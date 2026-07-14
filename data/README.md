# Static data schema

- `manifest.json`: release metadata and featured genes.
- `search-index.json`: compact index used for browser-side gene search and filtering.
- `genes-0.json` through `genes-49.json`: full gene records, 20 per chunk.
- `datasets.json`: source descriptions and source-level QC counts.
- `build-report.json`: reproducibility metadata, checksums, mapping counts, and NCBI/HGNC checks.

Each gene record retains its exact source workbook, sheet, and row reference. Records are exposed on gene pages only when the source gene label maps unambiguously to an approved HGNC symbol.
