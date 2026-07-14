# Aging Evidence Atlas

A static, searchable scientific reference for gene-level evidence in Dr. Mahdi's consolidated Human Aging and Longevity Atlas workbook. The atlas separates six evidence modules:

- `tAge`: transcriptomic associations with chronological age;
- `cAge`: CpG associations with chronological age;
- `bAge`: CpG associations with all-cause mortality;
- `Integrative`: gene-linked CpGs with transcriptomic-epigenetic convergence;
- `LongevityMap`: retained significant, single-gene longevity associations; and
- `GenAge`: retained curated human ageing genes.

The public demonstration contains an HGNC-mapped subset selected by a deterministic browsing hierarchy. It reports evidence components separately and does not assign a causal or biological-importance score.

## Run locally

From this directory:

```bash
python3 -m http.server 8000
```

Then open `http://127.0.0.1:8000/`.

## Data build

Generated JSON files are committed so the public site does not need a server or database. The source workbook is read in place and is never copied into the website repository.

```bash
python3 build/build_atlas_data.py --fetch-ncbi --chunk-size 20
python3 scripts/validate_data.py
python3 scripts/scientific_qc.py
```

The builder accepts command-line paths for the consolidated workbook and annotation references. Defaults point to the local FAST PROSPR data directory used for this release.

## Inclusion rules

- `tAge`: keep rows where the workbook's final `Include` value is 1. This exactly matches `P.Adjusted < 0.01` in the supplied workbook.
- `LongevityMap`: keep rows where final `Include` is 1. These are significant, single-gene records satisfying the helper flags.
- `GenAge`: keep rows where final `Include` is 1.
- `cAge`, `bAge`, and `Integrative`: these sheets have no `Include` column, so all populated source rows remain in their module. A row appears on a gene page only when its gene annotation maps unambiguously to an approved HGNC symbol.

The row-level sheets are authoritative. The source-level discrepancies identified during validation are recorded in `data/build-report.json` and shown on the site Methods and Sources pages.

## Browsing hierarchy

Genes are ordered lexicographically by:

1. number of evidence modules represented;
2. number of curated modules represented;
3. presence of integrative transcriptomic-epigenetic evidence;
4. supporting record count;
5. strongest available source P value; and
6. approved gene symbol.

This order supports browsing. It is not a weighted evidence score and should not be interpreted as causality, clinical actionability, or biological importance.

## Reproducibility

- `data/build-report.json` records source checksums, row counts, final inclusion counts, mapping counts, and annotation QC.
- Each gene record retains its source workbook, sheet, and row number.
- `scripts/scientific_qc.py` independently recomputes inclusion logic and reconciles every published record against the source row.
- NCBI summaries are attached only when the HGNC human Entrez ID and approved NCBI symbol agree.

## Public deployment

GitHub Pages deployment is defined in `.github/workflows/pages.yml`. The published site is available at:

`https://rey-zafarnejad.github.io/aging-evidence-atlas/`

## Scientific sources

- Tyshkovskiy A, et al. *Universal transcriptomic hallmarks of mammalian ageing and mortality*. Nature (2026). https://doi.org/10.1038/s41586-026-10542-3
- Bernabeu E, et al. *Refining epigenetic prediction of chronological and biological age*. Genome Medicine (2023). https://doi.org/10.1186/s13073-023-01161-y
- GenAge human genes. https://genomics.senescence.info/genes/human.html
- LongevityMap. https://genomics.senescence.info/longevity/
- HGNC approved gene set. https://www.genenames.org/download/
- NCBI Gene. https://www.ncbi.nlm.nih.gov/gene/

See [NOTICE.md](NOTICE.md) for source-data attribution and scope notes.
