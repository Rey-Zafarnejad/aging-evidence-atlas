#!/usr/bin/env python3
"""Build the source-centric Human Aging Atlas static data package.

The consolidated workbook defines the eligible gene universe. Public source
files provide the evidence shown on gene pages. Human gene symbols are the
display anchor, with transcriptomic mouse identifiers mapped through strict
one-to-one MGI/Alliance human-mouse homology classes.
"""

from __future__ import annotations

import argparse
import json
import math
import re
import urllib.parse
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd

from build_atlas_data import (
    attach_ncbi_annotation,
    fetch_ncbi_summaries,
    load_hgnc,
    p_sort_value,
    resolve_symbol,
    sha256,
    split_pipe,
    write_json,
)


DEFAULT_DATA_ROOT = Path(
    "/Users/ReyZafarnejad/Documents/Harvard University/Internship/FAST PROSPR/Data"
)
DEFAULT_ATLAS = DEFAULT_DATA_ROOT / "Human Aging and Longevity Atlas Datasets.xlsx"
DEFAULT_TRANSCRIPTOMIC = DEFAULT_DATA_ROOT / "41586_2026_10542_MOESM4_ESM.xlsx"
DEFAULT_EPIGENETIC = DEFAULT_DATA_ROOT / "13073_2023_1161_MOESM4_ESM.xlsx"
DEFAULT_GENAGE_HUMAN = DEFAULT_DATA_ROOT / "human_genes/genage_human.csv"
DEFAULT_LONGEVITY = DEFAULT_DATA_ROOT / "longevity_genes/longevity.csv"
DEFAULT_BUILD = Path(__file__).resolve().parent
DEFAULT_HGNC = DEFAULT_BUILD / "cache/hgnc_complete_set.txt"
DEFAULT_NCBI = DEFAULT_BUILD / "cache/ncbi_gene_summaries.json"
DEFAULT_ORTHOLOGY = DEFAULT_BUILD / "cache/HOM_MouseHumanSequence.rpt"
DEFAULT_GENAGE_MODELS = DEFAULT_BUILD / "cache/genage_models/genage_models.csv"
DEFAULT_OUTPUT = DEFAULT_BUILD.parent / "data"

TRANSCRIPTOMIC_DOI = "https://doi.org/10.1038/s41586-026-10542-3"
EPIGENETIC_DOI = "https://doi.org/10.1186/s13073-023-01161-y"
GENAGE_URL = "https://genomics.senescence.info/genes/"
LONGEVITY_URL = "https://genomics.senescence.info/longevity/"
ORTHOLOGY_URL = "https://www.informatics.jax.org/downloads/reports/HOM_MouseHumanSequence.rpt"

SOURCE_KEYS = (
    "transcriptomic",
    "epigenetic",
    "longevityMap",
    "genAge",
)

