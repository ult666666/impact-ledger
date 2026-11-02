# Release notes

## Unreleased: plainer dashboard and README

- Replace the dashboard's slogans and section eyebrows with plain titles ("Overview", "Attendance by month", "Session ledger", "Import CSV", "Metric guide"), and state that the data is synthetic once, under the page title. The sidebar motto, decorative glyphs and the motto footer are gone; the footer names the project, its source and its license.
- Rewrite the stylesheet in readable form with one type scale (12 px and up instead of 8 to 10 px), system fonts, one green accent and right-aligned numbers. Text meets WCAG AA contrast, inputs and chart bars reach 3:1, and axe-core finds no violations in local or static mode (it found 121 low-contrast nodes before).
- Shorten the README to setup, features, commands, build and limits. The detailed walkthrough, CSV rules, audit workflow, static preview notes and demo totals move to `docs/GUIDE.md`.
- Keep the API, the CLI, business rules, `model.js` and `demo.json` unchanged. The browser tests follow the new page title, and the committed screenshots are regenerated.

## Unreleased: audit history, as-of reports and undo

- Record every write in an append-only, hash-chained `audit_log` inside the same SQLite transaction: actor label, UTC time, entity, the row before and after, batch ID and the previous entry's SHA-256. Triggers reject `UPDATE`, `DELETE` and out-of-order inserts on the log.
- Add `verify` (CLI, exit 0/1/2) and `GET /api/verify`: check triggers, digests, links, time order, batch structure, every replayed transition and the current tables, and optionally an expected head digest.
- Add as-of reports for summary, snapshot, comparison and export (`--as-of`, `--as-of-entry`, `as_of`, `as_of_entry`), rebuilt by replaying the verified log prefix, and a keyboard-accessible **Ledger version** control in the local dashboard.
- Add audited corrections (`update-session`, `update-attendance`, `delete-session`, `delete-attendance`), `undo-import` as a compensating batch, `history` and `GET /api/history`. Import responses add `batch_id`. Undo refuses when any later entry touched a row from the import, even if its values match again.
- Version the schema with `PRAGMA user_version`. A 1.2.x ledger gains a `baseline` batch on first open; a newer schema is refused.
- Keep current-table reports, the static payload and `demo.json` bytes unchanged. Tests add a random-operation property test, tamper detection, CLI, HTTP and browser coverage.

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
