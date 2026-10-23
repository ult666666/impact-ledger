# Data dictionary

All examples and seeded records are fictional. One currency, USD, applies to every session. There is no name, email, age, address, demographic, or employer field.

## Session import

`session_id,program,session_date,duration_hours,budget,actual`

| CSV field | Meaning and validation | SQLite representation |
| --- | --- | --- |
| `session_id` | Globally unique, 1–64 ASCII letters/digits/dots/underscores/hyphens; first character alphanumeric | `TEXT PRIMARY KEY` |
| `program` | Case-sensitive printable label, 1–80 characters, no surrounding spaces, controls, or leading `= + - @` formula marker. English/Mandarin and markup-shaped text are permitted; browser renders text. | `TEXT NOT NULL` |
| `session_date` | Existing calendar date, exact `YYYY-MM-DD`, inclusive filter basis | `TEXT NOT NULL` |
| `duration_hours` | Greater than 0 and at most 24, at most two decimal places; full-session duration per person | `duration_hundredths INTEGER` |
| `budget` | Planned direct session spending in USD, 0–10,000,000, at most two decimals | `budget_cents INTEGER` |
| `actual` | Actual direct session spending in USD, same bounds | `actual_cents INTEGER` |

Decimal syntax has no sign, comma, currency symbol, exponent, spaces, NaN, or infinity. A leading zero is accepted only for `0` or a fraction such as `0.50`. Fields are not silently trimmed or rounded. Program labels cannot contain ASCII controls (including newlines/tabs) or surrogate code points. `<img ...>` is retained as a text label, never executed.

## Attendance import

`attendance_id,session_id,participant_id`

| CSV field | Meaning and validation |
| --- | --- |
| `attendance_id` | Globally unique attendance record ID; same ID syntax as session IDs |
| `session_id` | Existing session reference; foreign key |
| `participant_id` | Fictional stable person ID; same ID syntax; unique together with session ID |

The same person can attend many sessions but can appear only once per session. IDs, rather than inferred names, determine unique people. Importing the same file twice is rejected; it is not an update or upsert.

## File contract

Files use UTF-8 (an initial BOM is accepted), comma separators, and exact ordered headers. Missing/extra columns, duplicate/wrong headers, malformed quoting, blank data rows, header-only files, and invalid fields are rejected. Quoted commas and double quotes in program labels are handled by the CSV parser. Per-file limits are 1 MiB and 5,000 data rows. Existing duplicates and foreign-key failures roll back all inserted rows.

Exports are UTF-8 CSV with CRLF line endings, the original ordered headers, and two-place hours/USD values. Session exports sort by date then ID; attendance exports sort by attendance ID. Both select attendance through the same session filters. Allowed program labels cannot begin with spreadsheet formula markers.

## Metrics

Every measure uses the selected session set after inclusive dates and exact program filters.

| API field | Definition and denominator |
| --- | --- |
| `sessions` | Number of selected sessions, including zero-attendance sessions |
| `unique_participants` | Distinct participant IDs in attendance linked to selected sessions |
| `attendance` | Number of unique person/session attendance records |
| `participant_hours` | Sum of session duration × attendance count |
| `session_hours` | Sum of session durations once per session |
| `budget` | Sum of session planned spending once per session, USD |
| `actual` | Sum of session actual spending once per session, USD |
| `variance` | Actual − budget, USD; positive is over budget |
| `variance_percent` | `(actual − budget) / budget × 100`, rounded to two decimals; `null` when selected budget is zero |
| `attendance_per_participant` | Attendance / unique participants, rounded to two decimals; `null` with zero participants |
| Program chart share | Program attendance / all selected attendance × 100; displays 0% if no attendance exists |

Overall distinct participants are calculated across all selected records, not by adding program/month distinct totals. Monthly values group sessions by `YYYY-MM`; program values group exact labels. Financial denominator stays at session level. Empty filters produce zero counts/amounts, empty arrays, and `null` ratios.

There is no attendance rate, outcome score, causal-impact estimate, or eligible-population denominator. The dashboard cannot infer the quality or consequences of participation.

## Prior-period comparison

Comparison requires explicit inclusive start and end dates; summary remains usable without either date. `days` is the inclusive number of calendar days. The previous period ends the day before current start and contains the same `days`, with the same exact program filter. Example: 2026-09-01–2026-09-30 compares to 2026-08-02–2026-08-31. Dates are calendar-based and independent of DST. A prior window before year 0001 is rejected.

`current` and `previous` each contain `start`, `end`, and the standard `totals` object. People are distinct inside each window; a returning person counts in both windows. Session spending is counted once regardless of attendance. `deltas` reports current minus previous for the first eight numeric measures above (sessions through variance), calculated in integer units before JSON conversion. Negative variance is under-budget spending; a negative variance delta alone does not mean improvement. No percentage-change fields are emitted. Empty windows have zero counts/amounts and null standard ratios when their denominator is zero.

Print reports show the applied filter labels, these current totals, and comparison if enabled and available. All records remain synthetic and activity is not causal impact.
