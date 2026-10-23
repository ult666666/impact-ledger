"""Shared hand-derived comparison oracles consumed by Python and Node."""
import csv
import io
import json
from pathlib import Path
import tempfile
import sqlite3
import unittest
from impact_ledger.store import Store, ValidationError

FIXTURE = json.loads((Path(__file__).parent / 'fixtures/comparison.json').read_text())


class ComparisonTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'comparison.db')
        for kind, header in [('sessions', ['session_id', 'program', 'session_date', 'duration_hours', 'budget', 'actual']), ('attendance', ['attendance_id', 'session_id', 'participant_id'])]:
            output = io.StringIO(newline='')
            writer = csv.writer(output)
            writer.writerow(header)
            for row in FIXTURE['snapshot']['sessions']:
                if kind == 'sessions':
                    writer.writerow([row['session_id'], row['program'], row['session_date'], f"{row['duration_hundredths'] / 100:.2f}", f"{row['budget_cents'] / 100:.2f}", f"{row['actual_cents'] / 100:.2f}"])
                else:
                    for record in row['attendance_records']:
                        writer.writerow([record['attendance_id'], row['session_id'], record['participant_id']])
            self.store.import_csv(kind, output.getvalue().encode())

    def test_shared_calendar_and_accounting_oracles(self):
        for case in FIXTURE['cases']:
            with self.subTest(case=case['name']):
                self.assertEqual(self.store.comparison(**case['filters']), case['expected'])

    def test_shared_invalid_ranges_are_controlled_validation_errors(self):
        for filters in FIXTURE['invalid_filters']:
            with self.subTest(filters=filters), self.assertRaises(ValidationError):
                self.store.comparison(**filters)

    def test_deltas_subtract_integer_cents_before_json_conversion(self):
        with sqlite3.connect(self.store.path) as connection:
            connection.executemany('INSERT INTO sessions VALUES (?,?,?,?,?,?)', [
                ('large-before', 'Large', '2026-01-01', 100, 9007199254740962, 0),
                ('large-now', 'Large', '2026-01-02', 100, 9007199254740963, 0),
            ])
        connection.close()
        self.assertEqual(self.store.comparison('2026-01-02', '2026-01-02', 'Large')['deltas']['budget'], .01)

    def test_unbounded_summary_remains_independently_available(self):
        self.assertEqual(self.store.summary()['totals']['sessions'], 5)
