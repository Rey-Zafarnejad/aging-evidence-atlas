# Human Aging Atlas

A static, searchable scientific reference for gene-level evidence organized into four active omics layers:

- **Genomics:** GenAge human curation and mouse lifespan evidence, plus significant human LongevityMap associations;
- **Epigenomics:** cAge chronological-age CpGs and bAge all-cause mortality CpGs;
- **Transcriptomics:** tAge cross-species signatures, including ITP mouse-cohort analyses; and
- **Proteomics:** OrganAge proteins selected by published organ-specific age models.

Metabolomics and Integrative (IMM-AGE) are identified as planned layers and do not appear as gene evidence until source records are incorporated.

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

The OrganAge cache is derived from the official package at a pinned commit. To reproduce that compact cache from an OrganAge checkout:

```bash
python3 build/extract_organage_features.py --organage-repo /path/to/organage
```

## Evidence scope

- **Genomics:** GenAge and LongevityMap remain distinguishable nested sources. Other GenAge model organisms are outside this human-mouse release.
- **Epigenomics:** primary cAge and bAge CpGs are shown. The relatedness-adjusted bAge model is attached as sensitivity evidence for the same CpG.
- **Transcriptomics:** all 18 tAge source tables are evaluated; displayed records have FDR-adjusted P values at or below 0.05.
- **Proteomics:** unambiguous single-gene SomaScan targets with a non-zero coefficient in at least one of 500 OrganAge bootstrap models are shown with organ assignment and selection frequency. Organ-independent and cognition-optimized models are excluded.

## Gene selection

The current release preserves the eligible GenAge, LongevityMap, and OrganAge core. Remaining entries are selected deterministically using omics-layer breadth, public-source breadth, human evidence, transcriptomic context breadth, endpoint breadth, sensitivity support, capped record count, and statistical support. The public table defaults to alphabetical order and can be sorted by the number of represented evidence layers; no biological-importance rank is assigned.

## Reproducibility

- `data/build-report.json` records source checksums, dimensions, mapping results, and annotation QC.
- Every tabular evidence record retains its source sheet and row, or its source CSV row.
- `scripts/scientific_qc.py` independently reopens each source and reconciles every published value.
- NCBI summaries are attached only when the HGNC human Entrez ID and approved NCBI symbol agree.
- One-to-many and otherwise ambiguous human-mouse mappings are excluded.

## Database migration path

The static schema is designed to map to a relational backend without changing the scientific contract. Expected entities are `genes`, `orthologs`, `evidence_layers`, `sources`, `evidence_records`, `transcriptomic_results`, `epigenetic_results`, `longevity_associations`, `genage_records`, `organage_features`, and `provenance`. The browser search index can later be replaced by an API query while preserving the same gene-page response shape.

## Public deployment

GitHub Pages deployment is defined in `.github/workflows/pages.yml`. The published site is available at:

`https://rey-zafarnejad.github.io/Human-Aging-Atlas/`

## Scientific sources

- Tyshkovskiy A, et al. *Universal transcriptomic hallmarks of mammalian ageing and mortality*. Nature (2026). https://doi.org/10.1038/s41586-026-10542-3
- Bernabeu E, et al. *Refining epigenetic prediction of chronological and biological age*. Genome Medicine (2023). https://doi.org/10.1186/s13073-023-01161-y
- Oh HS-H, et al. *Organ aging signatures in the plasma proteome track health and disease*. Nature (2023). https://doi.org/10.1038/s41586-023-06802-1
- GenAge. https://genomics.senescence.info/genes/
- LongevityMap. https://genomics.senescence.info/longevity/
- Alpert A, et al. *A clinically meaningful metric of immune age derived from high-dimensional longitudinal monitoring*. Nature Medicine (2019). https://doi.org/10.1038/s41591-019-0381-y
- MGI/Alliance homology report. https://www.informatics.jax.org/downloads/reports/HOM_MouseHumanSequence.rpt
- HGNC approved gene set. https://www.genenames.org/download/
- NCBI Gene. https://www.ncbi.nlm.nih.gov/gene/

See [NOTICE.md](NOTICE.md) for source-data attribution and interpretation notes.
