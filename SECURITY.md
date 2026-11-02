# Security policy

Impact Ledger is an educational local demo for synthetic records. Do not use it for real participant information, confidential records, grant reporting, or financial decisions.

The Python server binds only `127.0.0.1`. It checks the Host header, rejects cross-origin imports, sends no CORS permissions, caps request bodies at 1 MiB, times out reads, and uses parameterized SQLite queries. Imports validate the complete file before a transaction writes it; duplicate and foreign-key failures roll back every row. DOM rendering uses text nodes. CSV program labels reject control characters and leading spreadsheet formula markers.

There is no authentication, encryption at rest, authorization model, backup workflow, rate limiter, or independent security assessment. Loopback does not protect against other users or malicious software on your computer. Do not bind a reverse proxy or expose the Python service to a network. The static preview contains only a fictional snapshot and has no write API.

## Audit log: what it protects and what it does not

Every write appends hash-chained entries to `audit_log` in the same transaction (see [ARCHITECTURE.md](docs/ARCHITECTURE.md#audit-history-and-as-of-reports)). SQLite triggers make the log append-only for ordinary SQL: `UPDATE` and `DELETE` on it fail, and an insert must carry the next entry number, the previous entry's digest and a time no earlier than the previous entry. `impact-ledger verify` recomputes every digest, replays every entry and compares the result with the tables. Past reports refuse to replay a prefix that fails these checks.

This makes the ledger **tamper-evident, not tamper-proof**. A local administrator, or any program that can write the database file, can still:

- drop the triggers and then edit or delete entries (verify reports the missing triggers and the broken digests or links);
- remove an entry with an `INSERT OR REPLACE` that reuses its digest, because SQLite fires no delete trigger for a row that REPLACE removes (verify reports the gap and the broken links);
- change `sessions` or `attendance` directly without a log entry (verify reports `state_mismatch`);
- delete the newest entries and restore the tables, or rewrite the whole log with freshly computed digests. The chain alone cannot detect this; `verify --expect-head` does, if you saved the head digest somewhere the same person cannot change;
- restore an older copy of the file, replace it, or delete it;
- write any actor label, because actors are self-declared and not authenticated, and set the system clock (entry times never decrease, but they are only as accurate as the clock).

Save the head digest printed by `verify` with any report you share, for example in a grant file. Anyone holding that digest can later confirm the ledger has not been rewritten up to that entry.

## Static preview

Static publication is restricted to seven verified regular files: index.html, app.js, model.js, styles.css, favicon.svg, deterministic synthetic demo.json, and empty .nojekyll. The builder inventories existing output before writes and refuses unknown entries, symlinks, nonregular entries and source/output overlap. It never recursively deletes unknown files. Selected output symlinks are rejected; trusted ancestor aliases are resolved. Private staging and per-file atomic replacement detach hard links rather than truncating their unselected originals. Ordinary failures clean the builder's own temporaries, but a failed replacement can leave a mixture of generated versions; rerun build and verification before publication. There is no whole-directory atomicity, adversarial concurrent-path containment or power-loss guarantee.

The verification-only command compares actual bytes and never repairs/writes the selected output. It creates a separate temporary synthetic SQLite database to compute expected bytes; target reads can update access times. Its bounded JSON receipt includes hashes/counts only for the exact valid payload; controlled failures expose stable codes and known filenames, never unknown names, file values or exception paths. CI runs verification after real browser checks and before upload. Upload and same-workflow deployment require non-PR main; deployment also needs both the Python matrix and frontend job. Pages/id-token write permissions exist only on the gated deployment job. Ref-scoped concurrency keeps a skipped non-main run from cancelling main. This boundary does not detect real records in intentionally changed source fixtures; the synthetic-only input policy still applies.

## Reporting

Report a suspected issue privately through the repository owner's GitHub profile contact route. If that route is unavailable, open a minimal issue asking for a private reporting channel; do not publish exploitation details or sensitive records. No response-time or supported-version guarantee is offered.
