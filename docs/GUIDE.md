# Impact Ledger guide

The [README](../README.md) covers setup. This guide describes each part of the dashboard, the CSV
format and the command-line workflows in detail.

## Demo data

`seed` writes a deterministic ledger for July to September 2026. These are fixture totals, not
results of a real organization:

| Measure | Total |
| --- | --- |
| Sessions | 36 |
| Participants | 55 |
| Attendances | 342 |
| Participant hours | 684 |
| Planned spending | $7,872 |
| Actual spending | $7,851 |

Actual spending is $21 below the budget, so the variance is negative.

## The dashboard

- Apply inclusive date and program filters to every metric, chart, table, and export.
- Count people distinctly across selected sessions, attendance once per person/session, and spending once per session.
- Opt in to Compare prior period for an explicit applied start/end date range. The previous window has the same number of calendar days and uses the same program. Both windows show totals and signed deltas; people can recur in both.
- Choose Print report for a synthetic stakeholder report with applied filters, all current totals, charts, tables, and comparison when enabled. Browser print settings can save a PDF. Printing waits until the view, any import refresh and any enabled comparison have finished loading, and the button says what it is waiting for. If a finished comparison is unavailable, the report prints the reason.
- Compare actual and budget in USD. Percent variance uses budget as denominator and is undefined at zero budget.
- Open the exact accessible tables under both charts; use a keyboard to navigate the session table on small screens.
- Optionally choose Preview CSV before import to review row/column errors against the current local ledger. Preview adds no rows or reservations; file/type changes clear it. [Preview example](screenshots/import-preview.png).
- Import UTF-8 CSV atomically. Files with bad headers, invalid dates/amounts, duplicate IDs, missing session references, or excess size/rows add nothing.
- Export both session and attendance CSVs for the applied filters. Edits in the form take effect when you choose Apply filters. Import completion reloads the latest submitted filters, including a request still loading, without applying draft edits.
- Try an empty date range: the interface reports zero activity rather than substituting demo totals.
- Choose an earlier Ledger version to rebuild every total, chart, table, comparison, export and print report from the audit log as it stood after that change. The status line and print report name the audit entry and its SHA-256 digest, so a past report can be reproduced exactly.

Comparison requires both explicit dates. Set them and choose Apply filters if a visible message requests them. A 2026-09-01 through 2026-09-30 current window compares with 2026-08-02 through 2026-08-31, not the previous calendar month. Empty windows show zeros. Signed changes describe activity; lower variance alone does not establish improvement. [Comparison and print example](screenshots/print-report.png).

## CSV import and the CLI

Import sessions before attendance. A session can have zero attendance; its spending is still included. Each file is append-only. Existing IDs and duplicate participant/session pairs are rejected.

```sh
python3 -m impact_ledger --db .local/example.db init
python3 -m impact_ledger --db .local/example.db preview-import sessions examples/sessions.csv
python3 -m impact_ledger --db .local/example.db import sessions examples/sessions.csv
python3 -m impact_ledger --db .local/example.db import attendance examples/attendance.csv
python3 -m impact_ledger --db .local/example.db summary --program '社区服务'
python3 -m impact_ledger --db .local/demo.db comparison --start 2026-09-01 --end 2026-09-30 --program 'Learning Lab'
python3 -m impact_ledger --db .local/example.db export sessions --start 2026-10-01 --end 2026-10-31 --output .local/sessions.csv
```

`preview-import KIND FILE` requires an existing initialized ledger and prints JSON: exit 0 for valid, 1 for CSV validation problems, 2 for usage, file I/O, or database failure. It never creates missing database paths or initializes an existing empty database. Preview is advisory: another import can change IDs or references afterwards. Import always revalidates against current state and atomically rejects conflicts. Both paths use the same parser and exact field rules; at most 100 errors are displayed.

CSV headers must match exactly and in this order:

```csv
session_id,program,session_date,duration_hours,budget,actual
```

```csv
attendance_id,session_id,participant_id
```

Dates use `YYYY-MM-DD`. Hours and USD amounts accept at most two decimal places; exponent notation, negatives, NaN, and infinity are rejected. One import is limited to 1 MiB and 5,000 data rows. See the [data dictionary](DATA_DICTIONARY.md) for bounds and definitions.

## Audit history, past reports and undo

Every write appends to a hash-chained audit log in the same SQLite transaction: seeding, each CSV import, and the corrections below. An entry records the actor label, a UTC timestamp, the entity and ID, the row before and after the write in integer units, its batch ID, and the SHA-256 digest of the previous entry. SQLite triggers reject `UPDATE` and `DELETE` on the log and any insert that does not extend the chain in order.

