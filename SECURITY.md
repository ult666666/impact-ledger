# Security policy

Impact Ledger is an educational local demo for synthetic records. Do not use it for real participant information, confidential records, grant reporting, or financial decisions.

The Python server binds only `127.0.0.1`. It checks the Host header, rejects cross-origin imports, sends no CORS permissions, caps request bodies at 1 MiB, times out reads, and uses parameterized SQLite queries. Imports validate the complete file before a transaction writes it; duplicate and foreign-key failures roll back every row. DOM rendering uses text nodes. CSV program labels reject control characters and leading spreadsheet formula markers.

There is no authentication, encryption at rest, authorization model, audit trail, backup workflow, rate limiter, or independent security assessment. Loopback does not protect against other users or malicious software on your computer. Do not bind a reverse proxy or expose the Python service to a network. The static preview contains only a fictional snapshot and has no write API.

Report a suspected issue privately through the repository owner's GitHub profile contact route. If that route is unavailable, open a minimal issue asking for a private reporting channel; do not publish exploitation details or sensitive records. No response-time or supported-version guarantee is offered.
