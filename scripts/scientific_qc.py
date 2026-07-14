#!/usr/bin/env python3
"""Reconcile every published gene record with the source workbook."""

from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_ROOT = Path(
    "/Users/ReyZafarnejad/Documents/Harvard University/Internship/FAST PROSPR/Data"
)
SOURCES = {
    "atlas": SOURCE_ROOT / "Human Aging and Longevity Atlas Datasets.xlsx",
    "hgnc": ROOT / "build/cache/hgnc_complete_set.txt",
    "ncbi": ROOT / "build/cache/ncbi_gene_summaries.json",
}
MODULES = ("tAge", "cAge", "bAge", "Integrative", "LongevityMap", "GenAge")


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


def same_probability(source_value: Any, published: dict[str, Any]) -> bool:
    source_text = str(source_value).strip()
    if source_text.startswith("<"):
        return (
            published.get("qualifier") == "upper_bound"
            and published.get("display") == source_text
            and same_number(source_text[1:], published.get("value"))
        )
    return published.get("qualifier") == "exact" and same_number(
        source_value, published.get("value")
    )


def p_sort(probability: dict[str, Any] | None) -> float:
    if not probability or probability.get("value") is None:
        return 1.0
    value = float(probability["value"])
    return 1e-320 if value == 0 else value


def rank_key(gene: dict[str, Any]) -> tuple[Any, ...]:
    profile = gene["evidenceProfile"]
    stats = gene["statistics"]
    best_p = min(
        p_sort(stats.get("bestTAgeAdjustedP")),
        p_sort(stats.get("bestCAgeP")),
        p_sort(stats.get("bestBAgeP")),
    )
    return (
        -profile["sourceBreadth"],
        -profile["curatedBreadth"],
        -int(profile["integrativeConvergence"]),
        -stats["totalRecords"],
        best_p,
        gene["symbol"],
    )


def source_tokens(value: Any) -> set[str]:
    if value is None or pd.isna(value):
        return set()
    return {item.strip() for item in re.split(r"[;,]", str(value)) if item.strip()}


