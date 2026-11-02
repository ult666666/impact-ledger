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
    parser.add_argument('--actor', default='local-cli', help='Label recorded in the audit log for writes (default: local-cli; not authenticated)')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('init', help='Create an empty synthetic-data ledger')
    commands.add_parser('seed', help='Seed an empty ledger with deterministic fictional records')
    serve = commands.add_parser('serve', help='Serve the dashboard on 127.0.0.1 only')
    serve.add_argument('--port', type=int, default=8765)
    for command in ['import', 'preview-import']:
        load = commands.add_parser(command, help='Atomically append CSV' if command == 'import' else 'Read-only CSV diagnostics against an existing initialized ledger')
        load.add_argument('kind', choices=['sessions', 'attendance'])
        load.add_argument('file', type=Path)
    for command in ['summary', 'comparison', 'export']:
        subparser = commands.add_parser(command)
        if command == 'export':
            subparser.add_argument('kind', choices=['sessions', 'attendance'])
            subparser.add_argument('--output', type=Path, help='CSV file (default: stdout)')
        subparser.add_argument('--start')
        subparser.add_argument('--end')
        subparser.add_argument('--program')
        as_of = subparser.add_mutually_exclusive_group()
        as_of.add_argument('--as-of', help='Report the ledger as recorded at this UTC time (YYYY-MM-DD means the end of that day)')
        as_of.add_argument('--as-of-entry', type=int, help='Report the ledger after this audit entry number')
    history = commands.add_parser('history', help='List audit batches, newest first')
    history.add_argument('--limit', type=int, default=20)
    verify = commands.add_parser('verify', help='Check the audit chain, its protections and the tables; exit 1 on any problem')
    verify.add_argument('--expect-head', help='SHA-256 of the latest entry saved from an earlier verify, to detect a truncated or rewritten log')
    undo = commands.add_parser('undo-import', help='Reverse one CSV import with a compensating batch')
    undo.add_argument('batch_id')
    update_session = commands.add_parser('update-session', help='Correct fields of one session')
    update_session.add_argument('session_id')
    for option in ['--program', '--date', '--duration', '--budget', '--actual']:
        update_session.add_argument(option)
    update_attendance = commands.add_parser('update-attendance', help='Correct the session or participant of one attendance record')
    update_attendance.add_argument('attendance_id')
    update_attendance.add_argument('--session')
    update_attendance.add_argument('--participant')
    for command, key in [('delete-session', 'session_id'), ('delete-attendance', 'attendance_id')]:
        commands.add_parser(command, help=f'Delete one {key.split("_")[0]} record with an audit entry').add_argument(key)
    args = parser.parse_args(argv)
    try:
        store = Store.open_existing(args.db) if args.command in ['preview-import', 'verify'] else Store(args.db)
        if args.command == 'init':
            result = store.metadata()
        elif args.command == 'seed':
            result = store.seed_demo(actor=args.actor if args.actor != 'local-cli' else 'seed')
        elif args.command in ['import', 'preview-import']:
            with args.file.open('rb') as source:
                payload = source.read(MAX_BYTES + 1)
            result = store.preview_csv(args.kind, payload) if args.command == 'preview-import' else store.import_csv(args.kind, payload, actor=args.actor)
        elif args.command == 'history':
            result = store.history(args.limit)
        elif args.command == 'verify':
            result = store.verify(args.expect_head)
        elif args.command == 'undo-import':
            result = store.undo_import(args.batch_id, actor=args.actor)
        elif args.command == 'update-session':
            result = store.update_session(args.session_id, actor=args.actor, program=args.program, session_date=args.date,
                                          duration_hours=args.duration, budget=args.budget, actual=args.actual)
        elif args.command == 'update-attendance':
            result = store.update_attendance(args.attendance_id, actor=args.actor, session_id=args.session, participant_id=args.participant)
        elif args.command == 'delete-session':
            result = store.delete_session(args.session_id, actor=args.actor)
        elif args.command == 'delete-attendance':
            result = store.delete_attendance(args.attendance_id, actor=args.actor)
        elif args.command in ['summary', 'comparison', 'export']:
            filters = {key: getattr(args, key) for key in ['start', 'end', 'program', 'as_of', 'as_of_entry']}
            if args.command == 'export':
                output = store.export_csv(args.kind, **filters)
                if args.output:
                    args.output.write_bytes(output)
                else:
                    sys.stdout.buffer.write(output)
                return 0
            result = store.comparison(**filters) if args.command == 'comparison' else store.summary(**filters)
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
        return 1 if args.command in ['preview-import', 'verify'] and not result['valid'] else 0
    except (ValidationError, OSError, sqlite3.Error) as exc:
        print(f'impact-ledger: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
