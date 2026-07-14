# Static data schema

- `manifest.json`: release-level counts and featured genes.
- `search-index.json`: compact index used for browser-side gene search and filtering.
- `genes-0.json` through `genes-49.json`: 20 full gene records per chunk.
- `datasets.json`: source descriptions, inclusion rules, and source-level QC counts.
- `build-report.json`: reproducibility metadata, checksums, mapping counts, and NCBI/HGNC checks.

Gene records retain exact source sheet and row references. Transcriptomic evidence is restricted to source rows with adjusted P <= 0.05. Epigenetic evidence includes gene-annotated records from Tables S1-S4. LongevityMap includes both significant and non-significant findings.
