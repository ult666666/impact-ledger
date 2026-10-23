# Verification record

## v1.2.0 — read-only CSV import preview

Verified locally on 23 October 2026 with macOS arm64, Python **3.15.0**, Node **24.18.0**, npm **11.16.0**, TypeScript **5.9.3**, Playwright **1.61.1** / Chromium headless shell **1228**. These are local results. Parent-owned independent review, hosted CI (including Python 3.11/3.13), and publication are separate steps.

| Command / journey | Observed result |
| --- | --- |
| `python3 -W error::ResourceWarning -m unittest discover -s tests -v` | **53 passed**, including ten preview, eight CLI subprocess and 17 real HTTP tests; existing store/comparison contracts retained |
| `npm run typecheck` | Strict TypeScript passed |
| `npm run build` | Committed JS and deterministic static site rebuilt |
| `npm test` | **13 Node tests passed** |
| `npm run test:browser` | **19 Chromium tests passed**, real local API and static repository-subpath workflows |
| `python3 -m venv .local/preview-v120-env` then `.local/preview-v120-env/bin/pip wheel --no-deps --wheel-dir .local/preview-wheel .` | Built **impact_ledger-1.2.0-py3-none-any.whl**, no runtime dependencies |
| `.local/preview-v120-env/bin/pip install --no-deps .local/preview-wheel/impact_ledger-1.2.0-py3-none-any.whl` | Fresh environment installed the built wheel |
| `.local/preview-v120-env/bin/python scripts/verify_package.py` | Outside-checkout console CLI 0/1/2, preview API, no-init/no-write checks, separate import, existing summary/comparison API/CLI, health, matching HTML/JS/CSS assets passed |
| `git diff --check` | No whitespace errors |

New tests were observed failing before implementation: missing `Store.preview_csv`, missing CLI command/HTTP route, and four absent-button browser journeys. One focused module now parses/validates both preview and real import. A final unavailable-database regression proved invalid kinds must be checked before opening SQLite; both preview and import now preserve that controlled ValidationError without touching missing paths. Tests cover BOM UTF-8, quoted commas/quotes, malformed quoting, physical record starting lines after quoted newlines, multiple field/row errors, exact decimal bounds/no normalization, header-only/empty/encoding/file/row limits, a 100-error cap and visible terminal file errors, duplicate IDs in file/ledger, participant/session uniqueness and missing references.

The default **DELETE-journal fixture** compares complete database bytes, mtime nanoseconds and directory entries before/after preview; a trigger that rejects inserts stays unexecuted. That directory-equality evidence is scoped to this fixture. The closed-WAL library/CLI regression starts with checkpointed data and all SQLite connections closed, accepts a valid preview, and verifies unchanged main-file bytes/mtime, complete logical rows, schema version, schema definitions and existing insert-rejecting trigger. It permits SQLite-managed `-wal`/`-shm` auxiliary entries; read-only SQL does not guarantee universal filesystem nonmutation. Neither application nor regression deletes sidecars or uses immutable mode to avoid SQLite locking. CLI tests show nonexistent parent/database paths remain nonexistent and an uninitialized zero-byte file remains unchanged. A real WAL writer commits during a preview between validation SELECTs: all checks retain one original snapshot, and a later preview observes the commit. Temporarily removing `BEGIN` made that regression fail, then restoring it returned the suite to green. Query tracing observes only SELECT/BEGIN. Another Store imports a previously previewed ID; importing the original two-row file fails with a current-state row diagnostic and no partial first row.

Chromium tests review a 102-row error file through an accessible table (100 displayed), correct same-name file bytes, prove valid preview changes neither metadata nor comparison, then import separately and observe refreshed totals/comparison. A real-response gate holds preview delivery while the file changes and proves stale validity never reappears. File/type changes clear results, attendance uses the same flow, an intervening real import causes atomic rejection, and static mode visibly requires the local API. The invalid-preview table scrolls within a 390px viewport. The original 15 browser cases still cover applied filters, imports, print readiness and adverse response ordering. There are no uncaught page errors; the extra expected HTTP 400 is the intentional preview-to-import ID conflict.

Current screenshots are rebuilt 1.2.0 evidence: [CSV preview error table](screenshots/import-preview.png), [desktop](screenshots/desktop.png), [comparison](screenshots/comparison.png), [mobile](screenshots/mobile.png), [print media](screenshots/print-report.png). The preview region was visually inspected for table legibility and clear separate actions. This is a focused Chromium check, not a full accessibility or physical-printer audit. No provider calls, runtime dependencies, schema migration or hosted write API were added. Preview remains advisory and cannot reserve IDs or predict changes after its read snapshot.

### Independent-review scope follow-up

The independent review approved the implementation at `38bf780` after 143 differential CSV fixtures and focused snapshot/atomicity/CLI/asset checks. Its P3 clarification reproduced SQLite creating empty WAL and shared-memory auxiliary files when opening an otherwise closed WAL ledger. The API, architecture and verification wording now distinguish ledger rows/schema/triggers/reservations and missing-database initialization from SQLite locking/sidecar management. Runtime behavior and live WAL support are unchanged. The follow-up reran all **53 Python tests** and the installed-wheel verification, including the new closed-WAL library/CLI check. The existing 13 Node and 19 browser results above remain the prior full feature run; UI/runtime sources and assets have no changes in this follow-up.

## v1.1.0 — prior-period comparison and stakeholder print report

Verified locally on 23 October 2026 with the same macOS/Python/Node/TypeScript/Chromium environment recorded below. These are local results; publication and hosted CI are separate steps.

