#!/usr/bin/env python3
"""Reconcile generated gene records against the original source rows."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_ROOT = Path(
    "/Users/ReyZafarnejad/Documents/Harvard University/Internship/FAST PROSPR/Data"
)
SOURCES = {
    "transcriptomic": SOURCE_ROOT / "41586_2026_10542_MOESM4_ESM.xlsx",
    "epigenetic": SOURCE_ROOT / "13073_2023_1161_MOESM4_ESM.xlsx",
    "genage": SOURCE_ROOT / "human_genes/genage_human.csv",
    "longevity": SOURCE_ROOT / "longevity_genes/longevity.csv",
    "hgnc": ROOT / "build/cache/hgnc_complete_set.txt",
}


def load(path: Path) -> Any:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def same_number(left: Any, right: Any) -> bool:
    if left is None and (right is None or pd.isna(right)):
        return True
    try:
        return math.isclose(float(left), float(right), rel_tol=1e-12, abs_tol=0.0)
    except (TypeError, ValueError):
        return str(left) == str(right)


def p_sort(prob: dict[str, Any] | None) -> float:
    if not prob or prob.get("value") is None:
        return 1.0
    value = float(prob["value"])
    return 1e-320 if value == 0 else value


def rank_key(gene: dict[str, Any]) -> tuple[Any, ...]:
    profile = gene["evidenceProfile"]
    stats = gene["statistics"]
    significant_records = (
        stats["transcriptomicRecords"]
        + stats["epigeneticRecords"]
        + stats["longevitySignificant"]
    )
    return (
        -profile["sourceBreadth"],
        -profile["humanEvidenceTypes"],
        -int(profile["curatedInGenAge"]),
        -stats["longevitySignificant"],
        -profile["analysisUnits"],
        -significant_records,
        p_sort(stats.get("bestTranscriptomicAdjustedP")),
        p_sort(stats.get("bestEpigeneticP")),
        gene["symbol"],
    )


def main() -> None:
    manifest = load(DATA / "manifest.json")
    report = load(DATA / "build-report.json")
    genes: dict[str, dict[str, Any]] = {}
    for chunk in range(manifest["chunkCount"]):
        genes.update(load(DATA / f"genes-{chunk}.json"))

    # File identity: verify the published audit points to the exact local inputs.
    expected_hashes = {item["name"]: item["sha256"] for item in report["sourceFiles"]}
    for source in SOURCES.values():
        assert source.exists(), source
        assert sha256(source) == expected_hashes[source.name], source.name

    transcript_workbook = pd.ExcelFile(SOURCES["transcriptomic"])
    transcript_sheet_names = [item["sheet"] for item in report["transcriptomic"]["sheets"]]
    transcript_sheets = {
        sheet: transcript_workbook.parse(sheet_name=sheet) for sheet in transcript_sheet_names
    }
    epigenetic_sheets = {
        sheet: pd.read_excel(SOURCES["epigenetic"], sheet_name=sheet, header=2)
        for sheet in ("S1", "S2", "S3", "S4")
    }
    genage = pd.read_csv(SOURCES["genage"], encoding="utf-8-sig")
    longevity = pd.read_csv(SOURCES["longevity"], encoding="utf-8-sig")

    counts = {"transcriptomic": 0, "epigenetic": 0, "genAge": 0, "longevity": 0}
    for symbol, gene in genes.items():
        record_ids = []
        for record in gene["transcriptomicRecords"]:
            row = transcript_sheets[record["sourceSheet"]].iloc[record["sourceRow"] - 2]
            assert str(row["Gene.symbol"]) == record["sourceSymbol"]
            assert same_number(row["Slope"], record["slope"])
            assert same_number(row["P.Adjusted"], record["adjustedPValue"]["value"])
            assert float(row["P.Adjusted"]) <= 0.05
            record_ids.append(record["recordId"])
            counts["transcriptomic"] += 1

        for record in gene["epigeneticRecords"]:
            row = epigenetic_sheets[record["sourceSheet"]].iloc[record["sourceRow"] - 4]
            assert str(row["CpG"]) == record["cpg"]
            assert all(symbol in str(row["Gene"]).split(";") for symbol in record["sourceSymbols"])
            assert same_number(row["Chrom"], record["cpgChromosome"])
            assert same_number(row["Position"], record["cpgPosition"])
            record_ids.append(record["recordId"])
            counts["epigenetic"] += 1

        for record in gene["longevityRecords"]:
            row = longevity.iloc[record["sourceRow"] - 2]
            assert same_number(row["id"], record["longevityMapId"])
            assert all(symbol in str(row["Gene(s)"]).split(",") for symbol in record["sourceSymbols"])
            assert str(row["Association"]).lower() == record["association"].lower()
            record_ids.append(record["recordId"])
            counts["longevity"] += 1

        if gene["genAgeRecord"]:
            record = gene["genAgeRecord"]
            row = genage.iloc[record["sourceRow"] - 2]
            assert same_number(row["GenAge ID"], record["genAgeId"])
            assert str(row["symbol"]) == record["sourceSymbol"]
            record_ids.append(record["recordId"])
            counts["genAge"] += 1

        assert len(record_ids) == len(set(record_ids)), f"Duplicate record for {symbol}"
        assert gene["statistics"]["transcriptomicRecords"] == len(gene["transcriptomicRecords"])
        assert gene["statistics"]["epigeneticRecords"] == len(gene["epigeneticRecords"])
        assert gene["statistics"]["longevityRecords"] == len(gene["longevityRecords"])

    ordered = sorted(genes.values(), key=lambda gene: gene["rank"])
    assert ordered == sorted(ordered, key=rank_key), "Published ranks do not match hierarchy"

    ncbi_cache = load(ROOT / "build/cache/ncbi_gene_summaries.json")
    for gene in ordered:
        entrez = str(gene["annotation"]["humanEntrezId"])
        ncbi = ncbi_cache[entrez]
        ncbi_symbol = ncbi.get("nomenclaturesymbol") or ncbi.get("name")
        assert str(ncbi_symbol).upper() == gene["symbol"].upper()
        if gene["summary"]:
            assert gene["summary"] == ncbi.get("summary")

    output = {
        "status": "ok",
        "selectedGenes": len(genes),
        "sourceRecordsReconciled": counts,
        "ncbiSymbolMatches": len(ordered),
        "ncbiSummaries": sum(1 for gene in ordered if gene["summary"]),
        "rankHierarchyVerified": True,
        "sourceChecksumsVerified": len(SOURCES),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
