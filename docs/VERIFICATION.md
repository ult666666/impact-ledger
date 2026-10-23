# Verification record

Verified locally on **23 October 2026**, macOS arm64, Python **3.15.0**, Node **24.18.0**, npm **11.16.0**, TypeScript **5.9.3**, and Playwright **1.61.1** with Chromium headless shell build **1228**.

This record describes observed local results, not a claim that hosted CI has already run. The repository CI additionally targets Python 3.11/3.13 on Ubuntu and Node 24. Hosted CI and Pages configuration require the repository owner's publication step. Both CI and Pages builds run the full Python and Chromium suites before publishing artifacts; action versions are pinned to official resolved commit IDs and jobs have 15-minute limits.

## Reproducible checks

| Command | Observed result |
| --- | --- |
| `npm ci --ignore-scripts` | Clean install from pinned lockfile; no runtime browser dependencies |
| `python3 -m unittest discover -s tests -v` | **31 tests passed**: 14 store/calculation, 13 real HTTP boundary, 4 CLI subprocess tests |
| `npm run typecheck` | Strict TypeScript check passed |
| `npm run build` | Compiled local assets and generated deterministic `site/` snapshot successfully |
| `npm test` | **9 Node tests passed** for the static accounting/export model |
| `npm run test:browser` | **6 real Chromium interaction tests passed** against local API and static mode |
| `python3 -m venv .local/package-env` then `.local/package-env/bin/pip install .` | Built and installed the wheel successfully in a clean virtual environment |
| Installed `impact-ledger ... seed` and `summary --program 'Learning Lab'`, run outside source root | 36 seeded sessions; 12 filtered sessions / 114 attendances returned |
| `.local/package-env/bin/python scripts/verify_package.py` | Installed package CLI, real HTTP health, HTML, app.js and model.js passed from outside the source root |

The Python suite uses temporary SQLite files, real connections, subprocess CLI invocations, and a live HTTP listener on a dynamic loopback port. HTTP tests do not mock the request handler. Browser tests launch the real CLI service and a separate static file server, then drive user controls and downloads.

## Boundaries and calculations checked

- Hand-computed unique participants, attendance, participant/session hours, exact cents, per-program/month summaries, zero attendance, and session-level spending.
- Inclusive date/program selection; invalid/reversed/noncanonical dates; honest empty selections; no percentage or average for zero denominators.
- Duplicate IDs within a file and against saved records; unknown session references; duplicate participant/session pairs; whole-file rollback after valid earlier rows.
- Exact headers/column counts, malformed CSV, invalid UTF-8, negative and nonfinite numbers, excessive precision, duration/money bounds, formula-like labels, oversized bodies and row counts.
- Hostile markup-shaped program names remain text; bilingual labels survive import, display, and export.
- Real filtered CSV attachment responses and correct original import/export fields.
- Cross-origin import rejection, invalid Host/rebinding checks, invalid/oversized/overlong/missing Content-Length, truncated bodies, unsupported transfer encoding/CSV charset/media type, unknown/repeated query parameters, and JSON application errors.
- Deterministic seed behavior and refusal to seed a nonempty ledger.

Tests were written before the corresponding implementation and were observed failing before implementation. Independent review also supplied a valid variance tie (20,000 budget cents and 20,201 actual cents): the original static pre-division floating rounding returned 1.00% while Python returned 1.01%. Positive/negative tie and safe-integer-bound regressions were observed failing, then the static ratio was changed to BigInt quotient/remainder half-up rounding. A later review reproduced a 5,000-digit Content-Length that disconnected without JSON; the length parser was bounded, and its regression case now passes. Independent review also reproduced a malformed absolute request target (`http://[`) that disconnected in URL parsing; a real raw-socket regression was observed failing before malformed/absolute targets were changed to JSON 400 responses. Two initial browser checks were corrected after inspection: one targeted a collapsed disclosure table rather than the visible ledger, and another treated the intentionally rejected invalid import's HTTP 400 as an unexpected console error.

## Browser and visual review

The six browser checks cover:

1. Synthetic local dashboard totals, accessible monthly data table, program filtering, and reset.
2. Empty date range with zero metrics and a visible explanation.
3. Downloaded session CSV corresponding to applied program filters.
4. Real invalid CSV import with zero persistence, then successful import of markup-shaped and Chinese labels without creating image elements.
5. A **390 × 844** mobile viewport without document overflow and with an independently scrollable ledger.
6. Read-only static preview mounted under `/impact-ledger/`, with functional filtering/attendance CSV download, disabled import, and an explicit local-service explanation.

The run observed no uncaught page errors or unexpected failed HTTP responses. The single expected HTTP 400 was the intentionally invalid CSV import. Desktop rendering at **1440 × 1100** and mobile rendering were inspected from these actual screenshots:

- [Desktop screenshot](screenshots/desktop.png)
- [Mobile screenshot](screenshots/mobile.png)

The desktop screenshot includes an opened exact-value chart table. Mobile uses the clean bundled synthetic snapshot. Both show synthetic labeling. Browser tests regenerate these files; they are examples, not performance measurements.

## Limits of verification

No independent security audit, full accessibility conformance audit, screen-reader session, load/concurrency benchmark, alternate browser engine, Windows run, or real organization dataset was used. Keyboard/focus semantics, labels, tables, responsive layout, and text-safe rendering are implemented; browser tests do not establish WCAG conformance. The local Python server is not suitable for public production deployment. No latency, adoption, or causal-impact claim is made.

The static model and API have independent hand-derived fixture tests and browser flows. This is not exhaustive equivalence proof for every possible database size or decimal ratio. Stored integer values stay exact; static ratio rounding is integer-rational within checked safe-integer bounds. Final JSON/browser numeric output is scoped to this small demonstration.