| Command / journey | Observed result |
| --- | --- |
| `python3 -W error::ResourceWarning -m unittest discover -s tests -v` | **39 passed**: 14 existing store, 4 comparison, 15 real HTTP, 6 CLI subprocess tests; no resource warnings |
| `npm run typecheck` | Strict TypeScript check passed |
| `npm run build` | Local JavaScript compiled and deterministic static site regenerated |
| `npm test` | **13 Node tests passed** |
| `npm run test:browser` | **10 Chromium tests passed**, exercising local API and static mode under a repository subpath |
| Fresh `.local/comparison-v110-env` virtual environment and `pip install --no-deps .` | Built and installed `impact-ledger` **1.1.0** with packaged frontend assets |
| `.local/comparison-v110-env/bin/python scripts/verify_package.py` | Installed package and distribution versions both 1.1.0; outside-checkout seed, summary/comparison CLI, matching comparison HTTP response, health, HTML/JS, and print CSS verified |
| `git diff --check` | No whitespace errors |

The shared hand-derived `tests/fixtures/comparison.json` has **10 valid oracles and 13 invalid filter cases**, consumed by both Python and Node. It covers unequal calendar month boundaries, leap and nonleap years, DST dates, year-0000 rejection, minimum valid previous date in year 0001, an early year-0002 crossing, missing/blank/invalid/reversed dates, prior-period underflow, exact program selection, empty and zero prior windows, distinct people appearing in both windows, session costs with many attendances, and exact fractional deltas. Program-label oracles include 80 Unicode codepoints and Python whitespace parity. Node summary/export filters also reject invalid program labels and year 0000 consistently with the store. Separate high-integer regressions in both languages prove deltas subtract cents before converting to JSON numbers. Standard ratio half-up tie tests remain in the full suite.

New model, CLI, HTTP and UI tests were observed failing before implementation. The large-total regression exposed lost fractional deltas from subtracting already-converted numbers, and now passes with integer subtraction. A repeated `beforeprint` lifecycle check exposed lost disclosure restore state; the handler now retains the original closed disclosures across repeated print events. Rendered PDF review then exposed rounded-panel clipping in later ledger pages: a minimal print-only square-corner experiment removed it, and the final print style uses square corners on the multi-page ledger. The final six-page PDF was re-rendered for visual verification. Two initial browser expectations were corrected against the deterministic seed: September Learning Lab has 3 sessions and its immediately prior 30-day window has 5. No failing checks remain in the recorded final runs.

Browser coverage adds applied-filter comparison in both modes (draft form edits do not alter it), visible missing-date and year-0001-underflow messages, zero empty windows, opt-out hiding, local import refresh for both sessions and attendance, and print lifecycle restoration. Print checks run in both local and static modes, include all eight current totals and optional comparison, hide every button/input/select, and assert all visible table containers fit without horizontal clipping. The two expected HTTP 400 responses are intentional comparison underflow and invalid CSV import; no uncaught page errors or unexpected HTTP failures were observed.

The v1.1.0 run regenerated screenshot evidence (the files now show 1.2.0): [desktop](screenshots/desktop.png), [comparison](screenshots/comparison.png), [mobile with comparison](screenshots/mobile.png), and [print media](screenshots/print-report.png). The 390 × 844 mobile view has no document overflow. Chromium also wrote a six-page A4 PDF for pagination review; rendered pages were visually inspected for table/chart legibility and clipping. This intermediate PDF is not a release artifact. Printer/browser settings can alter pagination, and this is not a full accessibility or physical-printer audit.

### Review follow-up: overlapping requests and report readiness

The first independent feature review reproduced two timing defects: import completion could replace a newer submitted Apply request with older completed filters, and Print report could capture an enabled comparison while its response was pending. Both received response-order browser regressions using the real Python API: route gates hold delivery after real server responses are fetched, with no fabricated summary/comparison payloads and no arbitrary sleeps. The four primary regressions were also run against the original compiled assets and observed failing for the reported behavior before returning to the rebuilt fixes.

The browser now stores latest submitted filters independently of the completed view. Import refreshes reuse that submitted intent, while draft form edits stay unapplied. Print readiness tracks initial/current summary, import refresh and requested comparison. The button is disabled with a visible explanation while needed data is pending, and its handler rejects programmatically dispatched clicks during that state. Summary errors keep it disabled; completed comparison errors allow a report with an explicit printable unavailable reason. Toggling comparison while a summary loads waits for the submitted summary.

Follow-up full verification: **39 Python tests**, **13 Node tests**, strict typecheck and build passed; **15 Chromium tests passed**. New browser cases hold an import success and a newer submitted summary, release them in the adverse order, and assert final report/comparison/session/export agreement despite another unapplied draft selection. They hold comparison and summary responses to verify no print invocation occurs until requested data is ready, check checkbox changes during a pending summary, gate initial local/static data loading, and verify printable missing-date explanations in both modes. Browser test gates use bounded failure timeouts, not timing sleeps. The rebuilt installed **1.1.0** CLI/API/assets journey was repeated outside the source root. Accounting/calendar/model contracts and dependency versions are unchanged. The earlier v1.1.0 counts above describe the original settled-state feature run; this follow-up supersedes its readiness claim.

## Historical v1.0.0 verification

The original verification narrative and counts below are retained as historical evidence for baseline commit `3813fbe8bb2e538c10770ba8c98973a6bd2c7ec8`. Current screenshot files show v1.2.0; original screenshot bytes remain in that baseline commit.

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
