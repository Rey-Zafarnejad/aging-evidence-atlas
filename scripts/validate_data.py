#!/usr/bin/env python3
"""Validate the generated Human Aging Atlas static data package."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
SOURCE_KEYS = {"transcriptomic", "epigenetic", "longevityMap", "genAge"}
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
    assert manifest["schemaVersion"] == 2
    assert manifest["geneCount"] == len(search) == report["selection"]["publishedGenes"]
    assert len({row["symbol"] for row in search}) == len(search)
    assert REFERENCE_GENES.issubset({row["symbol"] for row in search})
    assert {source["key"] for source in sources} == SOURCE_KEYS
    assert manifest["metrics"]["publicSources"] == len(SOURCE_KEYS)
    assert manifest["chunks"]

    top_evidence = manifest["topEvidenceGenes"]
    assert len(top_evidence) == 30
    assert len(set(top_evidence)) == 30
    assert report["selection"]["topEvidenceGenesDerivedBeforeStaticSelection"] == top_evidence
    assert manifest["topEvidenceUniverseGeneCount"] >= manifest["geneCount"]
    search_by_symbol = {row["symbol"]: row for row in search}
    assert set(top_evidence).issubset(search_by_symbol)
    assert [search_by_symbol[symbol]["evidenceRank"] for symbol in top_evidence] == list(range(1, 31))
    assert all(
        row["evidenceRank"] is None
        for row in search
        if row["symbol"] not in set(top_evidence)
    )

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
        }
        assert gene["coverage"]["publicSources"] == [
            key for key in ("transcriptomic", "epigenetic", "longevityMap", "genAge") if expected_sources[key]
        ]

        records = (
            evidence["transcriptomic"]
            + evidence["epigeneticAge"]
            + evidence["epigeneticMortality"]
            + evidence["longevityMap"]
            + evidence["genAgeMouse"]
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
