#!/usr/bin/env python3
"""Validate the generated static atlas data package."""

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
MODULES = ("tAge", "cAge", "bAge", "integrative", "longevity", "genAge")


def load(name: str):
    with (DATA / name).open(encoding="utf-8") as handle:
        return json.load(handle)


def walk(value, path="root"):
    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk(child, f"{path}[{index}]")
    elif isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        raise AssertionError(f"Non-finite number at {path}")


def main() -> None:
    manifest = load("manifest.json")
    search = load("search-index.json")
    datasets = load("datasets.json")
    report = load("build-report.json")

    assert manifest["version"] == "0.2.0"
    assert manifest["evidenceCollections"] == len(MODULES)
    assert manifest["geneCount"] == len(search) == report["selectedGeneCount"]
    assert len({row["symbol"] for row in search}) == len(search)
    assert [row["rank"] for row in search] == list(range(1, len(search) + 1))
    assert {dataset["id"] for dataset in datasets} == {*MODULES, "hgnc", "ncbi"}
    assert report["ncbi"]["recordsMatchedByHumanEntrezAndSymbol"] == manifest["geneCount"]
    assert not report["ncbi"]["symbolMismatchesExcluded"]
    assert report["tAge"]["selectionRuleVerified"]
    assert report["longevity"]["selectionRuleVerified"]

    loaded_symbols = set()
    observed_modules = set()
    for chunk in range(manifest["chunkCount"]):
        payload = load(f"genes-{chunk}.json")
        walk(payload)
        loaded_symbols.update(payload)
        for symbol, gene in payload.items():
            assert symbol == gene["symbol"]
            assert gene["rank"] >= 1
            assert 1 <= gene["evidenceProfile"]["sourceBreadth"] <= len(MODULES)
            assert gene["annotation"]["hgncId"].startswith("HGNC:")
            assert set(gene["sourceFlags"]) == set(MODULES)
            assert gene["evidenceProfile"]["sourceBreadth"] == sum(gene["sourceFlags"].values())
            observed_modules.update(source for source, present in gene["sourceFlags"].items() if present)

            for record in gene["tAgeRecords"]:
                assert record["adjustedPValue"]["value"] < 0.01
            for key in ("cAgeRecords", "bAgeRecords"):
                for record in gene[key]:
                    assert record["coordinateNote"].startswith("Chromosome and position refer to the CpG")
                    assert record["cpg"]
            for record in gene["integrativeRecords"]:
                assert record["coordinateNote"].endswith("in hg38")
            for record in gene["longevityRecords"]:
                assert record["association"].lower() == "significant"

    assert loaded_symbols == {row["symbol"] for row in search}
    assert observed_modules == set(MODULES)
    for row in search:
        assert row["symbol"] in load(f"genes-{row['chunk']}.json")
        assert set(row["sources"]).issubset(MODULES)

    maximum = max(row["sourceBreadth"] for row in search)
    assert maximum == manifest["maximumBreadth"]
    assert any(row["sourceBreadth"] == maximum for row in search)

    print(
        json.dumps(
            {
                "status": "ok",
                "publishedGenes": len(search),
                "chunks": manifest["chunkCount"],
                "evidenceModules": len(observed_modules),
                "maximumModuleBreadth": maximum,
                "featuredGenes": manifest["featuredGenes"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
