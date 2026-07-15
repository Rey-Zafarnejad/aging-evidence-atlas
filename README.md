# Human Aging Atlas

A static, searchable scientific reference for gene-level evidence from four public evidence collections:

- cross-species transcriptomic signatures, including ITP mouse-cohort analyses;
- human epigenetic associations with chronological age and all-cause mortality;
- significant human longevity associations from LongevityMap; and
- GenAge human curation and mouse lifespan evidence.

Pages are anchored to approved HGNC human symbols. Mouse evidence is connected only through a strict one-to-one human-mouse relationship in the MGI/Alliance homology report. Evidence remains separated by source and study design; the atlas does not assign a universal causal or biological-importance score.

## Run locally

From this directory:

```bash
python3 -m http.server 8000
```

Then open `http://127.0.0.1:8000/`.

## Data build

Generated JSON is committed so GitHub Pages can run the atlas without an application server or database. Original source files are read in place and are not copied into the public repository.

```bash
python3 build/build_human_aging_atlas.py --fetch-ncbi
python3 scripts/validate_data.py
python3 scripts/scientific_qc.py
```

The consolidated workbook defines the eligible gene universe. Evidence displayed on gene pages comes from the underlying public source files.

## Evidence scope

- **Transcriptomic:** all 18 source tables are evaluated; displayed records have FDR-adjusted P values at or below 0.05.
- **Epigenetic:** primary chronological-age CpGs and primary mortality CpGs are shown. The relatedness-adjusted mortality model is attached as sensitivity evidence for the same CpG.
- **LongevityMap:** significant, single-gene human association reports retained by the curation layer are shown from the public release.
- **GenAge:** retained human candidate-gene records and mouse model-organism lifespan records are shown. Other model organisms are outside this human-mouse release.

## Gene selection

The current release preserves the curated GenAge and LongevityMap core. Remaining places are selected deterministically using public-source breadth, human evidence, transcriptomic context breadth, endpoint breadth, sensitivity support, capped record count, and statistical support.

The displayed top-gene order is calculated across the complete eligible source release before the static publishing subset is selected. It is an evidence-support order, not a causal or biological-importance score.

## Reproducibility

- `data/build-report.json` records source checksums, dimensions, mapping results, and annotation QC.
- Every tabular evidence record retains its source sheet and row, or its source CSV row.
- `scripts/scientific_qc.py` independently reopens each source and reconciles every published value.
- NCBI summaries are attached only when the HGNC human Entrez ID and approved NCBI symbol agree.
- One-to-many and otherwise ambiguous human-mouse mappings are excluded.

## Database migration path

The static schema is designed to map to a later relational backend without changing the scientific contract. Expected entities are `genes`, `orthologs`, `sources`, `evidence_records`, `transcriptomic_results`, `epigenetic_results`, `longevity_associations`, `genage_records`, and `provenance`. The browser search index can later be replaced by an API query while preserving the same gene-page response shape.

## Public deployment

GitHub Pages deployment is defined in `.github/workflows/pages.yml`. The published site is available at:

`https://rey-zafarnejad.github.io/Human-Aging-Atlas/`

## Scientific sources

- Tyshkovskiy A, et al. *Universal transcriptomic hallmarks of mammalian ageing and mortality*. Nature (2026). https://doi.org/10.1038/s41586-026-10542-3
- Bernabeu E, et al. *Refining epigenetic prediction of chronological and biological age*. Genome Medicine (2023). https://doi.org/10.1186/s13073-023-01161-y
- GenAge. https://genomics.senescence.info/genes/
- LongevityMap. https://genomics.senescence.info/longevity/
- MGI/Alliance homology report. https://www.informatics.jax.org/downloads/reports/HOM_MouseHumanSequence.rpt
- HGNC approved gene set. https://www.genenames.org/download/
- NCBI Gene. https://www.ncbi.nlm.nih.gov/gene/

See [NOTICE.md](NOTICE.md) for source-data attribution and interpretation notes.
