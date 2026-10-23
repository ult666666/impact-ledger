"""Behavior contracts: preview must diagnose without changing or reserving data."""
from pathlib import Path
from contextlib import closing, contextmanager
import sqlite3
import tempfile
import unittest

from impact_ledger.store import Store, ValidationError
from test_store import SESSION_HEADER, ATTENDANCE_HEADER, SESSIONS, ATTENDANCE


class PreviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger.db'
        self.store = Store(self.path)

    def test_invalid_kind_is_controlled_before_accessing_database(self):
        self.store.path = Path(self.temp.name) / 'nonexistent' / 'ledger.db'
        for operation in [self.store.preview_csv, self.store.import_csv]:
            with self.subTest(operation=operation.__name__), self.assertRaisesRegex(ValidationError, 'kind must be sessions or attendance'):
                operation('unknown', b'anything')
        self.assertFalse(self.store.path.parent.exists())

    def test_valid_bom_quoted_csv_is_advisory_and_does_not_write(self):
        # A preview implemented with inserts or schema initialization would change these.
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute("CREATE TRIGGER forbid_preview_write BEFORE INSERT ON sessions BEGIN SELECT RAISE(ABORT, 'writes forbidden'); END")
            connection.commit()
        before = (self.path.read_bytes(), self.path.stat().st_mtime_ns, list(Path(self.temp.name).iterdir()))
        result = self.store.preview_csv('sessions', ('\ufeff' + SESSION_HEADER + 's1,"Lab, ""社区""",2026-01-01,0.01,10000000,0\r\n').encode())
        self.assertEqual(result, {'kind': 'sessions', 'valid': True, 'rows': 1, 'errors': [], 'errors_truncated': False, 'errors_total': 0})
        self.assertEqual(before, (self.path.read_bytes(), self.path.stat().st_mtime_ns, list(Path(self.temp.name).iterdir())))
        self.assertEqual(self.store.metadata()['sessions'], 0)

    def test_reports_multiple_bad_fields_with_physical_csv_start_lines(self):
        payload = SESSION_HEADER + 'bad!,"Line\nBreak",2026-02-30,0,NaN,10000000.01\nlast,Lab,2026-01-01,1,1\n'
        result = self.store.preview_csv('sessions', payload.encode())
        self.assertFalse(result['valid'])
        self.assertEqual(result['rows'], 2)
        self.assertEqual([(e['row'], e['field'], e['code']) for e in result['errors']], [
            (2, 'session_id', 'invalid_value'), (2, 'program', 'invalid_value'),
            (2, 'session_date', 'invalid_value'), (2, 'duration_hours', 'invalid_value'),
            (2, 'budget', 'invalid_value'), (2, 'actual', 'invalid_value'), (4, None, 'columns')])
        self.assertNotIn('Line\nBreak', str(result))
        with self.assertRaisesRegex(ValidationError, 'Row 2:'):
            self.store.import_csv('sessions', payload.encode())
        self.assertEqual(self.store.metadata()['sessions'], 0)

    def test_file_errors_are_bounded_and_have_no_row_or_field(self):
        for payload, code in [(b'', 'headers'), (b'wrong\n', 'headers'), (b'\xff', 'encoding'),
                              (SESSION_HEADER.encode(), 'empty'), (b'x' * (1024 * 1024 + 1), 'too_large'),
                              ((SESSION_HEADER + 's1,"unterminated\n').encode(), 'malformed_csv')]:
            with self.subTest(code=code):
                result = self.store.preview_csv('sessions', payload)
                self.assertFalse(result['valid'])
                error = result['errors'][-1]
                self.assertEqual((error['row'], error['field'], error['code']), (None, None, code))
                with self.assertRaises(ValidationError):
                    self.store.import_csv('sessions', payload)
        with self.assertRaises(ValidationError):
            self.store.preview_csv('unknown', b'anything')

    def test_rejects_5001_rows_and_caps_displayed_errors(self):
        payload = (SESSION_HEADER + ''.join(f's{i},Lab,2026-01-01,1,1,1\n' for i in range(5001))).encode()
        result = self.store.preview_csv('sessions', payload)
        self.assertFalse(result['valid'])
        self.assertEqual(result['errors'][-1]['code'], 'row_limit')
        at_limit = payload[:payload.rfind(b's5000,')]
        accepted = self.store.preview_csv('sessions', at_limit)
        self.assertTrue(accepted['valid'])
        self.assertEqual(accepted['rows'], 5000)
        bad = (SESSION_HEADER + ''.join(f's{i},Lab,2026-02-30,1,1,1\n' for i in range(102))).encode()
        result = self.store.preview_csv('sessions', bad)
        self.assertEqual((len(result['errors']), result['errors_total'], result['errors_truncated']), (100, 102, True))
        self.assertEqual((result['errors'][0]['row'], result['errors'][-1]['row']), (2, 101))
        stopped = self.store.preview_csv('sessions', bad + b'\"unterminated\n')
        self.assertEqual((len(stopped['errors']), stopped['errors_total'], stopped['errors_truncated']), (100, 103, True))
        self.assertEqual(stopped['errors'][-1]['code'], 'malformed_csv')
        self.assertIsNone(stopped['errors'][-1]['row'])

    def test_exact_bounds_match_real_import_and_never_normalize_input(self):
        for field, bad in [('duration_hours', '0'), ('duration_hours', '24.01'), ('budget', '10000000.01'),
                           ('actual', '0.001'), ('budget', '01'), ('budget', '1e2'), ('program', ' Lab'),
                           ('program', '=SUM(A1)'), ('session_id', ' s1'), ('session_date', '2026-1-01')]:
            values = ['s1', 'Lab', '2026-01-01', '24', '0', '10000000']
            values[SESSION_HEADER.strip().split(',').index(field)] = bad
            payload = (SESSION_HEADER + ','.join(values) + '\n').encode()
            with self.subTest(field=field, bad=bad):
                result = self.store.preview_csv('sessions', payload)
                self.assertEqual(result['errors'][0]['field'], field)
                with self.assertRaises(ValidationError):
                    self.store.import_csv('sessions', payload)
        payload = (SESSION_HEADER + 's1,Lab,2026-01-01,24,0,10000000\n').encode()
        self.assertTrue(self.store.preview_csv('sessions', payload)['valid'])
        self.assertEqual(self.store.import_csv('sessions', payload)['imported'], 1)

    def test_duplicate_ids_pairs_and_references_cover_file_and_database(self):
        self.store.import_csv('sessions', SESSIONS.encode())
        self.store.import_csv('attendance', ATTENDANCE.encode())
        result = self.store.preview_csv('sessions', (SESSION_HEADER + 's1,Lab,2026-01-01,1,1,1\ns5,Lab,2026-01-01,1,1,1\ns5,Lab,2026-01-01,1,1,1\n').encode())
        self.assertEqual([(e['row'], e['field'], e['code']) for e in result['errors']], [(2, 'session_id', 'duplicate_id'), (4, 'session_id', 'duplicate_id')])
        result = self.store.preview_csv('attendance', (ATTENDANCE_HEADER + 'a1,s1,p1\na5,missing,p5\na6,s2,p6\na6,s2,p6\n').encode())
        self.assertEqual([(e['row'], e['field'], e['code']) for e in result['errors']], [
            (2, 'attendance_id', 'duplicate_id'), (2, 'participant_id', 'duplicate_pair'),
            (3, 'session_id', 'missing_session'), (5, 'attendance_id', 'duplicate_id'), (5, 'participant_id', 'duplicate_pair')])

    def test_database_checks_keep_one_snapshot_while_another_connection_commits(self):
        with closing(sqlite3.connect(self.path)) as connection:
            connection.execute('PRAGMA journal_mode=WAL')
        self.store.import_csv('sessions', (SESSION_HEADER + 's1,Lab,2026-01-01,1,1,1\n').encode())
        writer = Store(self.path)
        statements = []

        class ObservedStore(Store):
            @contextmanager
            def _read_connection(inner):
                with super()._read_connection() as connection:
                    def observe(sql):
                        statements.append(sql)
                        if sql.startswith('SELECT 1 FROM attendance WHERE attendance_id') and len([q for q in statements if q.startswith('SELECT 1 FROM attendance WHERE attendance_id')]) == 2:
                            writer.import_csv('sessions', (SESSION_HEADER + 'late,Lab,2026-01-01,1,1,1\n').encode())
                    connection.set_trace_callback(observe)
                    yield connection

        result = ObservedStore.open_existing(self.path).preview_csv('attendance',
            (ATTENDANCE_HEADER + 'a1,s1,p1\na2,late,p2\n').encode())
        self.assertEqual([(e['row'], e['code']) for e in result['errors']], [(3, 'missing_session')])
        self.assertEqual(writer.metadata()['sessions'], 2)
        self.assertTrue(all(q.startswith(('SELECT', 'BEGIN')) for q in statements))
        # The next preview sees the commit, without reusing a prior result.
        self.assertTrue(self.store.preview_csv('attendance', (ATTENDANCE_HEADER + 'a2,late,p2\n').encode())['valid'])

    def test_preview_never_reserves_ids_and_import_revalidates_current_state_atomically(self):
        payload = (SESSION_HEADER + 'first,Lab,2026-01-01,1,1,1\nsecond,Lab,2026-01-01,1,1,1\n').encode()
        self.assertTrue(self.store.preview_csv('sessions', payload)['valid'])
        concurrent = Store(self.path)
        concurrent.import_csv('sessions', (SESSION_HEADER + 'second,Lab,2026-01-01,1,1,1\n').encode())
        with self.assertRaisesRegex(ValidationError, 'Row 3:.*already exists'):
            self.store.import_csv('sessions', payload)
        self.assertEqual([row['session_id'] for row in self.store.snapshot()['sessions']], ['second'])


if __name__ == '__main__':
    unittest.main()
