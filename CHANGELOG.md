# Release notes

## 1.2.1 — exact static payload and one tested publication path

- Refuse unexpected output entries, selected/file symlinks, nonregular entries and source/output overlap before target writes. Rebuild known generated files with private staging and per-file atomic replacement, preserving unselected hardlink originals.
- Add `scripts/build_site.py --output-directory PATH --verify-only`: compare the actual seven-file payload with committed assets/static shell/unchanged synthetic seed, return bounded JSON byte/SHA-256 receipts and controlled failure codes, and never repair the selected target.
- Consolidate CI/Pages into one workflow. Verify the browser-tested directory before main-only upload; same-workflow deploy needs both Python and frontend tests, owns the Pages/token write permissions, and uses ref-scoped concurrency. PR/non-main runs skip publication. Pin Ubuntu 24.04 explicitly and retain screenshots for seven days.
- Keep API, business rules, visible synthetic data, browser assets, comparison/import-preview/print behavior and historical release records unchanged. Target-only read semantics and non-atomic directory/concurrent-path limits are documented. [Local verification](docs/VERIFICATION.md#v121--exact-static-payload-and-single-workflow).

## 1.2.0 — advisory CSV import preview

- Add optional Preview CSV with row/column diagnostics, a 100-error display cap and explicit no-write/advisory wording. File/type changes discard old or delayed results. Static mode explains the local API requirement.
- Add `preview-import KIND FILE` JSON CLI (0 valid, 1 CSV problems, 2 I/O/usage/database error) and `POST /api/import/preview?kind=...` (200 valid/invalid CSV, existing framing protections).
- Share one bounded UTF-8/CSV parser and exact validator across preview and import. Preview uses read-only SQL in one snapshot; actual import reparses/revalidates in a writer transaction and commits atomically. Preview never initializes paths or reserves IDs.
- Retain applied-filter/comparison, exact-accounting, print-readiness and adverse-response-order behavior from 1.1.0. No new runtime dependencies or schema migration.

## 1.1.0 — comparison and print reports

Equal-day prior-period comparison, applied-filter reports, exact integer-unit deltas and guarded print readiness. [Historical verification](docs/VERIFICATION.md#v110--prior-period-comparison-and-stakeholder-print-report).