def main() -> None:
    manifest = load(DATA / "manifest.json")
    report = load(DATA / "build-report.json")
    genes: dict[str, dict[str, Any]] = {}
    for chunk in range(manifest["chunkCount"]):
        genes.update(load(DATA / f"genes-{chunk}.json"))

    expected_hashes = {item["name"]: item["sha256"] for item in report["sourceFiles"]}
    for source in SOURCES.values():
        assert source.exists(), source
        assert sha256(source) == expected_hashes[source.name], source.name

    sheets = {
        sheet: pd.read_excel(SOURCES["atlas"], sheet_name=sheet) for sheet in MODULES
    }

    # Verify the workbook's retained source records independently.
    tage_flag = pd.to_numeric(sheets["tAge"]["Include"], errors="coerce").fillna(0).eq(1)
    tage_rule = pd.to_numeric(sheets["tAge"]["P.Adjusted"], errors="coerce").lt(0.01)
    assert tage_flag.equals(tage_rule)
    assert int(tage_flag.sum()) == report["tAge"]["retainedRows"]

    longevity = sheets["LongevityMap"]
    longevity_flag = pd.to_numeric(longevity["Include"], errors="coerce").fillna(0).eq(1)
    helper_rule = (
        pd.to_numeric(longevity["Is significant?"], errors="coerce").fillna(0).eq(1)
        & pd.to_numeric(longevity["Is one gene?"], errors="coerce").fillna(0).eq(1)
        & pd.to_numeric(longevity["Gene name starts with letter?"], errors="coerce").fillna(0).eq(1)
    )
    corrected_rule = (
        pd.to_numeric(longevity["Is significant?"], errors="coerce").fillna(0).eq(1)
        & pd.to_numeric(longevity["Is one gene?"], errors="coerce").fillna(0).eq(1)
        & longevity["Gene"].fillna("").astype(str).str.match(r"^[A-Za-z]")
    )
    assert longevity_flag.equals(helper_rule)
    assert longevity_flag.equals(corrected_rule)
    assert int(longevity_flag.sum()) == report["longevity"]["retainedRows"]

    genage_flag = pd.to_numeric(sheets["GenAge"]["Include"], errors="coerce").fillna(0).eq(1)
    assert int(genage_flag.sum()) == report["genAge"]["retainedRows"]

    counts = {"tAge": 0, "cAge": 0, "bAge": 0, "integrative": 0, "longevity": 0, "genAge": 0}
    for symbol, gene in genes.items():
        record_ids: list[str] = []

        for record in gene["tAgeRecords"]:
            row = sheets["tAge"].iloc[record["sourceRow"] - 2]
            assert int(row["Include"]) == 1
            assert str(row["ID"]) == record["sourceSymbol"]
            assert same_number(row["Slope"], record["slope"])
            assert same_number(row["P.Adjusted"], record["adjustedPValue"]["value"])
            assert float(row["P.Adjusted"]) < 0.01
            record_ids.append(record["recordId"])
            counts["tAge"] += 1

        for module, key in (("cAge", "cAgeRecords"), ("bAge", "bAgeRecords")):
            for record in gene[key]:
                row = sheets[module].iloc[record["sourceRow"] - 2]
                assert str(row["CpG"]) == record["cpg"]
                assert set(record["sourceSymbols"]).issubset(source_tokens(row["Gene"]))
                assert same_number(row["Chrom"], record["cpgChromosome"])
                assert same_number(row["Position"], record["cpgPosition"])
                assert same_probability(row["p"], record["pValue"]), (
                    module,
                    symbol,
                    record["sourceRow"],
                    row["p"],
                    record["pValue"],
                )
                record_ids.append(record["recordId"])
                counts[module] += 1

        for record in gene["integrativeRecords"]:
            row = sheets["Integrative"].iloc[record["sourceRow"] - 2]
            assert str(row["ID"]) == record["sourceSymbol"]
            assert str(row["CpG ID"]) == record["cpg"]
            assert same_number(row["Position (hg38)"], record["cpgPositionHg38"])
            assert same_number(row["Distance to TSS"], record["distanceToTss"])
            assert same_number(row["Correlation with Age (MGB500)"], record["ageCorrelation"])
            record_ids.append(record["recordId"])
            counts["integrative"] += 1

        for record in gene["longevityRecords"]:
            row = sheets["LongevityMap"].iloc[record["sourceRow"] - 2]
            assert int(row["Include"]) == 1
            assert str(row["Gene"]) == record["sourceSymbol"]
            assert str(row["Association"]).lower() == record["association"].lower()
            assert same_number(row["PubMed"], record["pubmedId"])
            record_ids.append(record["recordId"])
            counts["longevity"] += 1

        if gene["genAgeRecord"]:
            record = gene["genAgeRecord"]
            row = sheets["GenAge"].iloc[record["sourceRow"] - 2]
            assert int(row["Include"]) == 1
            assert str(row["Gene"]) == record["sourceSymbol"]
            assert same_number(row["entrez gene id"], record["humanEntrezId"])
            assert same_number(row["Count of suporting references"], record["supportingReferenceCount"])
            record_ids.append(record["recordId"])
            counts["genAge"] += 1

        stats = gene["statistics"]
        assert len(record_ids) == len(set(record_ids)), f"Duplicate record for {symbol}"
        assert stats["tAgeRecords"] == len(gene["tAgeRecords"])
        assert stats["cAgeRecords"] == len(gene["cAgeRecords"])
        assert stats["bAgeRecords"] == len(gene["bAgeRecords"])
        assert stats["integrativeRecords"] == len(gene["integrativeRecords"])
        assert stats["longevityRecords"] == len(gene["longevityRecords"])
        assert stats["genAgeRecords"] == int(gene["genAgeRecord"] is not None)
        assert stats["totalRecords"] == len(record_ids)
        assert gene["evidenceProfile"]["sourceBreadth"] == sum(gene["sourceFlags"].values())

    ordered = sorted(genes.values(), key=lambda gene: gene["rank"])
    assert ordered == sorted(ordered, key=rank_key), "Published ranks do not match hierarchy"

    ncbi_cache = load(SOURCES["ncbi"])
    for gene in ordered:
        entrez = str(gene["annotation"]["humanEntrezId"])
        ncbi = ncbi_cache[entrez]
        ncbi_symbol = ncbi.get("nomenclaturesymbol") or ncbi.get("name")
        assert str(ncbi_symbol).upper() == gene["symbol"].upper()
        if gene["summary"]:
            assert gene["summary"] == str(ncbi.get("summary") or "").strip(), gene["symbol"]

    output = {
        "status": "ok",
        "publishedGenesAudited": len(genes),
        "sourceRecordsReconciled": counts,
        "sourceSelectionVerified": ["tAge", "LongevityMap", "GenAge"],
        "rankHierarchyVerified": True,
        "sourceChecksumsVerified": len(SOURCES),
    }
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()
