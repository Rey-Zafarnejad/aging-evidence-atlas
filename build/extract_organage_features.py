#!/usr/bin/env python3
"""Extract gene-linked features from the published OrganAge bootstrap models.

The OrganAge package ships 500 LASSO models for each organ. This extractor
records proteins with a non-zero coefficient in at least one model and leaves
multi-gene SomaScan targets out of gene-level attribution.
"""

from __future__ import annotations

import argparse
import json
import pickle
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


PINNED_COMMIT = "59303fd0dccc191be1ff34bf0bbf5efd8b90387a"
MODEL_FAMILY = "Zprot_stableassayps_perf95"
EXCLUDED_MODELS = {"Conventional", "Organismal"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--organage-repo",
        type=Path,
        required=True,
        help="Checkout of https://github.com/hamiltonoh/organage at the pinned commit",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path(__file__).resolve().parent / "derived/organage_features.csv",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    data_root = args.organage_repo / "src/organage/data"
    protein_lists = json.loads(
        (
            data_root
            / "tissue_pproteinlist_5k_dict_gtex_tissue_enriched_fc4_stable_assay_proteins_seqid.json"
        ).read_text(encoding="utf-8")
    )
    annotations = pd.read_csv(
        data_root / "SomaScan_V4.0_5K_Annotated_Content_20210616.csv", dtype=str
    ).set_index("SeqId", drop=False)
    model_root = data_root / "ml_models/KADRC" / MODEL_FAMILY

    rows: list[dict[str, object]] = []
    warnings.filterwarnings("ignore", message="Trying to unpickle estimator")
    for organ, proteins in protein_lists.items():
        if organ in EXCLUDED_MODELS:
            continue
        model_files = sorted((model_root / organ).glob("*aging_model.pkl"))
        if len(model_files) != 500:
            raise ValueError(f"Expected 500 {organ} models, found {len(model_files)}")

        selection_counts: Counter[str] = Counter()
        coefficient_sums: defaultdict[str, float] = defaultdict(float)
        for model_file in model_files:
            with model_file.open("rb") as handle:
                model = pickle.load(handle)
            coefficients = model.coef_[1:]
            if len(coefficients) != len(proteins):
                raise ValueError(f"Feature count mismatch for {organ}: {model_file.name}")
            for seq_id, coefficient in zip(proteins, coefficients, strict=True):
                if coefficient != 0:
                    selection_counts[seq_id] += 1
                    coefficient_sums[seq_id] += float(coefficient)

        for seq_id, selected_models in selection_counts.items():
            annotation = annotations.loc[seq_id]
            gene_symbol = str(annotation.get("Entrez Gene Name") or "").strip()
            if not gene_symbol or "|" in gene_symbol:
                continue
            mean_coefficient = coefficient_sums[seq_id] / selected_models
            rows.append(
                {
                    "organ": organ,
                    "seq_id": seq_id,
                    "target_name": annotation.get("Target Name"),
                    "target_full_name": annotation.get("Target Full Name"),
                    "gene_symbol": gene_symbol,
                    "entrez_gene_id": annotation.get("Entrez Gene ID"),
                    "hgnc_id": annotation.get("HGNC ID"),
                    "selected_models": selected_models,
                    "model_count": len(model_files),
                    "mean_nonzero_coefficient": mean_coefficient,
                    "coefficient_direction": "Positive" if mean_coefficient > 0 else "Negative",
                    "model_family": MODEL_FAMILY,
                    "source_commit": PINNED_COMMIT,
                }
            )

    output = pd.DataFrame(rows).sort_values(
        ["gene_symbol", "organ", "seq_id"], kind="stable"
    )
    if output.empty or output["seq_id"].duplicated().any():
        raise AssertionError("OrganAge extraction produced empty or duplicate protein records")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    output.to_csv(args.output, index=False)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "records": len(output),
                "genes": output["gene_symbol"].nunique(),
                "organs": output["organ"].nunique(),
                "excludedAmbiguousTargets": sum(
                    1
                    for organ, proteins in protein_lists.items()
                    if organ not in EXCLUDED_MODELS
                    for seq_id in proteins
                    if "|" in str(annotations.loc[seq_id].get("Entrez Gene Name") or "")
                ),
                "sourceCommit": PINNED_COMMIT,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
