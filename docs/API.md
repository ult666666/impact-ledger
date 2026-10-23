# Local API and CSV preview

Run `python3 -m impact_ledger --db .local/demo.db serve` and use the printed loopback origin. This synthetic educational service is local only. [All routes and security framing](ARCHITECTURE.md#http-contract) apply to both CSV operations.

| Action | CLI | HTTP |
| --- | --- | --- |
| Initialize an empty ledger | `impact-ledger --db ledger.db init` | Start an initialized Store locally |
| Advisory preview | `impact-ledger --db ledger.db preview-import sessions sessions.csv` | `POST /api/import/preview?kind=sessions` |
| Atomic append | `impact-ledger --db ledger.db import sessions sessions.csv` | `POST /api/import?kind=sessions` |

Use `attendance` instead of `sessions` for the second schema. Both routes accept raw `text/csv; charset=utf-8`, with one valid Content-Length and at most 1 MiB. CSV headers, field rules and 5,000-record limit are in the [data dictionary](DATA_DICTIONARY.md). The same Host/Origin, transfer encoding, timeout and content-type protections apply. Unsupported methods return 405. Unknown/repeated query parameters and invalid kinds return 400.

Preview requires an existing initialized database. CLI preview never creates a missing path or initializes schema. It prints JSON and returns 0 when valid, 1 for CSV diagnostics, 2 for usage/I/O/database failures. There is no persistent report file. API preview returns **200** for both valid and invalid CSV content, with this shape:

```json
{
  "kind": "sessions",
  "valid": false,
  "rows": 1,
  "errors": [
    {"row": 2, "field": "session_date", "code": "invalid_value", "message": "Date does not exist."}
  ],
  "errors_truncated": false,
  "errors_total": 1
}
```

`rows` is the number of checked records (up to 5,000), not the number of inserted rows. Each row error uses its physical CSV starting line; file-level errors use null for row and field. At most 100 errors are displayed; `errors_total` counts errors found before the file/record bounds stop processing. One row may have several errors. If a terminal file-level error arrives after the display fills, it replaces the last displayed row error. Error messages never echo file values.

## Preview error codes

| Code | Scope | Meaning |
| --- | --- | --- |
| `too_large` | File | More than 1 MiB; HTTP rejects excessive Content-Length as 413 before parsing |
| `encoding` | File | Invalid UTF-8 (a UTF-8 BOM is accepted) |
| `headers` | File | Missing or nonmatching ordered headers |
| `empty` | File | Header only, no data records |
| `malformed_csv` | File | Invalid quoting or CSV parser field-size bound exceeded |
| `row_limit` | File | More than 5,000 data records |
| `columns` | Row | Missing or extra columns |
| `invalid_value` | Field | Invalid ID, label, date or exact decimal syntax/range |
| `duplicate_id` | ID field | ID exists in the ledger or an earlier record in the file |
| `duplicate_pair` | `participant_id` | Participant/session pair exists in the ledger or earlier in the file |
| `missing_session` | `session_id` | Attendance references a session absent from the ledger |

Preview performs only read-only SQL in a consistent transaction. It adds no ledger rows or schema, executes no data-changing triggers, reserves no IDs and never initializes a missing database. SQLite may still manage locking and WAL auxiliary files (including `-wal`/`-shm`) in an existing ledger directory, even with `mode=ro`. This SQL read-only contract does not promise that every filesystem directory entry stays unchanged. Live WAL snapshots remain supported; the application neither deletes sidecars nor uses immutable-mode reads to suppress SQLite locking. It is optional and advisory; the database can change after it returns. Import accepts CSV bytes again, revalidates under its own write transaction, and relies on database constraints as the final guard. A valid preview can therefore be followed by an atomic rejection if another import uses an ID.

Successful import remains **201** with `{"kind":"sessions","imported":1}`. Invalid CSV is **400** with `{"error":"readable message; no rows added"}`; that example describes the error shape, not literal message text. It never partially succeeds. Framing/HTTP failures retain 400/403/408/411/413/415 statuses; unavailable SQLite returns 503. Static mode has no CSV API and clearly directs preview/import users to the local service.
