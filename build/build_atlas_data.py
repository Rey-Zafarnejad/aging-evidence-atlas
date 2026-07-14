#!/usr/bin/env python3
"""Build the static Aging Evidence Atlas data package from source files.

The script never modifies source workbooks. It emits a compact search index,
chunked gene records, dataset metadata, and a reproducibility report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import time
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd


DEFAULT_DATA_ROOT = Path(
    "/Users/ReyZafarnejad/Documents/Harvard University/Internship/FAST PROSPR/Data"
)
DEFAULT_ATLAS_WORKBOOK = DEFAULT_DATA_ROOT / "Human Aging and Longevity Atlas Datasets.xlsx"
DEFAULT_HGNC = Path(__file__).resolve().parent / "cache/hgnc_complete_set.txt"
DEFAULT_NCBI_CACHE = Path(__file__).resolve().parent / "cache/ncbi_gene_summaries.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data"

TRANSCRIPTOMIC_DOI = "https://doi.org/10.1038/s41586-026-10542-3"
EPIGENETIC_DOI = "https://doi.org/10.1186/s13073-023-01161-y"
GENAGE_URL = "https://genomics.senescence.info/genes/human.html"
LONGEVITY_URL = "https://genomics.senescence.info/longevity/"
HGNC_URL = "https://www.genenames.org/download/"
NCBI_GENE_URL = "https://www.ncbi.nlm.nih.gov/gene/"

MODULE_SHEETS = ("GenAge", "LongevityMap", "cAge", "bAge", "tAge", "Integrative")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas-workbook", type=Path, default=DEFAULT_ATLAS_WORKBOOK)
    parser.add_argument("--hgnc", type=Path, default=DEFAULT_HGNC)
    parser.add_argument("--ncbi-cache", type=Path, default=DEFAULT_NCBI_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gene-limit", type=int, default=1000)
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--fetch-ncbi", action="store_true")
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def clean_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        return value or None
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return int(value)
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        if value.is_integer():
            return int(value)
        return float(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def numeric(value: Any) -> float | None:
    value = clean_scalar(value)
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"<\s*([0-9.]+(?:e[+-]?\d+)?)", value, flags=re.IGNORECASE)
    if match:
        return float(match.group(1))
    try:
        return float(value)
    except ValueError:
        return None


def probability(value: Any) -> dict[str, Any]:
    raw = clean_scalar(value)
    parsed = numeric(raw)
    qualifier = "exact"
    if isinstance(raw, str) and raw.startswith("<"):
        qualifier = "upper_bound"
    elif parsed == 0:
        qualifier = "reported_zero"
    return {"value": parsed, "display": str(raw) if raw is not None else None, "qualifier": qualifier}


def gene_tokens(value: Any) -> list[str]:
    value = clean_scalar(value)
    if not isinstance(value, str):
        return []
    tokens = []
    for token in re.split(r"[;,]", value):
        token = token.strip().strip('"\'')
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def split_pipe(value: Any) -> list[str]:
    value = clean_scalar(value)
    if not isinstance(value, str):
        return []
    return [item.strip() for item in value.split("|") if item.strip()]


def write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(
            payload,
            handle,
            ensure_ascii=True,
            allow_nan=False,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        )
        handle.write("\n")


def load_hgnc(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, str], dict[str, Any]]:
    frame = pd.read_csv(path, sep="\t", dtype=str, keep_default_na=False)
    frame = frame[frame["status"].eq("Approved")].copy()
    approved: dict[str, dict[str, Any]] = {}
    aliases: defaultdict[str, set[str]] = defaultdict(set)

    for _, row in frame.iterrows():
        symbol = row["symbol"].strip()
        if not symbol:
            continue
        record = {column: clean_scalar(row.get(column)) for column in frame.columns}
        approved[symbol.upper()] = record
        for field in ("alias_symbol", "prev_symbol"):
            for alias in split_pipe(row.get(field)):
                aliases[alias.upper()].add(symbol)

    alias_map = {
        alias: next(iter(symbols))
        for alias, symbols in aliases.items()
        if len(symbols) == 1 and alias not in approved
    }
    report = {
        "approvedRecords": len(approved),
        "unambiguousAliases": len(alias_map),
        "ambiguousAliasesExcluded": sum(1 for symbols in aliases.values() if len(symbols) > 1),
    }
    return approved, alias_map, report


def resolve_symbol(
    raw_symbol: Any,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[str | None, str]:
    raw = clean_scalar(raw_symbol)
    if not isinstance(raw, str):
        return None, "missing"
    key = raw.upper()
    if key in approved:
        return approved[key]["symbol"], "approved_symbol"
    if key in alias_map:
        return alias_map[key], "hgnc_alias"
    return None, "unmapped"


def load_atlas_summaries(path: Path) -> dict[str, dict[str, Any]]:
    frame = pd.read_excel(path, sheet_name="Datasets")
    summaries: dict[str, dict[str, Any]] = {}
    for _, row in frame.iterrows():
        dataset = clean_scalar(row.get("Dataset"))
        if not dataset:
            continue
        release = row.get("Release Date")
        release_date = None if pd.isna(release) else pd.Timestamp(release).date().isoformat()
        summaries[str(dataset)] = {
            "agingOrLongevity": clean_scalar(row.get("Aging or Longevity")),
            "module": clean_scalar(row.get("Module")),
            "curation": clean_scalar(row.get("Curated or Not curated")),
            "tissue": clean_scalar(row.get("Tissue")),
            "reportedGeneCount": clean_scalar(row.get("Count of genes")),
            "reportedAnalyteCount": clean_scalar(row.get("Count of analytes")),
            "reportedGenesIncluded": clean_scalar(row.get("Genes included")),
            "releaseDate": release_date,
            "population": clean_scalar(row.get("Population")),
            "cohorts": clean_scalar(row.get("Cohorts in training and testing")),
            "trainingSampleCount": clean_scalar(row.get("Count of samples in training")),
            "databaseUrl": clean_scalar(row.get("Database")),
            "datasetUrl": clean_scalar(row.get("Dataset.1")),
            "paperUrl": clean_scalar(row.get("Paper")),
        }
    return summaries


def resolved_row_symbols(
    value: Any,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
    mapping_counts: defaultdict[str, int],
) -> dict[str, list[tuple[str, str]]]:
    resolved: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
    for raw_symbol in gene_tokens(value):
        symbol, method = resolve_symbol(raw_symbol, approved, alias_map)
        mapping_counts[method] += 1
        if symbol:
            resolved[symbol].append((raw_symbol, method))
    return dict(resolved)


def mapping_fields(source_mappings: list[tuple[str, str]]) -> dict[str, Any]:
    source_symbols = [item[0] for item in source_mappings]
    methods = sorted({item[1] for item in source_mappings})
    return {
        "sourceSymbol": source_symbols[0],
        "sourceSymbols": source_symbols,
        "symbolMapping": methods[0] if len(methods) == 1 else "multiple",
        "symbolMappings": [
            {"sourceSymbol": raw, "method": method} for raw, method in source_mappings
        ],
    }


def load_curated_tage(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    frame = pd.read_excel(path, sheet_name="tAge")
    required = {"ID", "Entrez.ID", "Slope", "SE", "Pearson.corr", "P.Value", "P.Adjusted", "Include"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"tAge missing columns: {sorted(missing)}")
    include = pd.to_numeric(frame["Include"], errors="coerce").eq(1)
    criterion = pd.to_numeric(frame["P.Adjusted"], errors="coerce").lt(0.01)
    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    mapped_rows = 0
    for source_index, row in frame[include].iterrows():
        symbol, method = resolve_symbol(row.get("ID"), approved, alias_map)
        mapping_counts[method] += 1
        if not symbol:
            continue
        mapped_rows += 1
        slope = numeric(row.get("Slope"))
        records[symbol].append(
            {
                "recordId": f"tAge:{source_index + 2}",
                "sourceCollection": "tAge",
                "sourceFile": path.name,
                "sourceSheet": "tAge",
                "sourceRow": int(source_index + 2),
                "sourceSymbol": clean_scalar(row.get("ID")),
                "symbolMapping": method,
                "sourceEntrezId": clean_scalar(row.get("Entrez.ID")),
                "sourceEntrezIdNote": "Mouse-ortholog identifier as reported in the consolidated workbook",
                "endpoint": "Chronological age",
                "slope": slope,
                "direction": "Positive" if slope and slope > 0 else "Negative" if slope and slope < 0 else "Zero",
                "standardError": clean_scalar(row.get("SE")),
                "pearsonCorrelation": clean_scalar(row.get("Pearson.corr")),
                "pValue": probability(row.get("P.Value")),
                "adjustedPValue": probability(row.get("P.Adjusted")),
            }
        )
    return records, {
        "rows": len(frame),
        "retainedRows": int(include.sum()),
        "selectionRuleVerified": bool(include.equals(criterion)),
        "mappedRetainedRows": mapped_rows,
        "mappedGenes": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
    }


def load_curated_epigenetic(
    path: Path,
    sheet_name: str,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    frame = pd.read_excel(path, sheet_name=sheet_name)
    common = {"Gene", "CpG", "Chrom", "Position", "SE", "p"}
    specific = {"Beta"} if sheet_name == "cAge" else {"logHR", "Z", "HR", "HR_CI95_Low", "HR_CI95_High"}
    missing = (common | specific) - set(frame.columns)
    if missing:
        raise ValueError(f"{sheet_name} missing columns: {sorted(missing)}")
    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    rows_with_gene = 0
    mapped_assignments = 0
    for source_index, row in frame.iterrows():
        if gene_tokens(row.get("Gene")):
            rows_with_gene += 1
        resolved = resolved_row_symbols(row.get("Gene"), approved, alias_map, mapping_counts)
        for symbol, source_mappings in resolved.items():
            mapped_assignments += 1
            record = {
                "recordId": f"{sheet_name}:{source_index + 2}:{clean_scalar(row.get('CpG'))}:{symbol}",
                "sourceCollection": sheet_name,
                "sourceFile": path.name,
                "sourceSheet": sheet_name,
                "sourceRow": int(source_index + 2),
                **mapping_fields(source_mappings),
                "endpoint": "Chronological age" if sheet_name == "cAge" else "All-cause mortality",
                "cpg": clean_scalar(row.get("CpG")),
                "cpgChromosome": clean_scalar(row.get("Chrom")),
                "cpgPosition": clean_scalar(row.get("Position")),
                "coordinateNote": "Chromosome and position refer to the CpG locus, not the gene locus",
                "standardError": clean_scalar(row.get("SE")),
                "pValue": probability(row.get("p")),
            }
            if sheet_name == "cAge":
                record["beta"] = clean_scalar(row.get("Beta"))
            else:
                record.update(
                    {
                        "logHazardRatio": clean_scalar(row.get("logHR")),
                        "zStatistic": clean_scalar(row.get("Z")),
                        "hazardRatio": clean_scalar(row.get("HR")),
                        "hazardRatioCiLow": clean_scalar(row.get("HR_CI95_Low")),
                        "hazardRatioCiHigh": clean_scalar(row.get("HR_CI95_High")),
                    }
                )
            records[symbol].append(record)
    return records, {
        "rows": len(frame),
        "rowsWithGeneAnnotation": rows_with_gene,
        "rowsWithoutGeneAnnotation": len(frame) - rows_with_gene,
        "mappedGeneAssignments": mapped_assignments,
        "mappedGenes": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
    }


def load_curated_integrative(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    frame = pd.read_excel(path, sheet_name="Integrative")
    required = {"ID", "CpG ID", "Chromosome", "Position (hg38)", "Distance to TSS", "Correlation with Age (MGB500)"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"Integrative missing columns: {sorted(missing)}")
    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    mapped_rows = 0
    for source_index, row in frame.iterrows():
        symbol, method = resolve_symbol(row.get("ID"), approved, alias_map)
        mapping_counts[method] += 1
        if not symbol:
            continue
        mapped_rows += 1
        records[symbol].append(
            {
                "recordId": f"integrative:{source_index + 2}",
                "sourceCollection": "Integrative",
                "sourceFile": path.name,
                "sourceSheet": "Integrative",
                "sourceRow": int(source_index + 2),
                "sourceSymbol": clean_scalar(row.get("ID")),
                "symbolMapping": method,
                "cpg": clean_scalar(row.get("CpG ID")),
                "cpgChromosome": clean_scalar(row.get("Chromosome")),
                "cpgPositionHg38": clean_scalar(row.get("Position (hg38)")),
                "distanceToTss": clean_scalar(row.get("Distance to TSS")),
                "ageCorrelation": clean_scalar(row.get("Correlation with Age (MGB500)")),
                "coordinateNote": "Chromosome and position refer to the CpG locus in hg38",
            }
        )
    return records, {
        "rows": len(frame),
        "mappedRows": mapped_rows,
        "mappedGenes": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
    }


def load_curated_genage(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    frame = pd.read_excel(path, sheet_name="GenAge")
    required = {"Gene", "name", "entrez gene id", "uniprot", "why", "Count of suporting references", "Pubmed", "Include"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"GenAge missing columns: {sorted(missing)}")
    include = pd.to_numeric(frame["Include"], errors="coerce").eq(1)
    records: dict[str, dict[str, Any]] = {}
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    for source_index, row in frame[include].iterrows():
        symbol, method = resolve_symbol(row.get("Gene"), approved, alias_map)
        mapping_counts[method] += 1
        if not symbol:
            continue
        pubmed = clean_scalar(row.get("Pubmed"))
        records[symbol] = {
            "recordId": f"genAge:{source_index + 2}",
            "sourceCollection": "GenAge",
            "sourceFile": path.name,
            "sourceSheet": "GenAge",
            "sourceRow": int(source_index + 2),
            "sourceSymbol": clean_scalar(row.get("Gene")),
            "symbolMapping": method,
            "geneName": clean_scalar(row.get("name")),
            "humanEntrezId": clean_scalar(row.get("entrez gene id")),
            "uniprotEntry": clean_scalar(row.get("uniprot")),
            "selectionBasis": split_pipe(str(row.get("why", "")).replace(",", "|")),
            "selectionBasisRaw": clean_scalar(row.get("why")),
            "supportingReferenceCount": clean_scalar(row.get("Count of suporting references")),
            "pubmedId": pubmed,
            "pubmedUrl": f"https://pubmed.ncbi.nlm.nih.gov/{pubmed}/" if pubmed else None,
        }
    return records, {
        "rows": len(frame),
        "retainedRows": int(include.sum()),
        "mappedRetainedRows": len(records),
        "mappedGenes": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
    }


def load_curated_longevity(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    frame = pd.read_excel(path, sheet_name="LongevityMap")
    required = {"Gene", "Association", "Population", "Variant(s)", "Link", "PubMed", "Is significant?", "Is one gene?", "Gene name starts with letter?", "Include"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"LongevityMap missing columns: {sorted(missing)}")
    include = pd.to_numeric(frame["Include"], errors="coerce").eq(1)
    helper_rule = (
        pd.to_numeric(frame["Is significant?"], errors="coerce").eq(1)
        & pd.to_numeric(frame["Is one gene?"], errors="coerce").eq(1)
        & pd.to_numeric(frame["Gene name starts with letter?"], errors="coerce").eq(1)
    )
    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    mapped_rows = 0
    for source_index, row in frame[include].iterrows():
        symbol, method = resolve_symbol(row.get("Gene"), approved, alias_map)
        mapping_counts[method] += 1
        if not symbol:
            continue
        mapped_rows += 1
        pubmed = clean_scalar(row.get("PubMed"))
        records[symbol].append(
            {
                "recordId": f"longevity:{source_index + 2}",
                "sourceCollection": "LongevityMap",
                "sourceFile": path.name,
                "sourceSheet": "LongevityMap",
                "sourceRow": int(source_index + 2),
                "sourceSymbol": clean_scalar(row.get("Gene")),
                "symbolMapping": method,
                "association": "Significant",
                "population": clean_scalar(row.get("Population")),
                "variants": clean_scalar(row.get("Variant(s)")),
                "sourceLink": clean_scalar(row.get("Link")),
                "pubmedId": pubmed,
                "pubmedUrl": f"https://pubmed.ncbi.nlm.nih.gov/{pubmed}/" if pubmed else None,
            }
        )
    corrected_gene_rule = (
        frame["Association"].astype(str).str.lower().eq("significant")
        & ~frame["Gene"].fillna("").astype(str).str.contains(",", regex=False)
        & frame["Gene"].fillna("").astype(str).str.match(r"^[A-Za-z]")
    )
    return records, {
        "rows": len(frame),
        "retainedRows": int(include.sum()),
        "selectionRuleVerified": bool(include.equals(helper_rule) and include.equals(corrected_gene_rule)),
        "mappedRetainedRows": mapped_rows,
        "mappedGenes": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
    }


def p_sort_value(prob: dict[str, Any] | None) -> float:
    if not prob or prob.get("value") is None:
        return 1.0
    value = float(prob["value"])
    return 1e-320 if value == 0 else value


def build_curated_gene_record(
    symbol: str,
    hgnc: dict[str, Any],
    tage: list[dict[str, Any]],
    cage: list[dict[str, Any]],
    bage: list[dict[str, Any]],
    integrative: list[dict[str, Any]],
    longevity: list[dict[str, Any]],
    genage: dict[str, Any] | None,
) -> dict[str, Any]:
    source_flags = {
        "tAge": bool(tage),
        "cAge": bool(cage),
        "bAge": bool(bage),
        "integrative": bool(integrative),
        "longevity": bool(longevity),
        "genAge": genage is not None,
    }
    curated_flags = {
        "longevity": bool(longevity),
        "genAge": genage is not None,
    }
    best_tage = min(tage, key=lambda item: p_sort_value(item["adjustedPValue"])) if tage else None
    best_cage = min(cage, key=lambda item: p_sort_value(item["pValue"])) if cage else None
    best_bage = min(bage, key=lambda item: p_sort_value(item["pValue"])) if bage else None
    positive = sum(1 for record in tage if record["direction"] == "Positive")
    negative = sum(1 for record in tage if record["direction"] == "Negative")
    total_records = len(tage) + len(cage) + len(bage) + len(integrative) + len(longevity) + int(genage is not None)
    return {
        "symbol": symbol,
        "annotation": {
            "approvedName": clean_scalar(hgnc.get("name")),
            "hgncId": clean_scalar(hgnc.get("hgnc_id")),
            "chromosomeLocation": clean_scalar(hgnc.get("location")),
            "chromosome": re.match(r"^(\d+|X|Y|MT)", str(hgnc.get("location", ""))).group(1)
            if re.match(r"^(\d+|X|Y|MT)", str(hgnc.get("location", "")))
            else None,
            "locusGroup": clean_scalar(hgnc.get("locus_group")),
            "locusType": clean_scalar(hgnc.get("locus_type")),
            "humanEntrezId": clean_scalar(hgnc.get("entrez_id")),
            "ensemblGeneId": clean_scalar(hgnc.get("ensembl_gene_id")),
            "uniprotIds": split_pipe(hgnc.get("uniprot_ids")),
            "aliases": split_pipe(hgnc.get("alias_symbol")),
            "previousSymbols": split_pipe(hgnc.get("prev_symbol")),
            "hgncUrl": f"https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/{urllib.parse.quote(str(hgnc.get('hgnc_id', '')))}",
        },
        "summary": None,
        "summarySource": None,
        "sourceFlags": source_flags,
        "evidenceProfile": {
            "sourceBreadth": sum(source_flags.values()),
            "sourceCollectionsAvailable": [key for key, present in source_flags.items() if present],
            "curatedBreadth": sum(curated_flags.values()),
            "curatedCollectionsAvailable": [key for key, present in curated_flags.items() if present],
            "integrativeConvergence": bool(integrative),
            "supportingRecords": total_records,
            "curatedInGenAge": genage is not None,
        },
        "statistics": {
            "tAgeRecords": len(tage),
            "tAgePositive": positive,
            "tAgeNegative": negative,
            "bestTAgeAdjustedP": best_tage["adjustedPValue"] if best_tage else None,
            "cAgeRecords": len(cage),
            "cAgeCpGs": len({record["cpg"] for record in cage}),
            "bestCAgeP": best_cage["pValue"] if best_cage else None,
            "bAgeRecords": len(bage),
            "bAgeCpGs": len({record["cpg"] for record in bage}),
            "bestBAgeP": best_bage["pValue"] if best_bage else None,
            "integrativeRecords": len(integrative),
            "integrativeCpGs": len({record["cpg"] for record in integrative}),
            "longevityRecords": len(longevity),
            "genAgeRecords": int(genage is not None),
            "totalRecords": total_records,
        },
        "tAgeRecords": sorted(tage, key=lambda item: p_sort_value(item["adjustedPValue"])),
        "cAgeRecords": sorted(cage, key=lambda item: (p_sort_value(item["pValue"]), item["cpg"] or "")),
        "bAgeRecords": sorted(bage, key=lambda item: (p_sort_value(item["pValue"]), item["cpg"] or "")),
        "integrativeRecords": sorted(integrative, key=lambda item: (-(abs(numeric(item["ageCorrelation"]) or 0)), item["cpg"] or "")),
        "longevityRecords": sorted(longevity, key=lambda item: (str(item.get("pubmedId") or ""), item["sourceRow"])),
        "genAgeRecord": genage,
    }


def curated_selection_key(gene: dict[str, Any]) -> tuple[Any, ...]:
    profile = gene["evidenceProfile"]
    stats = gene["statistics"]
    best_p = min(
        p_sort_value(stats.get("bestTAgeAdjustedP")),
        p_sort_value(stats.get("bestCAgeP")),
        p_sort_value(stats.get("bestBAgeP")),
    )
    return (
        -profile["sourceBreadth"],
        -profile["curatedBreadth"],
        -int(profile["integrativeConvergence"]),
        -stats["totalRecords"],
        best_p,
        gene["symbol"],
    )


def fetch_ncbi_summaries(ids: Iterable[str], cache_path: Path) -> dict[str, dict[str, Any]]:
    cache: dict[str, dict[str, Any]] = {}
    if cache_path.exists():
        with cache_path.open(encoding="utf-8") as handle:
            cache = json.load(handle)
    missing = sorted({str(item) for item in ids if item and str(item) not in cache}, key=int)
    for start in range(0, len(missing), 150):
        batch = missing[start : start + 150]
        params = urllib.parse.urlencode(
            {"db": "gene", "id": ",".join(batch), "retmode": "json", "version": "2.0"}
        )
        url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?{params}"
        request = urllib.request.Request(url, headers={"User-Agent": "AgingEvidenceAtlas/1.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            payload = json.load(response)
        result = payload.get("result", {})
        for uid in result.get("uids", []):
            cache[str(uid)] = result.get(str(uid), {})
        time.sleep(0.4)
    write_json(cache_path, cache)
    return cache


def attach_ncbi_annotation(
    genes: list[dict[str, Any]],
    ncbi_cache: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    matched = 0
    summary_count = 0
    symbol_mismatches = []
    location_mismatches = []
    for gene in genes:
        entrez_id = gene["annotation"].get("humanEntrezId")
        if not entrez_id:
            continue
        ncbi = ncbi_cache.get(str(entrez_id))
        if not ncbi:
            continue
        ncbi_symbol = clean_scalar(ncbi.get("nomenclaturesymbol")) or clean_scalar(ncbi.get("name"))
        if ncbi_symbol and str(ncbi_symbol).upper() != gene["symbol"].upper():
            symbol_mismatches.append(
                {"symbol": gene["symbol"], "entrezId": entrez_id, "ncbiSymbol": ncbi_symbol}
            )
            continue
        matched += 1
        summary = clean_scalar(ncbi.get("summary"))
        if summary:
            gene["summary"] = summary
            gene["summarySource"] = {
                "label": "NCBI Gene",
                "url": f"{NCBI_GENE_URL}{entrez_id}",
                "humanEntrezId": str(entrez_id),
            }
            summary_count += 1
        ncbi_location = clean_scalar(ncbi.get("maplocation"))
        hgnc_location = gene["annotation"].get("chromosomeLocation")
        if ncbi_location and hgnc_location and str(ncbi_location) != str(hgnc_location):
            location_mismatches.append(
                {
                    "symbol": gene["symbol"],
                    "hgncLocation": hgnc_location,
                    "ncbiLocation": ncbi_location,
                }
            )
        gene["annotation"]["ncbiMapLocation"] = ncbi_location
        gene["annotation"]["ncbiChromosome"] = clean_scalar(ncbi.get("chromosome"))
        gene["annotation"]["ncbiUrl"] = f"{NCBI_GENE_URL}{entrez_id}"
    return {
        "recordsMatchedByHumanEntrezAndSymbol": matched,
        "summariesAttached": summary_count,
        "symbolMismatchesExcluded": symbol_mismatches,
        "locationDifferences": location_mismatches,
    }


def source_file_record(path: Path, kind: str) -> dict[str, Any]:
    return {
        "name": path.name,
        "kind": kind,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def curated_main() -> None:
    args = parse_args()
    source_paths = [args.atlas_workbook, args.hgnc]
    missing = [str(path) for path in source_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required source files: {missing}")
    if args.gene_limit <= 0 or args.chunk_size <= 0:
        raise ValueError("gene-limit and chunk-size must be positive")

    workbook = pd.ExcelFile(args.atlas_workbook)
    expected_sheets = {"Datasets", *MODULE_SHEETS}
    missing_sheets = sorted(expected_sheets - set(workbook.sheet_names))
    if missing_sheets:
        raise ValueError(f"Consolidated workbook missing sheets: {missing_sheets}")

    build_time = datetime.now(UTC).isoformat(timespec="seconds")
    summaries = load_atlas_summaries(args.atlas_workbook)
    approved, alias_map, hgnc_report = load_hgnc(args.hgnc)
    tage, tage_report = load_curated_tage(args.atlas_workbook, approved, alias_map)
    cage, cage_report = load_curated_epigenetic(args.atlas_workbook, "cAge", approved, alias_map)
    bage, bage_report = load_curated_epigenetic(args.atlas_workbook, "bAge", approved, alias_map)
    integrative, integrative_report = load_curated_integrative(args.atlas_workbook, approved, alias_map)
    longevity, longevity_report = load_curated_longevity(args.atlas_workbook, approved, alias_map)
    genage, genage_report = load_curated_genage(args.atlas_workbook, approved, alias_map)

    all_symbols = sorted(
        set(tage) | set(cage) | set(bage) | set(integrative) | set(longevity) | set(genage)
    )
    all_genes = [
        build_curated_gene_record(
            symbol,
            approved[symbol.upper()],
            tage.get(symbol, []),
            cage.get(symbol, []),
            bage.get(symbol, []),
            integrative.get(symbol, []),
            longevity.get(symbol, []),
            genage.get(symbol),
        )
        for symbol in all_symbols
        if symbol.upper() in approved
    ]
    all_genes.sort(key=curated_selection_key)
    selected = all_genes[: args.gene_limit]

    ncbi_ids = [gene["annotation"].get("humanEntrezId") for gene in selected]
    ncbi_cache: dict[str, dict[str, Any]] = {}
    if args.ncbi_cache.exists():
        with args.ncbi_cache.open(encoding="utf-8") as handle:
            ncbi_cache = json.load(handle)
    if args.fetch_ncbi:
        ncbi_cache = fetch_ncbi_summaries(ncbi_ids, args.ncbi_cache)
    ncbi_report = attach_ncbi_annotation(selected, ncbi_cache)

    output = args.output_dir
    output.mkdir(parents=True, exist_ok=True)
    for old_chunk in output.glob("genes-*.json"):
        old_chunk.unlink()

    for rank, gene in enumerate(selected, start=1):
        gene["rank"] = rank
        gene["selectionNote"] = (
            "Deterministic browsing order: module breadth, curated-module breadth, integrative "
            "convergence, supporting-record count, then source statistical support. The rank is "
            "not a causal, clinical, or biological-importance score."
        )

    search_index = []
    for index, gene in enumerate(selected):
        chunk = index // args.chunk_size
        stats = gene["statistics"]
        profile = gene["evidenceProfile"]
        search_index.append(
            {
                "symbol": gene["symbol"],
                "name": gene["annotation"].get("approvedName"),
                "location": gene["annotation"].get("chromosomeLocation"),
                "rank": gene["rank"],
                "chunk": chunk,
                "sourceBreadth": profile["sourceBreadth"],
                "curatedBreadth": profile["curatedBreadth"],
                "supportingRecords": profile["supportingRecords"],
                "tAgeRecords": stats["tAgeRecords"],
                "cAgeRecords": stats["cAgeRecords"],
                "bAgeRecords": stats["bAgeRecords"],
                "integrativeRecords": stats["integrativeRecords"],
                "longevityRecords": stats["longevityRecords"],
                "curatedInGenAge": profile["curatedInGenAge"],
                "sources": profile["sourceCollectionsAvailable"],
            }
        )

    chunk_count = math.ceil(len(selected) / args.chunk_size)
    for chunk in range(chunk_count):
        start = chunk * args.chunk_size
        payload = {gene["symbol"]: gene for gene in selected[start : start + args.chunk_size]}
        write_json(output / f"genes-{chunk}.json", payload, compact=True)

    module_reports = {
        "tAge": tage_report,
        "cAge": cage_report,
        "bAge": bage_report,
        "integrative": integrative_report,
        "longevity": longevity_report,
        "genAge": genage_report,
    }
    source_records = [
        source_file_record(args.atlas_workbook, "consolidated evidence workbook"),
        source_file_record(args.hgnc, "HGNC annotation reference"),
    ]
    if args.ncbi_cache.exists():
        source_records.append(source_file_record(args.ncbi_cache, "NCBI Gene summary cache"))

    module_definitions = [
        (
            "tAge",
            "Transcriptomic age associations",
            "tAge",
            "Human multi-tissue transcriptomic associations with chronological age",
            TRANSCRIPTOMIC_DOI,
        ),
        (
            "cAge",
            "Chronological-age CpG associations",
            "cAge",
            "Gene-annotated blood CpGs associated with chronological age",
            EPIGENETIC_DOI,
        ),
        (
            "bAge",
            "Mortality-associated CpGs",
            "bAge",
            "Gene-annotated blood CpGs associated with all-cause mortality",
            summaries.get("bAge", {}).get("paperUrl") or EPIGENETIC_DOI,
        ),
        (
            "integrative",
            "Integrative transcriptomic-epigenetic evidence",
            "Integrative",
            "Gene-linked CpGs with age correlations and distance to transcription start site",
            summaries.get("Integrative", {}).get("paperUrl"),
        ),
        (
            "longevity",
            "LongevityMap significant single-gene associations",
            "LongevityMap",
            "Curated human genetic association reports for longevity",
            LONGEVITY_URL,
        ),
        (
            "genAge",
            "GenAge curated human ageing genes",
            "GenAge",
            "Curated human genes associated with ageing biology",
            GENAGE_URL,
        ),
    ]
    datasets = [
        {
            "id": module_id,
            "name": name,
            "shortName": short_name,
            "sourceFile": args.atlas_workbook.name,
            "sourceSheet": short_name,
            "publicationUrl": publication_url,
            "scope": scope,
            "summaryMetadata": summaries.get(short_name, {}),
            "report": module_reports[module_id],
        }
        for module_id, name, short_name, scope, publication_url in module_definitions
    ]
    datasets.extend(
        [
            {
                "id": "hgnc",
                "name": "HGNC complete approved gene set",
                "shortName": "HGNC",
                "sourceFile": args.hgnc.name,
                "sourceSheet": None,
                "publicationUrl": HGNC_URL,
                "scope": "Approved human gene symbols, names, identifiers, and cytogenetic locations",
                "report": hgnc_report,
            },
            {
                "id": "ncbi",
                "name": "NCBI Gene summaries",
                "shortName": "NCBI Gene",
                "sourceFile": args.ncbi_cache.name,
                "sourceSheet": None,
                "publicationUrl": NCBI_GENE_URL,
                "scope": "Human gene summaries matched by HGNC Entrez Gene ID and approved symbol",
                "report": ncbi_report,
            },
        ]
    )

    breadth_counts: defaultdict[str, int] = defaultdict(int)
    for gene in selected:
        breadth_counts[str(gene["evidenceProfile"]["sourceBreadth"])] += 1
    maximum_breadth = max((gene["evidenceProfile"]["sourceBreadth"] for gene in selected), default=0)
    featured = [
        gene["symbol"]
        for gene in selected
        if gene["evidenceProfile"]["sourceBreadth"] == maximum_breadth
    ][:16]
    if len(featured) < 12:
        featured = [gene["symbol"] for gene in selected[:16]]

    manifest = {
        "atlasName": "Aging Evidence Atlas",
        "version": "0.2.0",
        "generatedAt": build_time,
        "geneCount": len(selected),
        "candidateGeneCount": len(all_genes),
        "chunkSize": args.chunk_size,
        "chunkCount": chunk_count,
        "featuredGenes": featured,
        "evidenceCollections": 6,
        "maximumBreadth": maximum_breadth,
        "breadthCounts": dict(sorted(breadth_counts.items())),
        "moduleRows": {
            "tAge": tage_report["retainedRows"],
            "cAge": cage_report["rows"],
            "bAge": bage_report["rows"],
            "integrative": integrative_report["rows"],
            "longevity": longevity_report["retainedRows"],
            "genAge": genage_report["retainedRows"],
        },
        "methodStatement": (
            "Evidence components remain separate; rank is a browsing aid, not a score."
        ),
    }
    build_report = {
        "generatedAt": build_time,
        "parameters": {"geneLimit": args.gene_limit, "chunkSize": args.chunk_size},
        "sourceFiles": source_records,
        "workbookSheets": workbook.sheet_names,
        "datasetSummaries": summaries,
        "hgnc": hgnc_report,
        **module_reports,
        "ncbi": ncbi_report,
        "selectedGeneCount": len(selected),
        "candidateGeneCount": len(all_genes),
        "featuredGenes": featured,
        "selectedSymbols": [gene["symbol"] for gene in selected],
    }

    write_json(output / "manifest.json", manifest)
    write_json(output / "search-index.json", search_index, compact=True)
    write_json(output / "datasets.json", datasets)
    write_json(output / "build-report.json", build_report)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    curated_main()
