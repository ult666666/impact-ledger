import csv
import io
from pathlib import Path
import tempfile
import unittest

from impact_ledger.store import Store, ValidationError

SESSION_HEADER = 'session_id,program,session_date,duration_hours,budget,actual\n'
ATTENDANCE_HEADER = 'attendance_id,session_id,participant_id\n'
SESSIONS = SESSION_HEADER + 's1,Learning Lab,2026-01-10,1.5,100.10,80.05\ns2,Learning Lab,2026-02-10,2,50,75\ns3,Community Kitchen,2026-02-20,3,0,20\ns4,Empty Session,2026-02-21,1,30,0\n'
ATTENDANCE = ATTENDANCE_HEADER + 'a1,s1,p1\na2,s1,p2\na3,s2,p1\na4,s3,p3\n'


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'ledger.db')

    def populated(self):
        self.store.import_csv('sessions', SESSIONS.encode())
        self.store.import_csv('attendance', ATTENDANCE.encode())
        return self.store

    def test_counts_people_once_and_costs_once_per_session(self):
        summary = self.populated().summary()
        self.assertEqual(summary['totals'], {
            'sessions': 4, 'unique_participants': 3, 'attendance': 4,
            'participant_hours': 8, 'session_hours': 7.5,
            'budget': 180.1, 'actual': 175.05, 'variance': -5.05,
            'variance_percent': -2.8, 'attendance_per_participant': 1.33,
        })
        learning = next(p for p in summary['programs'] if p['program'] == 'Learning Lab')
        self.assertEqual((learning['unique_participants'], learning['attendance'], learning['participant_hours']), (2, 3, 5))
        self.assertEqual(summary['monthly'][0]['month'], '2026-01')
        self.assertEqual(summary['monthly'][0]['attendance'], 2)
        empty = next(s for s in summary['sessions'] if s['session_id'] == 's4')
        self.assertEqual(empty['attendance'], 0)

    def test_inclusive_date_and_program_filters_share_denominator(self):
        summary = self.populated().summary('2026-02-10', '2026-02-10', 'Learning Lab')
        self.assertEqual(summary['totals']['attendance'], 1)
        self.assertEqual(summary['totals']['unique_participants'], 1)
        self.assertEqual(summary['totals']['budget'], 50)
        self.assertEqual(summary['totals']['variance_percent'], 50)
        self.assertEqual(len(summary['sessions']), 1)

    def test_empty_filter_and_zero_budget_do_not_invent_rates(self):
        store = self.populated()
        summary = store.summary(program='Missing')
        self.assertEqual(summary['totals']['attendance'], 0)
        self.assertEqual(summary['totals']['budget'], 0)
        self.assertIsNone(summary['totals']['variance_percent'])
        self.assertIsNone(summary['totals']['attendance_per_participant'])
        self.assertEqual(summary['programs'], [])
        self.assertIsNone(store.summary(program='Community Kitchen')['totals']['variance_percent'])

    def test_bad_date_filters_are_rejected(self):
        for args in [('0000-01-01', None), ('2026-2-01', None), ('2026-02-30', None), ('2026-03-01', '2026-02-01')]:
            with self.subTest(args=args), self.assertRaises(ValidationError):
                self.store.summary(*args)

    def test_money_uses_exact_decimal_arithmetic(self):
        self.store.import_csv('sessions', (SESSION_HEADER + 's1,Exact,2026-01-01,0.1,0.10,0.20\ns2,Exact,2026-01-01,0.2,0.20,0.30\n').encode())
        totals = self.store.summary()['totals']
        self.assertEqual((totals['budget'], totals['actual'], totals['variance']), (0.3, 0.5, 0.2))
        self.assertEqual(totals['session_hours'], 0.3)

    def test_invalid_rows_leave_no_partial_import(self):
        for bad in ['s2,Lab,2026-02-30,1,1,1', 's2,Lab,2026-01-01,1,NaN,1', 's2,Lab,2026-01-01,1,-1,1', 's2,Lab,2026-01-01,Infinity,1,1', 's2,Lab,2026-01-01,1,1,0.001', 's2,Lab,2026-01-01,0,1,1', 's2,Lab,2026-01-01,25,1,1', 's2,Lab,2026-01-01,1,10000000.01,1', 's2,=CMD(),2026-01-01,1,1,1', 's2,Lab,2026-1-01,1,1,1']:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.store.import_csv('sessions', (SESSION_HEADER + 's1,Good,2026-01-01,1,1,1\n' + bad + '\n').encode())
            self.assertEqual(self.store.summary()['totals']['sessions'], 0)

    def test_duplicate_ids_inside_import_are_atomic(self):
        with self.assertRaises(ValidationError):
            self.store.import_csv('sessions', (SESSION_HEADER + 's1,Lab,2026-01-01,1,1,1\ns1,Lab,2026-01-02,1,1,1\n').encode())
        self.assertEqual(self.store.summary()['totals']['sessions'], 0)

    def test_existing_duplicate_id_rolls_back_other_rows(self):
        self.populated()
        with self.assertRaises(ValidationError):
            self.store.import_csv('sessions', (SESSION_HEADER + 's5,Lab,2026-01-01,1,1,1\ns1,Lab,2026-01-02,1,1,1\n').encode())
        self.assertEqual(self.store.summary()['totals']['sessions'], 4)

    def test_attendance_foreign_keys_and_duplicate_people_are_atomic(self):
        self.populated()
        for bad in ['a6,missing,p6', 'a6,s1,p1', 'a1,s2,p6']:
            with self.subTest(bad=bad), self.assertRaises(ValidationError):
                self.store.import_csv('attendance', (ATTENDANCE_HEADER + 'a5,s2,p5\n' + bad + '\n').encode())
            self.assertEqual(self.store.summary()['totals']['attendance'], 4)

    def test_strict_headers_rows_unicode_and_limits(self):
        invalid = [b'', b'wrong,headers\na,b\n', SESSION_HEADER.encode(), (SESSION_HEADER + 's1,Lab,2026-01-01,1,1,1,extra\n').encode(), (SESSION_HEADER + 's1,Lab,2026-01-01,1,1\n').encode(), b'\xff', b'x' * (1024 * 1024 + 1), (SESSION_HEADER + 's1,"Lab\nBreak",2026-01-01,1,1,1\n').encode(), (SESSION_HEADER + 's1,"unterminated,2026-01-01,1,1,1\n').encode()]
        for payload in invalid:
            with self.subTest(size=len(payload)), self.assertRaises(ValidationError):
                self.store.import_csv('sessions', payload)
        with self.assertRaises(ValidationError):
            self.store.import_csv('unknown', b'anything')

    def test_row_limit_rejects_whole_import(self):
        payload = SESSION_HEADER + ''.join(f's{i},Lab,2026-01-01,1,1,1\n' for i in range(5001))
        with self.assertRaises(ValidationError):
            self.store.import_csv('sessions', payload.encode())
        self.assertEqual(self.store.summary()['totals']['sessions'], 0)

    def test_hostile_markup_is_data_and_bilingual_labels_roundtrip(self):
        payload = SESSION_HEADER + 's1,<img src=x onerror=alert(1)>,2026-01-01,1,1,1\ns2,社区厨房,2026-01-02,1,1,1\n'
        self.store.import_csv('sessions', payload.encode())
        names = {row['program'] for row in self.store.summary()['programs']}
        self.assertEqual(names, {'<img src=x onerror=alert(1)>', '社区厨房'})
        self.assertIn('社区厨房', self.store.export_csv('sessions').decode())
        snapshot = self.store.snapshot()
        self.assertEqual(snapshot['sessions'][0]['attendance_records'], [])

    def test_csv_export_preserves_filtered_schema_and_roundtrips(self):
        store = self.populated()
        output = store.export_csv('sessions', start='2026-02-10', end='2026-02-10')
        rows = list(csv.DictReader(io.StringIO(output.decode())))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], {'session_id': 's2', 'program': 'Learning Lab', 'session_date': '2026-02-10', 'duration_hours': '2.00', 'budget': '50.00', 'actual': '75.00'})
        attendance = list(csv.DictReader(io.StringIO(store.export_csv('attendance', program='Learning Lab').decode())))
        self.assertEqual([row['attendance_id'] for row in attendance], ['a1', 'a2', 'a3'])

    def test_seed_is_deterministic_and_refuses_nonempty_database(self):
        self.assertGreater(self.store.seed_demo()['sessions'], 20)
        first = self.store.summary()
        self.assertGreater(first['totals']['unique_participants'], 20)
        with self.assertRaises(ValidationError):
            self.store.seed_demo()
        second_store = Store(Path(self.temp.name) / 'other.db')
        second_store.seed_demo()
        self.assertEqual(first, second_store.summary())
        self.assertTrue(self.store.metadata()['synthetic'])


if __name__ == '__main__':
    unittest.main()
