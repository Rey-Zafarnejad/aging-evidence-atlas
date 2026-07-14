# Static data schema

- `manifest.json`: release metadata and featured genes.
- `search-index.json`: compact index used for browser-side gene search and filtering.
- `genes-0.json` through `genes-49.json`: full gene records, 20 per chunk.
- `datasets.json`: source descriptions, exact inclusion rules, and source-level QC counts.
- `build-report.json`: reproducibility metadata, checksums, row-level inclusion audits, mapping counts, and NCBI/HGNC checks.

Each gene record retains its exact source workbook, sheet, and row reference. tAge, LongevityMap, and GenAge records require source `Include = 1`. The source workbook has no `Include` column for cAge, bAge, or Integrative, so those modules retain all populated rows and expose records only when the gene annotation maps unambiguously to an approved HGNC symbol.