```sh
python3 -m impact_ledger --db .local/demo.db import sessions examples/sessions.csv
python3 -m impact_ledger --db .local/demo.db --actor analyst update-session demo-s01-1 --actual 190.50
python3 -m impact_ledger --db .local/demo.db delete-attendance demo-s01-1-a01
python3 -m impact_ledger --db .local/demo.db history --limit 5
python3 -m impact_ledger --db .local/demo.db summary --as-of 2026-09-30
python3 -m impact_ledger --db .local/demo.db summary --as-of-entry 378
python3 -m impact_ledger --db .local/demo.db undo-import B000379
python3 -m impact_ledger --db .local/demo.db verify --expect-head <hash saved from an earlier verify>
```

- `--as-of` takes a UTC timestamp ending in `Z`, or a date meaning the end of that UTC day. It matches the time each change was recorded, not session dates, so on a demo seeded today `--as-of 2026-09-30` shows an empty ledger. `--as-of-entry` names an audit entry: entry 378 is the demo as seeded, before the import (`B000379`) and the two corrections above. Both rebuild the report by replaying the log after checking its digests, and the response includes an `as_of` block with the entry number and digest. The same options work for `comparison` and `export`, and as `as_of`/`as_of_entry` query parameters in the API.
- `undo-import BATCH` reverses one CSV import with a compensating batch of deletes. It refuses if a row from that import changed since (even if its values match again, as when a row was deleted and imported again), or if other records depend on it. History is never deleted.
- `verify` exits 0 when the chain, its triggers, every replayed transition and the current tables agree, 1 with a list of problems otherwise, and 2 for usage or file errors. Save the printed head digest outside the ledger: with `--expect-head`, verify also detects a truncated or fully rewritten log.
- Ledgers created by 1.2.x are upgraded on first open: their existing rows become one `baseline` batch. Changes made before that point have no history.

The actor is a self-declared label (`--actor`, default `local-cli`; web imports use `local-web`), not an authenticated identity. See [what the log does and does not protect](../SECURITY.md) and the [design](ARCHITECTURE.md#audit-history-and-as-of-reports).

## Static preview

`npm run build` also creates `site/`: the same interface, a deterministic synthetic snapshot, functional filters, and client-side CSV export. CSV validation preview and import are disabled with an explanation because checking ledger IDs/references requires the local API and SQLite. Preview it with:

```sh
python3 -m http.server 8000 --bind 127.0.0.1 --directory site
```

Open http://127.0.0.1:8000. Relative asset URLs work under a GitHub Pages repository path. You can also build from committed assets without Node and select a separate output directory whose parent already exists:

```sh
python3 scripts/build_site.py --output-directory '/tmp/impact preview'
python3 scripts/build_site.py --output-directory '/tmp/impact preview' --verify-only
```

The payload is exactly seven regular files: `index.html`, `app.js`, `model.js`, `styles.css`, `favicon.svg`, `demo.json`, and an empty `.nojekyll`.

- The builder refuses unsafe output paths and never deletes unknown files. Move an unknown file or folder out of the output directory yourself; there is no force option.
- A rebuild replaces only missing or changed generated files.
- `--verify-only` checks an existing output without changing it. It prints a JSON receipt of byte counts and SHA-256 digests and exits 0 on an exact match, 1 on any mismatch or I/O failure, and 2 on a usage error.

The [architecture notes](ARCHITECTURE.md#read-only-static-mode) give the full path, verification and atomic-replacement rules.

The single [CI and Pages workflow](../.github/workflows/ci.yml) runs the Python matrix and one frontend build/model/Chromium path. After browser checks it verifies the same `site/` bytes, then uploads only on non-PR `main`. Deployment needs both test jobs and consumes that run's tested artifact. PRs and non-main manual runs get all tests and skip publication. Only the gated deploy job has Pages/token write permissions; concurrency is scoped by ref. Screenshot artifacts expire after seven days. Repository Pages must already use GitHub Actions. No Python write API, databases, import CSVs, dependencies, wheels, or local reports are in the payload.

## Scope

Built to make data-to-stakeholder handoffs inspectable: strict inputs, explicit denominators, recoverable errors, and bilingual examples. There are no external integrations, provider calls, credentials, analytics beacons, or paid services. The interface loads no third-party assets.

This is not a production case-management or accounting system. No authentication, real eligibility population, outcomes, capacity, partial-attendance tracking, backup management, or causal identification is implemented. The audit history is tamper-evident, not tamper-proof: anyone who can edit the database file can rewrite it, and only a head digest saved elsewhere reveals a consistent rewrite. Actor labels are not authenticated. Past reports replay the log, so they take longer as history grows: on a 25,000-entry synthetic ledger, a summary as of the latest entry took 315 ms against 68 ms from the current tables (`python3 scripts/benchmark_history.py`). Session costs are direct session amounts, not organization-wide expenditures. Do not import private or real participant records. See [limitations and architecture](ARCHITECTURE.md) and [security policy](../SECURITY.md).