TRANSCRIPTOMIC_SHEETS = {
    "(A) ITP Chronological age": ("Mouse", "ITP", "Chronological age", "Unadjusted"),
    "(B) ITP Normalized age": ("Mouse", "ITP", "Normalized age", "Unadjusted"),
    "(C) ITP Normalized age, adj.": ("Mouse", "ITP", "Normalized age", "Adjusted"),
    "(D) ITP Mortality rate": ("Mouse", "ITP", "Mortality rate", "Unadjusted"),
    "(E) ITP Mortality rate, adj.": ("Mouse", "ITP", "Mortality rate", "Adjusted"),
    "(F) ITP Max lifespan": ("Mouse", "ITP", "Maximum lifespan", "Unadjusted"),
    "(G) ITP Max lifespan, adj.": ("Mouse", "ITP", "Maximum lifespan", "Adjusted"),
    "(H) Rodents Chronological age": ("Rodents", "Cross-species rodent meta-analysis", "Chronological age", "Unadjusted"),
    "(I) Rodents Normalized age": ("Rodents", "Cross-species rodent meta-analysis", "Normalized age", "Unadjusted"),
    "(J) Rodents Normalized age, adj": ("Rodents", "Cross-species rodent meta-analysis", "Normalized age", "Adjusted"),
    "(K) Rodents Mortality rate": ("Rodents", "Cross-species rodent meta-analysis", "Mortality rate", "Unadjusted"),
    "(L) Rodents Mortality rate, adj": ("Rodents", "Cross-species rodent meta-analysis", "Mortality rate", "Adjusted"),
    "(M) Rodents Max lifespan": ("Rodents", "Cross-species rodent meta-analysis", "Maximum lifespan", "Unadjusted"),
    "(N) Rodents Max lifespan, adj": ("Rodents", "Cross-species rodent meta-analysis", "Maximum lifespan", "Adjusted"),
    "(O) Mouse aging multi-tissue": ("Mouse", "Multi-tissue", "Chronological age", "Unadjusted"),
    "(P) Rat aging multi-tissue": ("Rat", "Multi-tissue", "Chronological age", "Unadjusted"),
    "(Q) Macaque aging multi-tissue": ("Macaque", "Multi-tissue", "Chronological age", "Unadjusted"),
    "(R) Human aging multi-tissue": ("Human", "Multi-tissue", "Chronological age", "Unadjusted"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--atlas-workbook", type=Path, default=DEFAULT_ATLAS)
    parser.add_argument("--transcriptomic", type=Path, default=DEFAULT_TRANSCRIPTOMIC)
    parser.add_argument("--epigenetic", type=Path, default=DEFAULT_EPIGENETIC)
    parser.add_argument("--genage-human", type=Path, default=DEFAULT_GENAGE_HUMAN)
    parser.add_argument("--longevity", type=Path, default=DEFAULT_LONGEVITY)
    parser.add_argument("--genage-models", type=Path, default=DEFAULT_GENAGE_MODELS)
    parser.add_argument("--orthology", type=Path, default=DEFAULT_ORTHOLOGY)
    parser.add_argument("--hgnc", type=Path, default=DEFAULT_HGNC)
    parser.add_argument("--ncbi-cache", type=Path, default=DEFAULT_NCBI)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--gene-limit", type=int, default=1000)
    parser.add_argument("--chunk-size", type=int, default=20)
    parser.add_argument("--fetch-ncbi", action="store_true")
    return parser.parse_args()


def clean(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item") and not isinstance(value, str):
        try:
            value = value.item()
        except (ValueError, AttributeError):
            pass
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
        return int(value) if value.is_integer() else float(value)
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    return value


def number(value: Any) -> float | None:
    value = clean(value)
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
    raw = clean(value)
    parsed = number(raw)
    qualifier = "exact"
    if isinstance(raw, str) and raw.startswith("<"):
        qualifier = "upper_bound"
    elif parsed == 0:
        qualifier = "reported_zero"
    return {
        "value": parsed,
        "display": str(raw) if raw is not None else None,
        "qualifier": qualifier,
    }


def gene_tokens(value: Any) -> list[str]:
    value = clean(value)
    if not isinstance(value, str):
        return []
    tokens: list[str] = []
    for token in re.split(r"[;,]", value):
        token = token.strip().strip("\"'")
        if token and token not in tokens:
            tokens.append(token)
    return tokens


def source_file(path: Path, kind: str) -> dict[str, Any]:
    return {
        "name": path.name,
        "kind": kind,
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def load_one_to_one_orthology(path: Path) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]], dict[str, Any]]:
    frame = pd.read_csv(path, sep="\t", dtype=str)
    by_mouse_entrez: dict[str, dict[str, Any]] = {}
    by_human_symbol: dict[str, dict[str, Any]] = {}
    excluded_classes = 0
    candidate_pairs: list[dict[str, Any]] = []

    for class_key, group in frame.groupby("DB Class Key", sort=False):
        human = group[group["NCBI Taxon ID"].eq("9606")]
        mouse = group[group["NCBI Taxon ID"].eq("10090")]
        if len(human) != 1 or len(mouse) != 1:
            excluded_classes += 1
            continue
        h = human.iloc[0]
        m = mouse.iloc[0]
        human_symbol = clean(h.get("Symbol"))
        mouse_entrez = clean(m.get("EntrezGene ID"))
        if not human_symbol or not mouse_entrez:
            continue
        record = {
            "homologyClassId": str(class_key),
            "humanSymbol": human_symbol,
            "humanEntrezId": clean(h.get("EntrezGene ID")),
            "humanHgncId": clean(h.get("HGNC ID")),
            "humanLocation": clean(h.get("Genetic Location")),
            "humanCoordinatesGrch38": clean(h.get("Genome Coordinates (mouse: GRCm39 human: GRCh38)")),
            "mouseSymbol": clean(m.get("Symbol")),
            "mouseEntrezId": mouse_entrez,
            "mouseMgiId": clean(m.get("Mouse MGI ID")),
            "mouseLocation": clean(m.get("Genetic Location")),
            "mouseCoordinatesGrcm39": clean(m.get("Genome Coordinates (mouse: GRCm39 human: GRCh38)")),
            "mappingType": "one-to-one",
            "source": "MGI/Alliance homology report",
            "sourceUrl": ORTHOLOGY_URL,
        }
        candidate_pairs.append(record)

    human_symbol_counts = Counter(record["humanSymbol"].upper() for record in candidate_pairs)
    mouse_entrez_counts = Counter(str(record["mouseEntrezId"]) for record in candidate_pairs)
    globally_unique_pairs = [
        record
        for record in candidate_pairs
        if human_symbol_counts[record["humanSymbol"].upper()] == 1
        and mouse_entrez_counts[str(record["mouseEntrezId"])] == 1
    ]
    for record in globally_unique_pairs:
        by_mouse_entrez[str(record["mouseEntrezId"])] = record
        by_human_symbol[record["humanSymbol"].upper()] = record

    return by_mouse_entrez, by_human_symbol, {
        "reportRows": len(frame),
        "oneToOnePairs": len(by_mouse_entrez),
        "nonOneToOneClassesExcluded": excluded_classes,
        "classLevelPairsExcludedAsGloballyAmbiguous": len(candidate_pairs) - len(globally_unique_pairs),
    }


def load_eligibility(
    atlas_path: Path,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
    mouse_to_human: dict[str, dict[str, Any]],
) -> tuple[set[str], set[str], set[str], dict[str, Any]]:
    tage = pd.read_excel(atlas_path, sheet_name="tAge")
    genage = pd.read_excel(atlas_path, sheet_name="GenAge")
    longevity = pd.read_excel(atlas_path, sheet_name="LongevityMap")

    tage_retained = pd.to_numeric(tage["Include"], errors="coerce").eq(1)
    genage_retained = pd.to_numeric(genage["Include"], errors="coerce").eq(1)
    longevity_retained = pd.to_numeric(longevity["Include"], errors="coerce").eq(1)

    tage_symbols: set[str] = set()
    unmapped_tage = 0
    for _, row in tage[tage_retained].iterrows():
        mouse_entrez = clean(row.get("Entrez.ID"))
        ortholog = mouse_to_human.get(str(mouse_entrez)) if mouse_entrez is not None else None
        if ortholog and ortholog["humanSymbol"].upper() in approved:
            tage_symbols.add(approved[ortholog["humanSymbol"].upper()]["symbol"])
        else:
            unmapped_tage += 1

    genage_symbols: set[str] = set()
    for value in genage.loc[genage_retained, "Gene"]:
        symbol, _ = resolve_symbol(value, approved, alias_map)
        if symbol:
            genage_symbols.add(symbol)

    longevity_symbols: set[str] = set()
    for value in longevity.loc[longevity_retained, "Gene"]:
        symbol, _ = resolve_symbol(value, approved, alias_map)
        if symbol:
            longevity_symbols.add(symbol)

    eligible = tage_symbols | genage_symbols | longevity_symbols
    return eligible, genage_symbols, longevity_symbols, {
        "eligibleGenes": len(eligible),
        "transcriptomicRetainedRows": int(tage_retained.sum()),
        "transcriptomicMappedGenes": len(tage_symbols),
        "transcriptomicRowsWithoutOneToOneHumanOrtholog": unmapped_tage,
        "genAgeRetainedRows": int(genage_retained.sum()),
        "genAgeMappedGenes": len(genage_symbols),
        "longevityMapRetainedRows": int(longevity_retained.sum()),
        "longevityMapMappedGenes": len(longevity_symbols),
        "mandatoryCuratedCoreGenes": len(genage_symbols | longevity_symbols),
    }


def load_transcriptomic_evidence(
    path: Path,
    eligible: set[str],
    mouse_to_human: dict[str, dict[str, Any]],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    workbook = pd.ExcelFile(path)
    missing = set(TRANSCRIPTOMIC_SHEETS) - set(workbook.sheet_names)
    if missing:
        raise ValueError(f"Transcriptomic workbook missing sheets: {sorted(missing)}")

    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    sheet_report: dict[str, Any] = {}
    for sheet, (organism, cohort, endpoint, adjustment) in TRANSCRIPTOMIC_SHEETS.items():
        frame = pd.read_excel(path, sheet_name=sheet)
        adjusted_p = pd.to_numeric(frame["P.Adjusted"], errors="coerce")
        significant = adjusted_p.le(0.05)
        mapped = 0
        retained = 0
        for source_index, row in frame[significant].iterrows():
            mouse_entrez = clean(row.get("Entrez.ID"))
            ortholog = mouse_to_human.get(str(mouse_entrez)) if mouse_entrez is not None else None
            if not ortholog:
                continue
            mapped += 1
            human_symbol = ortholog["humanSymbol"]
            if human_symbol not in eligible:
                continue
            retained += 1
            slope = number(row.get("Slope"))
            record = {
                "recordId": f"transcriptomic:{sheet[1]}:{source_index + 2}",
                "sourceKey": "transcriptomic",
                "sourceSheet": sheet,
                "sourceRow": int(source_index + 2),
                "organism": organism,
                "cohort": cohort,
                "endpoint": endpoint,
                "model": adjustment,
                "sourceMouseSymbol": clean(row.get("Gene.symbol")),
                "sourceMouseEntrezId": mouse_entrez,
                "humanSymbol": human_symbol,
                "orthologyClassId": ortholog["homologyClassId"],
                "slope": slope,
                "direction": "Positive" if slope and slope > 0 else "Negative" if slope and slope < 0 else "Zero",
                "standardError": clean(row.get("SE")),
                "logCpm": clean(row.get("logCPM")),
                "likelihoodRatio": clean(row.get("LR")),
                "pearsonCorrelation": clean(row.get("Pearson.corr")),
                "pValue": probability(row.get("P.Value")),
                "adjustedPValue": probability(row.get("P.Adjusted")),
            }
            records[human_symbol].append(record)
        sheet_report[sheet] = {
            "rows": len(frame),
            "significantRows": int(significant.sum()),
            "significantRowsWithOneToOneOrtholog": mapped,
            "recordsForEligibleGenes": retained,
        }

    for symbol in records:
        records[symbol].sort(
            key=lambda item: (p_sort_value(item["adjustedPValue"]), item["sourceSheet"], item["sourceRow"])
        )
    return records, {
        "sheets": sheet_report,
        "genesWithEvidence": len(records),
        "recordsForEligibleGenes": sum(len(items) for items in records.values()),
        "displayRule": "Adjusted P value at or below 0.05; eligibility remains defined by the curation layer",
    }


def resolve_gene_annotations(
    value: Any,
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> dict[str, list[dict[str, str]]]:
    resolved: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for source_symbol in gene_tokens(value):
        symbol, method = resolve_symbol(source_symbol, approved, alias_map)
        if symbol:
            resolved[symbol].append({"sourceSymbol": source_symbol, "mapping": method})
    return dict(resolved)


def load_epigenetic_evidence(
    path: Path,
    eligible: set[str],
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[
    defaultdict[str, list[dict[str, Any]]],
    defaultdict[str, list[dict[str, Any]]],
    dict[str, Any],
]:
    age_frame = pd.read_excel(path, sheet_name="S1", header=2)
    mortality_frame = pd.read_excel(path, sheet_name="S3", header=2)
    sensitivity_frame = pd.read_excel(path, sheet_name="S4", header=2)

    sensitivity_by_cpg: dict[str, tuple[int, dict[str, Any]]] = {}
    for source_index, row in sensitivity_frame.iterrows():
        cpg = clean(row.get("CpG"))
        if cpg:
            sensitivity_by_cpg[str(cpg)] = (int(source_index + 4), row.to_dict())

    age_records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    age_unannotated = 0
    for source_index, row in age_frame.iterrows():
        resolved = resolve_gene_annotations(row.get("Gene"), approved, alias_map)
        if not resolved:
            age_unannotated += 1
        for symbol, mappings in resolved.items():
            if symbol not in eligible:
                continue
            age_records[symbol].append(
                {
                    "recordId": f"epigenetic:age:{source_index + 4}:{clean(row.get('CpG'))}:{symbol}",
                    "sourceKey": "epigenetic",
                    "sourceSheet": "S1",
                    "sourceRow": int(source_index + 4),
                    "organism": "Human",
                    "endpoint": "Chronological age",
                    "model": "Primary EWAS",
                    "cpg": clean(row.get("CpG")),
                    "cpgChromosome": clean(row.get("Chrom")),
                    "cpgPosition": clean(row.get("Position")),
                    "geneAnnotations": mappings,
                    "beta": clean(row.get("Beta")),
                    "standardError": clean(row.get("SE")),
                    "pValue": probability(row.get("p")),
                }
            )

    mortality_records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mortality_unannotated = 0
    paired_sensitivity = 0
    for source_index, row in mortality_frame.iterrows():
        resolved = resolve_gene_annotations(row.get("Gene"), approved, alias_map)
        if not resolved:
            mortality_unannotated += 1
        cpg = clean(row.get("CpG"))
        sensitivity_item = sensitivity_by_cpg.get(str(cpg)) if cpg else None
        if sensitivity_item:
            paired_sensitivity += 1
        for symbol, mappings in resolved.items():
            if symbol not in eligible:
                continue
            sensitivity = None
            if sensitivity_item:
                sensitivity_row_number, sensitivity_row = sensitivity_item
                sensitivity = {
                    "sourceSheet": "S4",
                    "sourceRow": sensitivity_row_number,
                    "model": "Relatedness-adjusted sensitivity model",
                    "logHazardRatio": clean(sensitivity_row.get("logHR")),
                    "standardError": clean(sensitivity_row.get("SE")),
                    "zStatistic": clean(sensitivity_row.get("Z")),
                    "hazardRatio": clean(sensitivity_row.get("HR")),
                    "hazardRatioCiLow": clean(sensitivity_row.get("HR_CI95_Low")),
                    "hazardRatioCiHigh": clean(sensitivity_row.get("HR_CI95_High")),
                    "pValue": probability(sensitivity_row.get("p")),
                }
            mortality_records[symbol].append(
                {
                    "recordId": f"epigenetic:mortality:{source_index + 4}:{cpg}:{symbol}",
                    "sourceKey": "epigenetic",
                    "sourceSheet": "S3",
                    "sourceRow": int(source_index + 4),
                    "organism": "Human",
                    "endpoint": "All-cause mortality",
                    "model": "Primary EWAS",
                    "cpg": cpg,
                    "cpgChromosome": clean(row.get("Chrom")),
                    "cpgPosition": clean(row.get("Position")),
                    "geneAnnotations": mappings,
                    "logHazardRatio": clean(row.get("logHR")),
                    "standardError": clean(row.get("SE")),
                    "zStatistic": clean(row.get("Z")),
                    "hazardRatio": clean(row.get("HR")),
                    "hazardRatioCiLow": clean(row.get("HR_CI95_Low")),
                    "hazardRatioCiHigh": clean(row.get("HR_CI95_High")),
                    "pValue": probability(row.get("p")),
                    "sensitivityAnalysis": sensitivity,
                }
            )

    for collection in (age_records, mortality_records):
        for symbol in collection:
            collection[symbol].sort(key=lambda item: (p_sort_value(item["pValue"]), item["cpg"] or ""))

    return age_records, mortality_records, {
        "agePrimaryRows": len(age_frame),
        "ageRowsWithoutApprovedGeneAnnotation": age_unannotated,
        "ageGenesWithEvidence": len(age_records),
        "mortalityPrimaryRows": len(mortality_frame),
        "mortalitySensitivityRows": len(sensitivity_frame),
        "mortalityCpGsPairedToSensitivityModel": paired_sensitivity,
        "mortalityRowsWithoutApprovedGeneAnnotation": mortality_unannotated,
        "mortalityGenesWithEvidence": len(mortality_records),
        "scope": "Primary chronological-age CpGs and primary mortality CpGs; the relatedness-adjusted mortality model is attached as sensitivity evidence",
    }


def load_genage_human_evidence(
    raw_path: Path,
    mandatory_symbols: set[str],
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[dict[str, dict[str, Any]], dict[str, Any]]:
    frame = pd.read_csv(raw_path)
    records: dict[str, dict[str, Any]] = {}
    for source_index, row in frame.iterrows():
        symbol, method = resolve_symbol(row.get("symbol"), approved, alias_map)
        if not symbol or symbol not in mandatory_symbols:
            continue
        records[symbol] = {
            "recordId": f"genage:human:{source_index + 2}",
            "sourceKey": "genAge",
            "sourceFile": raw_path.name,
            "sourceRow": int(source_index + 2),
            "organism": "Human",
            "genAgeId": clean(row.get("GenAge ID")),
            "sourceSymbol": clean(row.get("symbol")),
            "symbolMapping": method,
            "geneName": clean(row.get("name")),
            "entrezGeneId": clean(row.get("entrez gene id")),
            "uniprotEntry": clean(row.get("uniprot")),
            "evidenceBasis": [item.strip() for item in str(row.get("why", "")).split(",") if item.strip()],
        }
    return records, {
        "sourceRows": len(frame),
        "retainedHumanGenesWithPublicRecords": len(records),
    }


def load_genage_mouse_evidence(
    path: Path,
    eligible: set[str],
    mouse_to_human: dict[str, dict[str, Any]],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    frame = pd.read_csv(path)
    mouse = frame[frame["organism"].eq("Mus musculus")]
    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    unmapped = 0
    for source_index, row in mouse.iterrows():
        mouse_entrez = clean(row.get("entrez gene id"))
        ortholog = mouse_to_human.get(str(mouse_entrez)) if mouse_entrez is not None else None
        if not ortholog:
            unmapped += 1
            continue
        human_symbol = ortholog["humanSymbol"]
        if human_symbol not in eligible:
            continue
        records[human_symbol].append(
            {
                "recordId": f"genage:mouse:{source_index + 2}",
                "sourceKey": "genAge",
                "sourceFile": path.name,
                "sourceRow": int(source_index + 2),
                "organism": "Mouse",
                "genAgeId": clean(row.get("GenAge ID")),
                "mouseSymbol": clean(row.get("symbol")),
                "mouseEntrezGeneId": mouse_entrez,
                "geneName": clean(row.get("name")),
                "averageLifespanChange": clean(row.get("avg lifespan change (max obsv)")),
                "lifespanEffect": clean(row.get("lifespan effect")),
                "longevityInfluence": clean(row.get("longevity influence")),
                "orthologyClassId": ortholog["homologyClassId"],
            }
        )
    for symbol in records:
        records[symbol].sort(key=lambda item: (str(item.get("mouseSymbol") or ""), item["sourceRow"]))
    return records, {
        "modelOrganismRows": len(frame),
        "mouseRows": len(mouse),
        "mouseRowsWithoutOneToOneHumanOrtholog": unmapped,
        "eligibleHumanGenesWithMouseEvidence": len(records),
        "mouseRecordsForEligibleGenes": sum(len(items) for items in records.values()),
    }


def load_longevity_evidence(
    raw_path: Path,
    atlas_path: Path,
    mandatory_symbols: set[str],
    approved: dict[str, dict[str, Any]],
    alias_map: dict[str, str],
) -> tuple[defaultdict[str, list[dict[str, Any]]], dict[str, Any]]:
    raw = pd.read_csv(raw_path)
    curated = pd.read_excel(atlas_path, sheet_name="LongevityMap")
    if len(raw) != len(curated):
        raise ValueError("LongevityMap raw and curation rows do not align")
    retained = pd.to_numeric(curated["Include"], errors="coerce").eq(1)
    records: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    mismatched_rows = 0
    for source_index in raw.index[retained]:
        raw_row = raw.loc[source_index]
        curated_row = curated.loc[source_index]
        raw_gene = clean(raw_row.get("Gene(s)"))
        curated_gene = clean(curated_row.get("Gene"))
        if str(raw_gene) != str(curated_gene):
            mismatched_rows += 1
            continue
        symbol, method = resolve_symbol(raw_gene, approved, alias_map)
        if not symbol or symbol not in mandatory_symbols:
            continue
        pubmed = clean(raw_row.get("PubMed"))
        records[symbol].append(
            {
                "recordId": f"longevity:{clean(raw_row.get('id')) or source_index + 1}",
                "sourceKey": "longevityMap",
                "sourceFile": raw_path.name,
                "sourceRow": int(source_index + 2),
                "reportId": clean(raw_row.get("id")),
                "sourceSymbol": raw_gene,
                "symbolMapping": method,
                "association": clean(raw_row.get("Association")),
                "population": clean(raw_row.get("Population")),
                "variants": clean(raw_row.get("Variant(s)")),
                "pubmedId": pubmed,
                "pubmedUrl": f"https://pubmed.ncbi.nlm.nih.gov/{pubmed}/" if pubmed else None,
            }
        )
    for symbol in records:
        records[symbol].sort(key=lambda item: (str(item.get("pubmedId") or ""), item["sourceRow"]))
    return records, {
        "sourceRows": len(raw),
        "retainedRows": int(retained.sum()),
        "rawToCurationGeneMismatches": mismatched_rows,
        "genesWithRetainedAssociations": len(records),
        "retainedAssociationRecords": sum(len(items) for items in records.values()),
    }


def annotation_for(symbol: str, hgnc: dict[str, Any]) -> dict[str, Any]:
    location = clean(hgnc.get("location"))
    chromosome_match = re.match(r"^(\d+|X|Y|MT)", str(location or ""))
    hgnc_id = clean(hgnc.get("hgnc_id"))
    return {
        "approvedName": clean(hgnc.get("name")),
        "hgncId": hgnc_id,
        "chromosomeLocation": location,
        "chromosome": chromosome_match.group(1) if chromosome_match else None,
        "locusGroup": clean(hgnc.get("locus_group")),
        "locusType": clean(hgnc.get("locus_type")),
        "humanEntrezId": clean(hgnc.get("entrez_id")),
        "ensemblGeneId": clean(hgnc.get("ensembl_gene_id")),
        "uniprotIds": split_pipe(hgnc.get("uniprot_ids")),
        "aliases": split_pipe(hgnc.get("alias_symbol")),
        "previousSymbols": split_pipe(hgnc.get("prev_symbol")),
        "hgncUrl": f"https://www.genenames.org/data/gene-symbol-report/#!/hgnc_id/{urllib.parse.quote(str(hgnc_id or ''))}",
    }


def best_probability(record_groups: Iterable[Iterable[dict[str, Any]]]) -> dict[str, Any] | None:
    probabilities: list[dict[str, Any]] = []
    for records in record_groups:
        for record in records:
            for key in ("adjustedPValue", "pValue"):
                value = record.get(key)
                if value and value.get("value") is not None:
                    probabilities.append(value)
                    break
    return min(probabilities, key=p_sort_value) if probabilities else None


def build_gene(
    symbol: str,
    approved: dict[str, dict[str, Any]],
    orthology_by_human: dict[str, dict[str, Any]],
    transcriptomic: list[dict[str, Any]],
    epigenetic_age: list[dict[str, Any]],
    epigenetic_mortality: list[dict[str, Any]],
    longevity: list[dict[str, Any]],
    genage_human: dict[str, Any] | None,
    genage_mouse: list[dict[str, Any]],
) -> dict[str, Any]:
    source_flags = {
        "transcriptomic": bool(transcriptomic),
        "epigenetic": bool(epigenetic_age or epigenetic_mortality),
        "longevityMap": bool(longevity),
        "genAge": bool(genage_human or genage_mouse),
    }
    contexts = sorted({f"{item['organism']} | {item['cohort']}" for item in transcriptomic})
    organisms = sorted({item["organism"] for item in transcriptomic} | ({"Human"} if epigenetic_age or epigenetic_mortality or longevity or genage_human else set()) | ({"Mouse"} if genage_mouse else set()))
    endpoints = sorted({item["endpoint"] for item in transcriptomic} | ({"Chronological age"} if epigenetic_age else set()) | ({"All-cause mortality"} if epigenetic_mortality else set()) | ({"Longevity"} if longevity or genage_human or genage_mouse else set()))
    all_groups = (transcriptomic, epigenetic_age, epigenetic_mortality, longevity)
    best_p = best_probability(all_groups)
    sensitivity_supported = sum(
        1
        for item in epigenetic_mortality
        if item.get("sensitivityAnalysis")
        and p_sort_value(item["sensitivityAnalysis"].get("pValue")) <= 0.05
    )
    total_records = (
        len(transcriptomic)
        + len(epigenetic_age)
        + len(epigenetic_mortality)
        + len(longevity)
        + int(genage_human is not None)
        + len(genage_mouse)
    )
    positive = sum(1 for item in transcriptomic if item["direction"] == "Positive")
    negative = sum(1 for item in transcriptomic if item["direction"] == "Negative")
    return {
        "symbol": symbol,
        "annotation": annotation_for(symbol, approved[symbol.upper()]),
        "mouseOrtholog": orthology_by_human.get(symbol.upper()),
        "summary": None,
        "summarySource": None,
        "coverage": {
            "publicSourceCount": sum(source_flags.values()),
            "publicSources": [key for key in SOURCE_KEYS if source_flags[key]],
            "organisms": organisms,
            "transcriptomicContexts": contexts,
            "endpoints": endpoints,
        },
        "statistics": {
            "totalEvidenceRecords": total_records,
            "transcriptomicRecords": len(transcriptomic),
            "transcriptomicPositive": positive,
            "transcriptomicNegative": negative,
            "epigeneticAgeCpGs": len({item["cpg"] for item in epigenetic_age}),
            "epigeneticMortalityCpGs": len({item["cpg"] for item in epigenetic_mortality}),
            "epigeneticMortalitySensitivitySupported": sensitivity_supported,
            "longevityAssociations": len(longevity),
            "genAgeHumanRecords": int(genage_human is not None),
            "genAgeMouseRecords": len(genage_mouse),
            "bestReportedP": best_p,
        },
        "evidence": {
            "transcriptomic": transcriptomic,
            "epigeneticAge": epigenetic_age,
            "epigeneticMortality": epigenetic_mortality,
            "longevityMap": longevity,
            "genAgeHuman": genage_human,
            "genAgeMouse": genage_mouse,
        },
    }


def selection_key(gene: dict[str, Any]) -> tuple[Any, ...]:
    coverage = gene["coverage"]
    stats = gene["statistics"]
    human_evidence_breadth = sum(
        (
            stats["epigeneticAgeCpGs"] > 0,
            stats["epigeneticMortalityCpGs"] > 0,
            stats["longevityAssociations"] > 0,
            stats["genAgeHumanRecords"] > 0,
            any(item["organism"] == "Human" for item in gene["evidence"]["transcriptomic"]),
        )
    )
    capped_records = sum(
        min(count, 20)
        for count in (
            stats["transcriptomicRecords"],
            stats["epigeneticAgeCpGs"],
            stats["epigeneticMortalityCpGs"],
            stats["longevityAssociations"],
            stats["genAgeHumanRecords"] + stats["genAgeMouseRecords"],
        )
    )
    return (
        -coverage["publicSourceCount"],
        -human_evidence_breadth,
        -len(coverage["transcriptomicContexts"]),
        -len(coverage["endpoints"]),
        -stats["epigeneticMortalitySensitivitySupported"],
        -capped_records,
        p_sort_value(stats["bestReportedP"]),
        gene["symbol"],
    )


def source_definitions(selected: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "key": "transcriptomic",
            "title": "Cross-species transcriptomic signatures",
            "shortTitle": "Transcriptomic",
            "description": "Age, mortality, normalized-age, and lifespan associations across ITP, rodent meta-analysis, and multi-tissue analyses.",
            "organisms": ["Mouse", "Rodents", "Rat", "Macaque", "Human"],
            "sourceUrl": TRANSCRIPTOMIC_DOI,
            "geneCount": sum(bool(gene["evidence"]["transcriptomic"]) for gene in selected),
            "recordCount": sum(len(gene["evidence"]["transcriptomic"]) for gene in selected),
        },
        {
            "key": "epigenetic",
            "title": "Human epigenetic associations",
            "shortTitle": "Epigenetic",
            "description": "Gene-annotated CpGs associated with chronological age or all-cause mortality, with relatedness-adjusted mortality sensitivity results.",
            "organisms": ["Human"],
            "sourceUrl": EPIGENETIC_DOI,
            "geneCount": sum(bool(gene["evidence"]["epigeneticAge"] or gene["evidence"]["epigeneticMortality"]) for gene in selected),
            "recordCount": sum(len(gene["evidence"]["epigeneticAge"]) + len(gene["evidence"]["epigeneticMortality"]) for gene in selected),
        },
        {
            "key": "longevityMap",
            "title": "LongevityMap",
            "shortTitle": "LongevityMap",
            "description": "Curated human genetic association reports with significant longevity findings.",
            "organisms": ["Human"],
            "sourceUrl": LONGEVITY_URL,
            "geneCount": sum(bool(gene["evidence"]["longevityMap"]) for gene in selected),
            "recordCount": sum(len(gene["evidence"]["longevityMap"]) for gene in selected),
        },
        {
            "key": "genAge",
            "title": "GenAge",
            "shortTitle": "GenAge",
            "description": "Expert-curated human ageing genes and experimental mouse lifespan evidence linked by one-to-one orthology.",
            "organisms": ["Human", "Mouse"],
            "sourceUrl": GENAGE_URL,
            "geneCount": sum(bool(gene["evidence"]["genAgeHuman"] or gene["evidence"]["genAgeMouse"]) for gene in selected),
            "recordCount": sum(int(gene["evidence"]["genAgeHuman"] is not None) + len(gene["evidence"]["genAgeMouse"]) for gene in selected),
        },
    ]


def main() -> None:
    args = parse_args()
    inputs = [
        args.atlas_workbook,
        args.transcriptomic,
        args.epigenetic,
        args.genage_human,
        args.longevity,
        args.genage_models,
        args.orthology,
        args.hgnc,
    ]
    missing = [str(path) for path in inputs if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing required source files: {missing}")
    if args.gene_limit <= 0 or args.chunk_size <= 0:
        raise ValueError("gene-limit and chunk-size must be positive")

    build_time = datetime.now(UTC).isoformat(timespec="seconds")
    approved, alias_map, hgnc_report = load_hgnc(args.hgnc)
    mouse_to_human, orthology_by_human, orthology_report = load_one_to_one_orthology(args.orthology)
    eligible, genage_core, longevity_core, eligibility_report = load_eligibility(
        args.atlas_workbook, approved, alias_map, mouse_to_human
    )
    reference_genes = {"TP53", "CDKN2A", "MTOR", "SIRT1", "APOE", "TERT", "FOXO3", "IGF1", "FKBP5"}
    reference_genes &= eligible
    mandatory_core = genage_core | longevity_core | reference_genes
    if len(mandatory_core) > args.gene_limit:
        raise ValueError("The mandatory curated core exceeds the requested gene limit")

    transcriptomic, transcriptomic_report = load_transcriptomic_evidence(
        args.transcriptomic, eligible, mouse_to_human
    )
    epigenetic_age, epigenetic_mortality, epigenetic_report = load_epigenetic_evidence(
        args.epigenetic, eligible, approved, alias_map
    )
    genage_human, genage_human_report = load_genage_human_evidence(
        args.genage_human, genage_core, approved, alias_map
    )
    genage_mouse, genage_mouse_report = load_genage_mouse_evidence(
        args.genage_models, eligible, mouse_to_human
    )
    longevity, longevity_report = load_longevity_evidence(
        args.longevity, args.atlas_workbook, longevity_core, approved, alias_map
    )

    genes = [
        build_gene(
            symbol,
            approved,
            orthology_by_human,
            transcriptomic.get(symbol, []),
            epigenetic_age.get(symbol, []),
            epigenetic_mortality.get(symbol, []),
            longevity.get(symbol, []),
            genage_human.get(symbol),
            genage_mouse.get(symbol, []),
        )
        for symbol in sorted(eligible)
        if symbol.upper() in approved
    ]
    genes.sort(key=selection_key)
    genes_by_symbol = {gene["symbol"]: gene for gene in genes}

    mandatory = [genes_by_symbol[symbol] for symbol in mandatory_core if symbol in genes_by_symbol]
    mandatory.sort(key=selection_key)
    nonmandatory = [gene for gene in genes if gene["symbol"] not in mandatory_core]
    selected_symbols = {gene["symbol"] for gene in mandatory}
    selected = mandatory + [
        gene for gene in nonmandatory if gene["symbol"] not in selected_symbols
    ][: max(0, args.gene_limit - len(mandatory))]
    selected.sort(key=selection_key)

    if len(selected) != min(args.gene_limit, len(genes)):
        raise AssertionError("Selected gene count does not match the requested limit")
    missing_references = sorted(reference_genes - {gene["symbol"] for gene in selected})
    if missing_references:
        raise AssertionError(f"Reference ageing genes missing from release: {missing_references}")

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

    search_index: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    for chunk_number, start in enumerate(range(0, len(selected), args.chunk_size)):
        chunk_genes = selected[start : start + args.chunk_size]
        payload = {gene["symbol"]: gene for gene in chunk_genes}
        filename = f"genes-{chunk_number}.json"
        write_json(output / filename, payload, compact=True)
        chunks.append({"id": chunk_number, "file": filename, "geneCount": len(chunk_genes)})
        for gene in chunk_genes:
            ortholog = gene.get("mouseOrtholog") or {}
            search_index.append(
                {
                    "symbol": gene["symbol"],
                    "name": gene["annotation"].get("approvedName"),
                    "location": gene["annotation"].get("chromosomeLocation"),
                    "mouseSymbol": ortholog.get("mouseSymbol"),
                    "publicSourceCount": gene["coverage"]["publicSourceCount"],
                    "sources": gene["coverage"]["publicSources"],
                    "recordCount": gene["statistics"]["totalEvidenceRecords"],
                    "chunk": chunk_number,
                }
            )

    featured = [gene["symbol"] for gene in selected[:8]]
    sources = source_definitions(selected)
    manifest = {
        "title": "Human Aging Atlas",
        "schemaVersion": 2,
        "generatedAt": build_time,
        "geneCount": len(selected),
        "chunkSize": args.chunk_size,
        "chunks": chunks,
        "featuredGenes": featured,
        "referenceGenesVerified": sorted(reference_genes),
        "metrics": {
            "publicSources": len(sources),
            "evidenceRecords": sum(gene["statistics"]["totalEvidenceRecords"] for gene in selected),
            "genesWithHumanMouseOrtholog": sum(bool(gene.get("mouseOrtholog")) for gene in selected),
        },
    }
    build_report = {
        "generatedAt": build_time,
        "schemaVersion": 2,
        "selection": {
            "eligibleGenes": len(genes),
            "mandatoryCuratedCoreGenes": len(mandatory),
            "publishedGenes": len(selected),
            "method": [
                "Preserve every retained GenAge human and LongevityMap gene",
                "Fill remaining places by public-source breadth, human evidence, transcriptomic context breadth, endpoint breadth, sensitivity support, capped record count, and statistical support",
                "Use approved HGNC symbols and strict one-to-one human-mouse orthology",
            ],
            "referenceGenesVerified": sorted(reference_genes),
        },
        "reports": {
            "hgnc": hgnc_report,
            "orthology": orthology_report,
            "eligibility": eligibility_report,
            "transcriptomic": transcriptomic_report,
            "epigenetic": epigenetic_report,
            "genAgeHuman": genage_human_report,
            "genAgeMouse": genage_mouse_report,
            "longevityMap": longevity_report,
            "ncbi": ncbi_report,
        },
        "sourceFiles": [
            source_file(args.atlas_workbook, "curation layer"),
            source_file(args.transcriptomic, "public transcriptomic evidence"),
            source_file(args.epigenetic, "public epigenetic evidence"),
            source_file(args.genage_human, "public GenAge human release"),
            source_file(args.genage_models, "public GenAge model-organism release"),
            source_file(args.longevity, "public LongevityMap release"),
            source_file(args.orthology, "MGI/Alliance homology report"),
            source_file(args.hgnc, "HGNC reference"),
        ],
    }

    write_json(output / "manifest.json", manifest)
    write_json(output / "search-index.json", search_index, compact=True)
    write_json(output / "sources.json", sources)
    write_json(output / "datasets.json", sources)
    write_json(output / "build-report.json", build_report)
    print(
        json.dumps(
            {
                "publishedGenes": len(selected),
                "mandatoryCore": len(mandatory),
                "evidenceRecords": manifest["metrics"]["evidenceRecords"],
                "featuredGenes": featured,
                "ncbiSummaries": ncbi_report["summariesAttached"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
