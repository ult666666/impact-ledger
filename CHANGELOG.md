# Release notes

## 1.2.0 — advisory CSV import preview

- Add optional Preview CSV with row/column diagnostics, a 100-error display cap and explicit no-write/advisory wording. File/type changes discard old or delayed results. Static mode explains the local API requirement.
- Add `preview-import KIND FILE` JSON CLI (0 valid, 1 CSV problems, 2 I/O/usage/database error) and `POST /api/import/preview?kind=...` (200 valid/invalid CSV, existing framing protections).
- Share one bounded UTF-8/CSV parser and exact validator across preview and import. Preview uses read-only SQL in one snapshot; actual import reparses/revalidates in a writer transaction and commits atomically. Preview never initializes paths or reserves IDs.
- Retain applied-filter/comparison, exact-accounting, print-readiness and adverse-response-order behavior from 1.1.0. No new runtime dependencies or schema migration.

## 1.1.0 — comparison and print reports

Equal-day prior-period comparison, applied-filter reports, exact integer-unit deltas and guarded print readiness. [Historical verification](docs/VERIFICATION.md#v110--prior-period-comparison-and-stakeholder-print-report).
