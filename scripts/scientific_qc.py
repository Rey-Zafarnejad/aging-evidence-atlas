#!/usr/bin/env python3
"""Reconcile published Human Aging Atlas records with their source rows."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
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
    "transcriptomic": SOURCE_ROOT / "41586_2026_10542_MOESM4_ESM.xlsx",
    "epigenetic": SOURCE_ROOT / "13073_2023_1161_MOESM4_ESM.xlsx",
    "genageHuman": SOURCE_ROOT / "human_genes/genage_human.csv",
    "longevity": SOURCE_ROOT / "longevity_genes/longevity.csv",
    "genageModels": ROOT / "build/cache/genage_models/genage_models.csv",
    "orthology": ROOT / "build/cache/HOM_MouseHumanSequence.rpt",
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
    if right is None and (left is None or pd.isna(left)):
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
    if float(source_value) == 0:
        return published.get("qualifier") == "reported_zero" and published.get("value") == 0
    return published.get("qualifier") == "exact" and same_number(source_value, published.get("value"))


def tokens(value: Any) -> set[str]:
    if value is None or pd.isna(value):
        return set()
    return {item.strip() for item in re.split(r"[;,]", str(value)) if item.strip()}


def main() -> None:
    manifest = load(DATA / "manifest.json")
    report = load(DATA / "build-report.json")
    genes: dict[str, dict[str, Any]] = {}
    for chunk in manifest["chunks"]:
        genes.update(load(DATA / chunk["file"]))

    expected_hashes = {item["name"]: item["sha256"] for item in report["sourceFiles"]}
    for source in SOURCES.values():
        assert source.exists(), source
        assert sha256(source) == expected_hashes[source.name], source.name

    transcriptomic_sheets = {
        sheet: pd.read_excel(SOURCES["transcriptomic"], sheet_name=sheet)
        for sheet in pd.ExcelFile(SOURCES["transcriptomic"]).sheet_names
    }
    epigenetic_sheets = {
        sheet: pd.read_excel(SOURCES["epigenetic"], sheet_name=sheet, header=2)
        for sheet in ("S1", "S3", "S4")
    }
    genage_human = pd.read_csv(SOURCES["genageHuman"])
    genage_models = pd.read_csv(SOURCES["genageModels"])
    longevity = pd.read_csv(SOURCES["longevity"])
    orthology = pd.read_csv(SOURCES["orthology"], sep="\t", dtype=str)

    candidate_pairs: list[tuple[str, str, str]] = []
    for class_key, group in orthology.groupby("DB Class Key"):
        human = group[group["NCBI Taxon ID"].eq("9606")]
        mouse = group[group["NCBI Taxon ID"].eq("10090")]
        if len(human) == 1 and len(mouse) == 1:
            candidate_pairs.append(
                (
                    str(class_key),
                    str(human.iloc[0]["Symbol"]).upper(),
                    str(mouse.iloc[0]["EntrezGene ID"]),
                )
            )
    human_counts = Counter(item[1] for item in candidate_pairs)
    mouse_counts = Counter(item[2] for item in candidate_pairs)
    one_to_one_classes = {
        class_key
        for class_key, human_symbol, mouse_entrez in candidate_pairs
        if human_counts[human_symbol] == 1 and mouse_counts[mouse_entrez] == 1
    }

    counts = {
        "transcriptomic": 0,
        "epigeneticAge": 0,
        "epigeneticMortality": 0,
        "epigeneticSensitivity": 0,
        "longevityMap": 0,
        "genAgeHuman": 0,
        "genAgeMouse": 0,
    }

    for symbol, gene in genes.items():
        evidence = gene["evidence"]
        ortholog = gene.get("mouseOrtholog")
        if ortholog:
            assert ortholog["homologyClassId"] in one_to_one_classes
            assert ortholog["humanSymbol"] == symbol

        for record in evidence["transcriptomic"]:
            frame = transcriptomic_sheets[record["sourceSheet"]]
            row = frame.iloc[record["sourceRow"] - 2]
            assert ortholog
            assert str(int(row["Entrez.ID"])) == str(record["sourceMouseEntrezId"])
            assert str(row["Gene.symbol"]) == record["sourceMouseSymbol"]
            assert same_number(row["Slope"], record["slope"])
            assert same_probability(row["P.Value"], record["pValue"])
            assert same_probability(row["P.Adjusted"], record["adjustedPValue"])
            assert float(row["P.Adjusted"]) <= 0.05
            assert record["orthologyClassId"] == ortholog["homologyClassId"]
            counts["transcriptomic"] += 1

        for record in evidence["epigeneticAge"]:
            row = epigenetic_sheets["S1"].iloc[record["sourceRow"] - 4]
            assert str(row["CpG"]) == record["cpg"]
            assert {item["sourceSymbol"] for item in record["geneAnnotations"]}.issubset(tokens(row["Gene"]))
            assert same_number(row["Beta"], record["beta"])
            assert same_probability(row["p"], record["pValue"])
            counts["epigeneticAge"] += 1

        for record in evidence["epigeneticMortality"]:
            row = epigenetic_sheets["S3"].iloc[record["sourceRow"] - 4]
            assert str(row["CpG"]) == record["cpg"]
            assert {item["sourceSymbol"] for item in record["geneAnnotations"]}.issubset(tokens(row["Gene"]))
            assert same_number(row["HR"], record["hazardRatio"])
            assert same_probability(row["p"], record["pValue"])
            counts["epigeneticMortality"] += 1
            sensitivity = record["sensitivityAnalysis"]
            assert sensitivity
            sensitivity_row = epigenetic_sheets["S4"].iloc[sensitivity["sourceRow"] - 4]
            assert str(sensitivity_row["CpG"]) == record["cpg"]
            assert same_number(sensitivity_row["HR"], sensitivity["hazardRatio"])
            assert same_probability(sensitivity_row["p"], sensitivity["pValue"])
            counts["epigeneticSensitivity"] += 1

        for record in evidence["longevityMap"]:
            row = longevity.iloc[record["sourceRow"] - 2]
            assert str(row["Gene(s)"]) == record["sourceSymbol"]
            assert str(row["Association"]) == record["association"]
            assert same_number(row["PubMed"], record["pubmedId"])
            counts["longevityMap"] += 1

        if evidence["genAgeHuman"]:
            record = evidence["genAgeHuman"]
            row = genage_human.iloc[record["sourceRow"] - 2]
            assert str(row["symbol"]) == record["sourceSymbol"]
            assert same_number(row["GenAge ID"], record["genAgeId"])
            assert same_number(row["entrez gene id"], record["entrezGeneId"])
            counts["genAgeHuman"] += 1

        for record in evidence["genAgeMouse"]:
            row = genage_models.iloc[record["sourceRow"] - 2]
            assert str(row["organism"]) == "Mus musculus"
            assert str(row["symbol"]) == record["mouseSymbol"]
            assert same_number(row["entrez gene id"], record["mouseEntrezGeneId"])
            assert record["orthologyClassId"] in one_to_one_classes
            counts["genAgeMouse"] += 1

    expected_records = sum(
        value for key, value in counts.items() if key != "epigeneticSensitivity"
    )
    assert expected_records == manifest["metrics"]["evidenceRecords"]
    assert counts["epigeneticSensitivity"] == counts["epigeneticMortality"]

    print(
        json.dumps(
            {
                "status": "ok",
                "publishedGenesAudited": len(genes),
                "sourceRecordsReconciled": counts,
                "sourceChecksumsVerified": len(SOURCES),
                "oneToOneOrthologyVerified": True,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
