# Static data schema

- `manifest.json`: release metadata, chunk index, and release checks.
- `search-index.json`: compact browser search index with human identity, mouse ortholog, omics-layer coverage, nested source labels, and chunk location.
- `genes-0.json` through `genes-49.json`: source-centric gene records, 20 per chunk.
- `sources.json`: public source definitions used by the interface.
- `datasets.json`: compatibility alias of `sources.json`.
- `build-report.json`: source checksums, selection summary, mapping results, and quality-control metadata.

Each gene record contains:

- approved HGNC human identity and NCBI annotation;
- a strict one-to-one MGI/Alliance mouse ortholog when available;
- omics-layer coverage, nested source labels, and non-composite record counts;
- transcriptomic source rows with organism, cohort, endpoint, model, effect, and P values;
- chronological-age and mortality CpGs, with mortality sensitivity estimates attached to the matching CpG;
- Genomics records from LongevityMap and GenAge;
- Epigenomics records from cAge and bAge;
- Transcriptomics records from tAge; and
- Proteomics records from OrganAge organ-specific models.

Tabular records retain source sheet and row provenance. CSV-derived records retain their source row. The structure is intended to become the response contract for a future SQL-backed API.
