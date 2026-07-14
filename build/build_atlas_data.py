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
DEFAULT_TRANSCRIPTOMIC = DEFAULT_DATA_ROOT / "41586_2026_10542_MOESM4_ESM.xlsx"
DEFAULT_EPIGENETIC = DEFAULT_DATA_ROOT / "13073_2023_1161_MOESM4_ESM.xlsx"
DEFAULT_GENAGE = DEFAULT_DATA_ROOT / "human_genes/genage_human.csv"
DEFAULT_LONGEVITY = DEFAULT_DATA_ROOT / "longevity_genes/longevity.csv"
DEFAULT_HGNC = Path(__file__).resolve().parent / "cache/hgnc_complete_set.txt"
DEFAULT_NCBI_CACHE = Path(__file__).resolve().parent / "cache/ncbi_gene_summaries.json"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data"

TRANSCRIPTOMIC_DOI = "https://doi.org/10.1038/s41586-026-10542-3"
EPIGENETIC_DOI = "https://doi.org/10.1186/s13073-023-01161-y"
GENAGE_URL = "https://genomics.senescence.info/genes/human.html"
LONGEVITY_URL = "https://genomics.senescence.info/longevity/"
HGNC_URL = "https://www.genenames.org/download/"
NCBI_GENE_URL = "https://www.ncbi.nlm.nih.gov/gene/"

TRANSCRIPTOMIC_EXPECTED_SHEETS = [
    "(A) ITP Chronological age",
    "(B) ITP Normalized age",
    "(C) ITP Normalized age, adj.",
    "(D) ITP Mortality rate",
    "(E) ITP Mortality rate, adj.",
    "(F) ITP Max lifespan",
    "(G) ITP Max lifespan, adj.",
    "(H) Rodents Chronological age",
    "(I) Rodents Normalized age",
    "(J) Rodents Normalized age, adj",
    "(K) Rodents Mortality rate",
    "(L) Rodents Mortality rate, adj",
    "(M) Rodents Max lifespan",
    "(N) Rodents Max lifespan, adj",
    "(O) Mouse aging multi-tissue",
    "(P) Rat aging multi-tissue",
    "(Q) Macaque aging multi-tissue",
    "(R) Human aging multi-tissue",
]

