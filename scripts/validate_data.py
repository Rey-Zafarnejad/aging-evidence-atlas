#!/usr/bin/env python3
"""Validate the generated Human Aging Atlas static data package."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_KEYS = {"transcriptomic", "epigenetic", "longevityMap", "genAge", "organAge"}
LAYER_KEYS = {"genomics", "epigenomics", "transcriptomics", "proteomics"}
REFERENCE_GENES = {"TP53", "CDKN2A", "MTOR", "SIRT1", "APOE", "TERT", "FOXO3", "IGF1", "FKBP5"}


def load(name: str) -> Any:
    with (DATA / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def walk(value: Any, path: str = "root") -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            walk(child, f"{path}[{index}]")
    elif isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise AssertionError(f"Non-finite number at {path}")


def main() -> None:
    manifest = load("manifest.json")
    search = load("search-index.json")
    sources = load("sources.json")
    report = load("build-report.json")

    assert manifest["title"] == "Human Aging Atlas"
    assert manifest["schemaVersion"] == 3
    assert manifest["geneCount"] == len(search) == report["selection"]["publishedGenes"]
    assert len({row["symbol"] for row in search}) == len(search)
    assert REFERENCE_GENES.issubset({row["symbol"] for row in search})
    assert {source["key"] for source in sources} == SOURCE_KEYS
    assert manifest["metrics"]["publicSources"] == len(SOURCE_KEYS)
    assert {source["layerKey"] for source in sources} == LAYER_KEYS
    assert manifest["metrics"]["activeEvidenceLayers"] == len(LAYER_KEYS)
    assert manifest["chunks"]
    search_by_symbol = {row["symbol"]: row for row in search}

    genes: dict[str, dict[str, Any]] = {}
    for chunk in manifest["chunks"]:
        payload = load(chunk["file"])
        assert len(payload) == chunk["geneCount"]
        walk(payload)
        genes.update(payload)

    assert set(genes) == {row["symbol"] for row in search}
    assert len(genes) == manifest["geneCount"]

    total_records = 0
    observed_sources: set[str] = set()
    record_ids: set[str] = set()
    for symbol, gene in genes.items():
        assert symbol == gene["symbol"]
        assert gene["annotation"]["hgncId"].startswith("HGNC:")
        assert set(gene["coverage"]["publicSources"]).issubset(SOURCE_KEYS)
        assert gene["coverage"]["publicSourceCount"] == len(gene["coverage"]["publicSources"])
        observed_sources.update(gene["coverage"]["publicSources"])

        evidence = gene["evidence"]
        expected_sources = {
            "transcriptomic": bool(evidence["transcriptomic"]),
            "epigenetic": bool(evidence["epigeneticAge"] or evidence["epigeneticMortality"]),
            "longevityMap": bool(evidence["longevityMap"]),
            "genAge": bool(evidence["genAgeHuman"] or evidence["genAgeMouse"]),
            "organAge": bool(evidence["organAge"]),
        }
        assert gene["coverage"]["publicSources"] == [
            key for key in ("transcriptomic", "epigenetic", "longevityMap", "genAge", "organAge") if expected_sources[key]
        ]
        expected_layers = []
        genomic_sources = [label for present, label in ((expected_sources["genAge"], "GenAge"), (expected_sources["longevityMap"], "LongevityMap")) if present]
        epigenomic_sources = [label for present, label in ((bool(evidence["epigeneticAge"]), "cAge"), (bool(evidence["epigeneticMortality"]), "bAge")) if present]
        if genomic_sources:
            expected_layers.append({"key": "genomics", "sources": genomic_sources})
        if epigenomic_sources:
            expected_layers.append({"key": "epigenomics", "sources": epigenomic_sources})
        if expected_sources["transcriptomic"]:
            expected_layers.append({"key": "transcriptomics", "sources": ["tAge"]})
        if expected_sources["organAge"]:
            expected_layers.append({"key": "proteomics", "sources": ["OrganAge"]})
        assert gene["coverage"]["evidenceLayers"] == expected_layers
        assert gene["coverage"]["evidenceLayerCount"] == len(expected_layers)
        assert search_by_symbol[symbol]["evidenceLayers"] == expected_layers
        assert search_by_symbol[symbol]["evidenceLayerCount"] == len(expected_layers)

        records = (
            evidence["transcriptomic"]
            + evidence["epigeneticAge"]
            + evidence["epigeneticMortality"]
            + evidence["longevityMap"]
            + evidence["genAgeMouse"]
            + evidence["organAge"]
            + ([evidence["genAgeHuman"]] if evidence["genAgeHuman"] else [])
        )
        stats = gene["statistics"]
        assert stats["totalEvidenceRecords"] == len(records)
        assert stats["transcriptomicRecords"] == len(evidence["transcriptomic"])
        assert stats["epigeneticAgeCpGs"] == len({item["cpg"] for item in evidence["epigeneticAge"]})
        assert stats["epigeneticMortalityCpGs"] == len({item["cpg"] for item in evidence["epigeneticMortality"]})
        assert stats["longevityAssociations"] == len(evidence["longevityMap"])
        assert stats["genAgeHumanRecords"] == int(evidence["genAgeHuman"] is not None)
        assert stats["genAgeMouseRecords"] == len(evidence["genAgeMouse"])
        assert stats["organAgeProteinOrganRecords"] == len(evidence["organAge"])
        assert stats["organAgeOrgans"] == sorted({item["organ"] for item in evidence["organAge"]})
        total_records += len(records)

        for record in records:
            assert record["recordId"] not in record_ids, record["recordId"]
            record_ids.add(record["recordId"])
        for record in evidence["transcriptomic"]:
            assert record["adjustedPValue"]["value"] <= 0.05
            assert gene["mouseOrtholog"]
            assert record["humanSymbol"] == symbol
            if record["cohort"] == "ITP":
                assert record["organism"] == "Mouse"
        for record in evidence["epigeneticMortality"]:
            assert record["cpg"]
            if record["sensitivityAnalysis"]:
                assert record["sensitivityAnalysis"]["sourceSheet"] == "S4"
        for record in evidence["longevityMap"]:
            assert str(record["association"]).lower() == "significant"
        for record in evidence["organAge"]:
            assert record["organism"] == "Human"
            assert record["modelCount"] == 500
            assert 1 <= record["selectedModels"] <= record["modelCount"]
            assert record["coefficientDirection"] in {"Positive", "Negative"}

        ortholog = gene.get("mouseOrtholog")
        if ortholog:
            assert ortholog["humanSymbol"] == symbol
            assert ortholog["mappingType"] == "one-to-one"

    assert observed_sources == SOURCE_KEYS
    assert total_records == manifest["metrics"]["evidenceRecords"]
    for row in search:
        assert row["symbol"] in load(f"genes-{row['chunk']}.json")

    print(
        json.dumps(
            {
                "status": "ok",
                "publishedGenes": len(genes),
                "chunks": len(manifest["chunks"]),
                "publicSources": len(observed_sources),
                "evidenceRecords": total_records,
                "referenceGenesVerified": sorted(REFERENCE_GENES),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
