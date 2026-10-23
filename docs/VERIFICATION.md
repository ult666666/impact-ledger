# Verification record

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

Screenshots are regenerated current v1.1.0 evidence: [desktop](screenshots/desktop.png), [comparison](screenshots/comparison.png), [mobile with comparison](screenshots/mobile.png), and [print media](screenshots/print-report.png). The 390 × 844 mobile view has no document overflow. Chromium also wrote a six-page A4 PDF for pagination review; rendered pages were visually inspected for table/chart legibility and clipping. This intermediate PDF is not a release artifact. Printer/browser settings can alter pagination, and this is not a full accessibility or physical-printer audit.

## Historical v1.0.0 verification

The original verification narrative and counts below are retained as historical evidence for baseline commit `3813fbe8bb2e538c10770ba8c98973a6bd2c7ec8`. Current screenshot files show v1.1.0; original screenshot bytes remain in that baseline commit.

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