EPIGENETIC_TABLES = {
    "S1": {
        "endpoint": "Chronological age",
        "analysis": "Linear CpG-age EWAS",
        "title": "Top 10,000 epigenome-wide significant linear CpG-age associations",
    },
    "S2": {
        "endpoint": "Chronological age",
        "analysis": "Quadratic CpG-age EWAS",
        "title": "Top 10,000 epigenome-wide significant quadratic CpG-age associations",
    },
    "S3": {
        "endpoint": "All-cause mortality",
        "analysis": "Mortality EWAS",
        "title": "Epigenome-wide significant CpG associations with all-cause mortality",
    },
    "S4": {
        "endpoint": "All-cause mortality",
        "analysis": "Mortality EWAS with relatedness adjustment",
        "title": "Mortality CpG associations replicated with coxme relatedness adjustment",
    },
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transcriptomic", type=Path, default=DEFAULT_TRANSCRIPTOMIC)
    parser.add_argument("--epigenetic", type=Path, default=DEFAULT_EPIGENETIC)
    parser.add_argument("--genage", type=Path, default=DEFAULT_GENAGE)
    parser.add_argument("--longevity", type=Path, default=DEFAULT_LONGEVITY)
    parser.add_argument("--hgnc", type=Path, default=DEFAULT_HGNC)
    parser.add_argument("--ncbi-cache", type=Path, default=DEFAULT_NCBI_CACHE)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gene-limit", type=int, default=1000)
    parser.add_argument("--chunk-size", type=int, default=100)
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


def classify_transcript_sheet(sheet_name: str) -> dict[str, str]:
    label = re.sub(r"^\([A-Z]\)\s*", "", sheet_name).strip()
    adjusted = bool(re.search(r",?\s*adj\.?$", label, flags=re.IGNORECASE))
    clean = re.sub(r",?\s*adj\.?$", "", label, flags=re.IGNORECASE).strip()
    if clean.startswith("ITP "):
        family = "ITP"
        endpoint = clean.removeprefix("ITP ")
        population = "Mouse ITP liver"
    elif clean.startswith("Rodents "):
        family = "Rodents"
        endpoint = clean.removeprefix("Rodents ")
        population = "Mouse and rat multi-tissue"
    elif clean.endswith(" aging multi-tissue"):
        family = clean.removesuffix(" aging multi-tissue")
        endpoint = "Chronological age"
        population = f"{family} multi-tissue"
    else:
        family = clean.split()[0]
        endpoint = clean
        population = family
    return {
        "family": family,
        "endpoint": endpoint,
        "model": "Age-adjusted" if adjusted else "Unadjusted",
        "population": population,
        "label": label,
    }


def load_transcriptomic(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    workbook = pd.ExcelFile(path)
    if workbook.sheet_names != TRANSCRIPTOMIC_EXPECTED_SHEETS:
        missing = sorted(set(TRANSCRIPTOMIC_EXPECTED_SHEETS) - set(workbook.sheet_names))
        extra = sorted(set(workbook.sheet_names) - set(TRANSCRIPTOMIC_EXPECTED_SHEETS))
        raise ValueError(f"Unexpected transcriptomic sheets. Missing={missing}, extra={extra}")

    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    sheet_report = []
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    total_rows = 0
    significant_rows = 0

    for sheet_name in workbook.sheet_names:
        frame = pd.read_excel(path, sheet_name=sheet_name)
        required = {"Entrez.ID", "Gene.symbol", "Slope", "P.Value", "P.Adjusted"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{sheet_name} missing columns: {sorted(missing)}")
        meta = classify_transcript_sheet(sheet_name)
        total_rows += len(frame)
        significant = frame[pd.to_numeric(frame["P.Adjusted"], errors="coerce").le(0.05)].copy()
        significant_rows += len(significant)
        mapped_rows = 0

        for source_row, row in significant.iterrows():
            symbol, method = resolve_symbol(row.get("Gene.symbol"), approved, alias_map)
            mapping_counts[method] += 1
            if not symbol:
                continue
            mapped_rows += 1
            support_metric = "SE" if "SE" in frame.columns else "logCPM"
            association_metric = "Pearson.corr" if "Pearson.corr" in frame.columns else "LR"
            slope = numeric(row.get("Slope"))
            records[symbol].append(
                {
                    "recordId": f"transcriptomic:{sheet_name}:{source_row + 2}",
                    "sourceCollection": "Transcriptomic signatures",
                    "sourceFile": path.name,
                    "sourceSheet": sheet_name,
                    "sourceRow": int(source_row + 2),
                    "sourceSymbol": clean_scalar(row.get("Gene.symbol")),
                    "symbolMapping": method,
                    "sourceEntrezId": clean_scalar(row.get("Entrez.ID")),
                    "sourceEntrezIdNote": "Mouse-ortholog identifier as reported in the source workbook",
                    **meta,
                    "slope": slope,
                    "direction": "Positive" if slope and slope > 0 else "Negative" if slope and slope < 0 else "Zero",
                    "pValue": probability(row.get("P.Value")),
                    "adjustedPValue": probability(row.get("P.Adjusted")),
                    "supportMetric": support_metric,
                    "supportValue": clean_scalar(row.get(support_metric)),
                    "associationMetric": association_metric,
                    "associationValue": clean_scalar(row.get(association_metric)),
                }
            )

        sheet_report.append(
            {
                "sheet": sheet_name,
                "rowsTested": len(frame),
                "fdrSignificantRows": len(significant),
                "mappedSignificantRows": mapped_rows,
                **meta,
            }
        )

    return records, {
        "rowsTested": total_rows,
        "fdrSignificantRows": significant_rows,
        "geneCountWithMappedSignificantEvidence": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
        "sheets": sheet_report,
    }


def load_epigenetic(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    workbook = pd.ExcelFile(path)
    missing_sheets = sorted(set(EPIGENETIC_TABLES) - set(workbook.sheet_names))
    if missing_sheets:
        raise ValueError(f"Epigenetic workbook missing sheets: {missing_sheets}")

    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    table_report = []
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    rows_with_gene = 0
    mapped_assignments = 0

    for sheet_name, meta in EPIGENETIC_TABLES.items():
        frame = pd.read_excel(path, sheet_name=sheet_name, header=2)
        required = {"CpG", "Chrom", "Position", "Gene"}
        missing = required - set(frame.columns)
        if missing:
            raise ValueError(f"{sheet_name} missing columns: {sorted(missing)}")
        table_mapped = 0
        for source_row, row in frame.iterrows():
            raw_tokens = gene_tokens(row.get("Gene"))
            if raw_tokens:
                rows_with_gene += 1
            resolved_in_row: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
            for raw_symbol in raw_tokens:
                symbol, method = resolve_symbol(raw_symbol, approved, alias_map)
                mapping_counts[method] += 1
                if not symbol:
                    continue
                resolved_in_row[symbol].append((raw_symbol, method))
            for symbol, source_mappings in resolved_in_row.items():
                table_mapped += 1
                mapped_assignments += 1
                source_symbols = [item[0] for item in source_mappings]
                mapping_methods = sorted({item[1] for item in source_mappings})
                base = {
                    "recordId": f"epigenetic:{sheet_name}:{clean_scalar(row.get('CpG'))}:{symbol}",
                    "sourceCollection": "Epigenetic age and mortality",
                    "sourceFile": path.name,
                    "sourceSheet": sheet_name,
                    "sourceRow": int(source_row + 4),
                    "sourceSymbol": source_symbols[0],
                    "sourceSymbols": source_symbols,
                    "symbolMapping": mapping_methods[0] if len(mapping_methods) == 1 else "multiple",
                    "symbolMappings": [
                        {"sourceSymbol": raw, "method": mapping_method}
                        for raw, mapping_method in source_mappings
                    ],
                    "endpoint": meta["endpoint"],
                    "analysis": meta["analysis"],
                    "tableTitle": meta["title"],
                    "cpg": clean_scalar(row.get("CpG")),
                    "cpgChromosome": clean_scalar(row.get("Chrom")),
                    "cpgPosition": clean_scalar(row.get("Position")),
                    "coordinateNote": "Chromosome and position refer to the CpG locus, not the gene locus",
                }
                if sheet_name == "S1":
                    base.update(
                        {
                            "beta": clean_scalar(row.get("Beta")),
                            "standardError": clean_scalar(row.get("SE")),
                            "pValue": probability(row.get("p")),
                        }
                    )
                elif sheet_name == "S2":
                    base.update(
                        {
                            "linearBeta": clean_scalar(row.get("Beta CpG")),
                            "linearStandardError": clean_scalar(row.get("SE CpG")),
                            "linearPValue": probability(row.get("p CpG")),
                            "quadraticBeta": clean_scalar(row.get("Beta CpG^2")),
                            "quadraticStandardError": clean_scalar(row.get("SE CpG^2")),
                            "pValue": probability(row.get("p CpG^2")),
                        }
                    )
                else:
                    base.update(
                        {
                            "logHazardRatio": clean_scalar(row.get("logHR")),
                            "standardError": clean_scalar(row.get("SE")),
                            "zStatistic": clean_scalar(row.get("Z")),
                            "hazardRatio": clean_scalar(row.get("HR")),
                            "hazardRatioCiLow": clean_scalar(row.get("HR_CI95_Low")),
                            "hazardRatioCiHigh": clean_scalar(row.get("HR_CI95_High")),
                            "pValue": probability(row.get("p")),
                        }
                    )
                records[symbol].append(base)

        table_report.append(
            {
                "sheet": sheet_name,
                "rows": len(frame),
                "mappedGeneAssignments": table_mapped,
                **meta,
            }
        )

    return records, {
        "associationRows": sum(item["rows"] for item in table_report),
        "rowsWithGeneAnnotation": rows_with_gene,
        "mappedGeneAssignments": mapped_assignments,
        "geneCountWithMappedEvidence": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
        "tables": table_report,
    }


def load_genage(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"GenAge ID", "symbol", "name", "entrez gene id", "uniprot", "why"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"GenAge file missing columns: {sorted(missing)}")

    records: dict[str, dict[str, Any]] = {}
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    for source_row, row in frame.iterrows():
        symbol, method = resolve_symbol(row.get("symbol"), approved, alias_map)
        mapping_counts[method] += 1
        if not symbol:
            continue
        records[symbol] = {
            "recordId": f"genage:{clean_scalar(row.get('GenAge ID'))}",
            "sourceCollection": "GenAge human genes",
            "sourceFile": path.name,
            "sourceRow": int(source_row + 2),
            "sourceSymbol": clean_scalar(row.get("symbol")),
            "symbolMapping": method,
            "genAgeId": clean_scalar(row.get("GenAge ID")),
            "geneName": clean_scalar(row.get("name")),
            "humanEntrezId": clean_scalar(row.get("entrez gene id")),
            "uniprotEntry": clean_scalar(row.get("uniprot")),
            "selectionBasis": split_pipe(str(row.get("why", "")).replace(",", "|")),
            "selectionBasisRaw": clean_scalar(row.get("why")),
        }
    return records, {
        "rows": len(frame),
        "mappedGenes": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
    }


def load_longevity(
    path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    frame = pd.read_csv(path, encoding="utf-8-sig")
    required = {"id", "Association", "Population", "Variant(s)", "Gene(s)", "PubMed"}
    missing = required - set(frame.columns)
    if missing:
        raise ValueError(f"LongevityMap file missing columns: {sorted(missing)}")

    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mapping_counts: defaultdict[str, int] = defaultdict(int)
    association_counts: defaultdict[str, int] = defaultdict(int)
    for source_row, row in frame.iterrows():
        association_raw = clean_scalar(row.get("Association"))
        association = str(association_raw).lower() if association_raw else "unreported"
        if association == "non-significant":
            association_label = "Non-significant"
        elif association == "significant":
            association_label = "Significant"
        else:
            association_label = "Unreported"
        association_counts[association_label] += 1
        resolved_in_row: defaultdict[str, list[tuple[str, str]]] = defaultdict(list)
        for raw_symbol in gene_tokens(row.get("Gene(s)")):
            symbol, method = resolve_symbol(raw_symbol, approved, alias_map)
            mapping_counts[method] += 1
            if not symbol:
                continue
            resolved_in_row[symbol].append((raw_symbol, method))
        for symbol, source_mappings in resolved_in_row.items():
            source_symbols = [item[0] for item in source_mappings]
            mapping_methods = sorted({item[1] for item in source_mappings})
            pubmed = clean_scalar(row.get("PubMed"))
            records[symbol].append(
                {
                    "recordId": f"longevity:{clean_scalar(row.get('id'))}:{symbol}",
                    "sourceCollection": "LongevityMap",
                    "sourceFile": path.name,
                    "sourceRow": int(source_row + 2),
                    "sourceSymbol": source_symbols[0],
                    "sourceSymbols": source_symbols,
                    "symbolMapping": mapping_methods[0] if len(mapping_methods) == 1 else "multiple",
                    "symbolMappings": [
                        {"sourceSymbol": raw, "method": mapping_method}
                        for raw, mapping_method in source_mappings
                    ],
                    "longevityMapId": clean_scalar(row.get("id")),
                    "association": association_label,
                    "population": clean_scalar(row.get("Population")),
                    "variants": clean_scalar(row.get("Variant(s)")),
                    "pubmedId": pubmed,
                    "pubmedUrl": f"https://pubmed.ncbi.nlm.nih.gov/{pubmed}/" if pubmed else None,
                }
            )
    return records, {
        "rows": len(frame),
        "associationCounts": dict(sorted(association_counts.items())),
        "mappedGenes": len(records),
        "mappingCounts": dict(sorted(mapping_counts.items())),
    }


def p_sort_value(prob: dict[str, Any] | None) -> float:
    if not prob or prob.get("value") is None:
        return 1.0
    value = float(prob["value"])
    return 1e-320 if value == 0 else value


def build_gene_record(
    symbol: str,
    hgnc: dict[str, Any],
    transcript: list[dict[str, Any]],
    epigenetic: list[dict[str, Any]],
    longevity: list[dict[str, Any]],
    genage: dict[str, Any] | None,
) -> dict[str, Any]:
    transcript_tables = sorted({record["sourceSheet"] for record in transcript})
    epigenetic_tables = sorted({record["sourceSheet"] for record in epigenetic})
    longevity_pubmed = sorted(
        {str(record["pubmedId"]) for record in longevity if record.get("pubmedId")}
    )
    significant_longevity = [record for record in longevity if record["association"] == "Significant"]
    non_significant_longevity = [
        record for record in longevity if record["association"] == "Non-significant"
    ]
    human_transcript = [record for record in transcript if record["family"] == "Human"]
    source_flags = {
        "transcriptomic": bool(transcript),
        "epigenetic": bool(epigenetic),
        "longevity": bool(longevity),
        "genAge": genage is not None,
    }
    human_flags = {
        "humanTranscriptomic": bool(human_transcript),
        "humanEpigenetic": bool(epigenetic),
        "humanLongevityAssociation": bool(longevity),
        "humanCuratedGenAge": genage is not None,
    }
    best_fdr_record = min(transcript, key=lambda item: p_sort_value(item["adjustedPValue"])) if transcript else None
    best_epigenetic_record = min(epigenetic, key=lambda item: p_sort_value(item["pValue"])) if epigenetic else None
    positive = sum(1 for record in transcript if record["direction"] == "Positive")
    negative = sum(1 for record in transcript if record["direction"] == "Negative")
    analysis_units = len(transcript_tables) + len(epigenetic_tables) + len(longevity_pubmed) + int(genage is not None)
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
        "humanEvidenceFlags": human_flags,
        "evidenceProfile": {
            "sourceBreadth": sum(source_flags.values()),
            "sourceCollectionsAvailable": [key for key, present in source_flags.items() if present],
            "analysisUnits": analysis_units,
            "transcriptomicTables": len(transcript_tables),
            "epigeneticTables": len(epigenetic_tables),
            "longevityPublications": len(longevity_pubmed),
            "humanEvidenceTypes": sum(human_flags.values()),
            "curatedInGenAge": genage is not None,
        },
        "statistics": {
            "transcriptomicRecords": len(transcript),
            "transcriptomicPositive": positive,
            "transcriptomicNegative": negative,
            "bestTranscriptomicAdjustedP": best_fdr_record["adjustedPValue"] if best_fdr_record else None,
            "bestTranscriptomicSource": best_fdr_record["sourceSheet"] if best_fdr_record else None,
            "epigeneticRecords": len(epigenetic),
            "epigeneticCpGs": len({record["cpg"] for record in epigenetic}),
            "bestEpigeneticP": best_epigenetic_record["pValue"] if best_epigenetic_record else None,
            "bestEpigeneticSource": best_epigenetic_record["sourceSheet"] if best_epigenetic_record else None,
            "longevityRecords": len(longevity),
            "longevitySignificant": len(significant_longevity),
            "longevityNonSignificant": len(non_significant_longevity),
        },
        "transcriptomicRecords": sorted(
            transcript,
            key=lambda item: (p_sort_value(item["adjustedPValue"]), item["sourceSheet"]),
        ),
        "epigeneticRecords": sorted(
            epigenetic,
            key=lambda item: (p_sort_value(item["pValue"]), item["sourceSheet"], item["cpg"] or ""),
        ),
        "longevityRecords": sorted(
            longevity,
            key=lambda item: (item["association"] != "Significant", str(item.get("pubmedId") or "")),
        ),
        "genAgeRecord": genage,
    }


def selection_key(gene: dict[str, Any]) -> tuple[Any, ...]:
    profile = gene["evidenceProfile"]
    stats = gene["statistics"]
    best_fdr = p_sort_value(stats.get("bestTranscriptomicAdjustedP"))
    best_epi = p_sort_value(stats.get("bestEpigeneticP"))
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
        best_fdr,
        best_epi,
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


def main() -> None:
    args = parse_args()
    source_paths = [
        args.transcriptomic,
        args.epigenetic,
        args.genage,
        args.longevity,
        args.hgnc,
    ]
    missing = [str(path) for path in source_paths if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required source files: {missing}")
    if args.gene_limit <= 0 or args.chunk_size <= 0:
        raise ValueError("gene-limit and chunk-size must be positive")

    build_time = datetime.now(UTC).isoformat(timespec="seconds")
    approved, alias_map, hgnc_report = load_hgnc(args.hgnc)
    transcript, transcript_report = load_transcriptomic(args.transcriptomic, approved, alias_map)
    epigenetic, epigenetic_report = load_epigenetic(args.epigenetic, approved, alias_map)
    genage, genage_report = load_genage(args.genage, approved, alias_map)
    longevity, longevity_report = load_longevity(args.longevity, approved, alias_map)

    all_symbols = sorted(set(transcript) | set(epigenetic) | set(genage) | set(longevity))
    all_genes = [
        build_gene_record(
            symbol,
            approved[symbol.upper()],
            transcript.get(symbol, []),
            epigenetic.get(symbol, []),
            longevity.get(symbol, []),
            genage.get(symbol),
        )
        for symbol in all_symbols
        if symbol.upper() in approved
    ]
    all_genes.sort(key=selection_key)
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
            "Hierarchical evidence ordering: source breadth, human evidence types, GenAge curation, "
            "significant LongevityMap reports, analysis units, record count, then statistical support. "
            "This rank is not a biological importance or causal-effect score."
        )

    search_index = []
    for index, gene in enumerate(selected):
        chunk = index // args.chunk_size
        search_index.append(
            {
                "symbol": gene["symbol"],
                "name": gene["annotation"].get("approvedName"),
                "location": gene["annotation"].get("chromosomeLocation"),
                "rank": gene["rank"],
                "chunk": chunk,
                "sourceBreadth": gene["evidenceProfile"]["sourceBreadth"],
                "analysisUnits": gene["evidenceProfile"]["analysisUnits"],
                "transcriptomicRecords": gene["statistics"]["transcriptomicRecords"],
                "epigeneticRecords": gene["statistics"]["epigeneticRecords"],
                "longevitySignificant": gene["statistics"]["longevitySignificant"],
                "curatedInGenAge": gene["evidenceProfile"]["curatedInGenAge"],
                "sources": gene["evidenceProfile"]["sourceCollectionsAvailable"],
            }
        )

    chunk_count = math.ceil(len(selected) / args.chunk_size)
    for chunk in range(chunk_count):
        start = chunk * args.chunk_size
        payload = {gene["symbol"]: gene for gene in selected[start : start + args.chunk_size]}
        write_json(output / f"genes-{chunk}.json", payload, compact=True)

    source_records = [
        source_file_record(args.transcriptomic, "transcriptomic workbook"),
        source_file_record(args.epigenetic, "epigenetic workbook"),
        source_file_record(args.genage, "curated gene CSV"),
        source_file_record(args.longevity, "longevity association CSV"),
        source_file_record(args.hgnc, "HGNC annotation reference"),
    ]
    datasets = [
        {
            "id": "transcriptomic",
            "name": "Universal transcriptomic hallmarks of mammalian ageing and mortality",
            "shortName": "Transcriptomic signatures",
            "sourceFile": args.transcriptomic.name,
            "publicationUrl": TRANSCRIPTOMIC_DOI,
            "scope": "18 gene-level analyses spanning ITP, rodent, mouse, rat, macaque, and human data",
            "inclusionRule": "Benjamini-Hochberg adjusted P <= 0.05 in the source sheet",
            "report": transcript_report,
        },
        {
            "id": "epigenetic",
            "name": "Refining epigenetic prediction of chronological and biological age",
            "shortName": "Epigenetic age and mortality",
            "sourceFile": args.epigenetic.name,
            "publicationUrl": EPIGENETIC_DOI,
            "scope": "Gene-annotated CpGs from four epigenome-wide significant age and mortality tables",
            "inclusionRule": "All records in source Tables S1-S4; source tables report P < 3.6 x 10^-8",
            "report": epigenetic_report,
        },
        {
            "id": "genage",
            "name": "GenAge human genes",
            "shortName": "GenAge",
            "sourceFile": args.genage.name,
            "publicationUrl": GENAGE_URL,
            "scope": "Manually curated candidate human ageing-associated genes",
            "inclusionRule": "All rows in the supplied GenAge human-gene file",
            "report": genage_report,
        },
        {
            "id": "longevity",
            "name": "LongevityMap genetic association studies of longevity",
            "shortName": "LongevityMap",
            "sourceFile": args.longevity.name,
            "publicationUrl": LONGEVITY_URL,
            "scope": "Human longevity association reports, including significant and non-significant findings",
            "inclusionRule": "All rows in the supplied LongevityMap Build 3 file",
            "report": longevity_report,
        },
        {
            "id": "hgnc",
            "name": "HGNC complete approved gene set",
            "shortName": "HGNC",
            "sourceFile": args.hgnc.name,
            "publicationUrl": HGNC_URL,
            "scope": "Approved human gene symbols, names, identifiers, and cytogenetic locations",
            "inclusionRule": "Approved HGNC records; ambiguous aliases excluded",
            "report": hgnc_report,
        },
        {
            "id": "ncbi",
            "name": "NCBI Gene summaries",
            "shortName": "NCBI Gene",
            "sourceFile": args.ncbi_cache.name,
            "publicationUrl": NCBI_GENE_URL,
            "scope": "Human gene summaries matched by HGNC Entrez Gene ID and approved symbol",
            "inclusionRule": "Summary attached only when NCBI symbol matches the selected HGNC symbol",
            "report": ncbi_report,
        },
    ]

    breadth_counts = defaultdict(int)
    for gene in selected:
        breadth_counts[str(gene["evidenceProfile"]["sourceBreadth"])] += 1
    featured = [gene["symbol"] for gene in selected if gene["evidenceProfile"]["sourceBreadth"] == 4][:16]
    if len(featured) < 12:
        featured = [gene["symbol"] for gene in selected[:16]]

    manifest = {
        "atlasName": "Aging Evidence Atlas",
        "version": "0.1.0",
        "generatedAt": build_time,
        "geneCount": len(selected),
        "candidateGeneCount": len(all_genes),
        "chunkSize": args.chunk_size,
        "chunkCount": chunk_count,
        "featuredGenes": featured,
        "evidenceCollections": 4,
        "breadthCounts": dict(sorted(breadth_counts.items())),
        "transcriptomicSignificantRecords": transcript_report["fdrSignificantRows"],
        "epigeneticGeneAssignments": epigenetic_report["mappedGeneAssignments"],
        "genAgeGenes": genage_report["mappedGenes"],
        "longevityRows": longevity_report["rows"],
        "methodStatement": (
            "The atlas reports evidence components separately. The rank is a deterministic browsing aid, "
            "not a causal, clinical, or biological-importance score."
        ),
    }
    build_report = {
        "generatedAt": build_time,
        "parameters": {"geneLimit": args.gene_limit, "chunkSize": args.chunk_size},
        "sourceFiles": source_records,
        "hgnc": hgnc_report,
        "transcriptomic": transcript_report,
        "epigenetic": epigenetic_report,
        "genAge": genage_report,
        "longevity": longevity_report,
        "ncbi": ncbi_report,
        "selectedGeneCount": len(selected),
        "featuredGenes": featured,
        "selectedSymbols": [gene["symbol"] for gene in selected],
    }

    write_json(output / "manifest.json", manifest)
    write_json(output / "search-index.json", search_index, compact=True)
    write_json(output / "datasets.json", datasets)
    write_json(output / "build-report.json", build_report)
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
