#!/usr/bin/env python3
"""Validate the generated static atlas data package."""

from __future__ import annotations

import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


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

    assert manifest["geneCount"] == 1000, manifest["geneCount"]
    assert len(search) == manifest["geneCount"]
    assert len({row["symbol"] for row in search}) == len(search)
    assert [row["rank"] for row in search] == list(range(1, len(search) + 1))
    assert len(datasets) == 6
    assert report["selectedGeneCount"] == manifest["geneCount"]
    assert report["ncbi"]["recordsMatchedByHumanEntrezAndSymbol"] == manifest["geneCount"]
    assert not report["ncbi"]["symbolMismatchesExcluded"]

    loaded_symbols = set()
    for chunk in range(manifest["chunkCount"]):
        payload = load(f"genes-{chunk}.json")
        walk(payload)
        loaded_symbols.update(payload)
        for symbol, gene in payload.items():
            assert symbol == gene["symbol"]
            assert gene["rank"] >= 1
            assert 1 <= gene["evidenceProfile"]["sourceBreadth"] <= 4
            assert gene["annotation"]["hgncId"].startswith("HGNC:")
            for record in gene["transcriptomicRecords"]:
                assert record["adjustedPValue"]["value"] <= 0.05
            for record in gene["epigeneticRecords"]:
                assert record["coordinateNote"].startswith("Chromosome and position refer to the CpG")

    assert loaded_symbols == {row["symbol"] for row in search}
    for row in search:
        assert row["symbol"] in load(f"genes-{row['chunk']}.json")

    broad = [row for row in search if row["sourceBreadth"] == 4]
    assert broad, "Expected at least one gene represented in all four evidence collections"
    print(
        json.dumps(
            {
                "status": "ok",
                "genes": len(search),
                "chunks": manifest["chunkCount"],
                "fourCollectionGenes": len(broad),
                "featuredGenes": manifest["featuredGenes"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
