# Aging Evidence Atlas

A static, searchable scientific reference for gene-level evidence across:

- transcriptomic signatures of ageing, mortality, normalized age, and lifespan;
- epigenome-wide CpG associations with chronological age and all-cause mortality;
- human longevity association reports from LongevityMap; and
- curated human ageing genes from GenAge.

The public demonstration contains a selected set of HGNC-mapped gene records. It reports evidence components separately and does not assign a causal or biological-importance score.

## Run locally

From this directory:

```bash
python3 -m http.server 8000
```

Then open `http://127.0.0.1:8000/`.

## Data build

The generated JSON files are committed so the public site does not need a server or database. The original Excel/CSV source files are not copied into the website repository.

```bash
python3 build/build_atlas_data.py --fetch-ncbi --chunk-size 20
python3 scripts/validate_data.py
python3 scripts/scientific_qc.py
```

The builder accepts command-line paths for each source file. The defaults point to the local FAST PROSPR data directory used for this release.

## Selection hierarchy

Genes are ordered lexicographically by:

1. number of supplied evidence collections represented;
2. number of human evidence types represented;
3. GenAge curation status;
4. significant LongevityMap reports;
5. source analysis units;
6. evidence-record count; and
7. source statistical support.

This order supports browsing. It is not a weighted evidence score and should not be interpreted as causality, clinical actionability, or biological importance.

## Reproducibility

- `data/build-report.json` records source checksums, row counts, mapping counts, and annotation QC.
- Each gene record retains source filename, sheet, and row number.
- `scripts/scientific_qc.py` reconciles every published record against the original source row.
- NCBI summaries are attached only when the HGNC human Entrez ID and approved NCBI symbol agree.

## Public deployment

GitHub Pages deployment is defined in `.github/workflows/pages.yml`. The published site is expected at:

`https://rey-zafarnejad.github.io/aging-evidence-atlas/`

## Scientific sources

- Tyshkovskiy A, et al. *Universal transcriptomic hallmarks of mammalian ageing and mortality*. Nature (2026). https://doi.org/10.1038/s41586-026-10542-3
- Bernabeu E, et al. *Refining epigenetic prediction of chronological and biological age*. Genome Medicine (2023). https://doi.org/10.1186/s13073-023-01161-y
- GenAge human genes. https://genomics.senescence.info/genes/human.html
- LongevityMap. https://genomics.senescence.info/longevity/
- HGNC approved gene set. https://www.genenames.org/download/
- NCBI Gene. https://www.ncbi.nlm.nih.gov/gene/

See [NOTICE.md](NOTICE.md) for source-data attribution and scope notes.
