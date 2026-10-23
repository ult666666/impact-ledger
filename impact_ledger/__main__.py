"""Reproducible command-line entry point; no third-party runtime packages."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

from .server import create_server
from .store import MAX_BYTES, Store, ValidationError


def main(argv=None):
    parser = argparse.ArgumentParser(description='Impact Ledger — synthetic local operations dashboard')
    parser.add_argument('--db', default='.local/ledger.db', help='SQLite path (default: .local/ledger.db)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Create an empty synthetic-data ledger')
    commands.add_parser('seed', help='Seed an empty ledger with deterministic fictional records')
    serve = commands.add_parser('serve', help='Serve the dashboard on 127.0.0.1 only')
    serve.add_argument('--port', type=int, default=8765)
    load = commands.add_parser('import', help='Atomically append a validated UTF-8 CSV')
    load.add_argument('kind', choices=['sessions', 'attendance'])
    load.add_argument('file', type=Path)
    for command in ['summary', 'export']:
        subparser = commands.add_parser(command)
        if command == 'export':
            subparser.add_argument('kind', choices=['sessions', 'attendance'])
            subparser.add_argument('--output', type=Path, help='CSV file (default: stdout)')
        subparser.add_argument('--start')
        subparser.add_argument('--end')
        subparser.add_argument('--program')
    args = parser.parse_args(argv)
    try:
        store = Store(args.db)
        if args.command == 'init':
            result = store.metadata()
        elif args.command == 'seed':
            result = store.seed_demo()
        elif args.command == 'import':
            with args.file.open('rb') as source:
                result = store.import_csv(args.kind, source.read(MAX_BYTES + 1))
        elif args.command in ['summary', 'export']:
            filters = {key: getattr(args, key) for key in ['start', 'end', 'program']}
            if args.command == 'export':
                output = store.export_csv(args.kind, **filters)
                if args.output:
                    args.output.write_bytes(output)
                else:
                    sys.stdout.buffer.write(output)
                return 0
            result = store.summary(**filters)
        else:
            if not 0 <= args.port <= 65535:
                raise ValidationError('Port must be between 0 and 65535.')
            server = create_server(store, args.port)
            print(f'Impact Ledger: http://127.0.0.1:{server.server_address[1]} — SYNTHETIC DATA ONLY', flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
            finally:
                server.server_close()
            return 0
        print(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False))
        return 0
    except (ValidationError, OSError, sqlite3.Error) as exc:
        print(f'impact-ledger: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
