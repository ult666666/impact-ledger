from contextlib import closing
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from impact_ledger import audit
from impact_ledger.store import Store, ValidationError
from test_store import ATTENDANCE, SESSION_HEADER, SESSIONS


class FakeClock:
    """Deterministic UTC clock; tests move it explicitly, including backwards."""
    def __init__(self, start=datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)):
        self.now = start

    def __call__(self):
        return self.now

    def advance(self, seconds):
        self.now += timedelta(seconds=seconds)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger.db'
        self.clock = FakeClock()
        self.store = Store(self.path, clock=self.clock)

    def populated(self):
        self.store.import_csv('sessions', SESSIONS.encode(), actor='importer')
        self.clock.advance(60)
        self.store.import_csv('attendance', ATTENDANCE.encode(), actor='importer')
        self.clock.advance(60)
        return self.store

    def log(self):
        with closing(sqlite3.connect(self.path)) as connection:
            return audit.entries(connection)

    def raw(self, *statements):
        """A local administrator editing the file directly with SQL."""
        connection = sqlite3.connect(self.path)
        try:
            for statement in statements:
                connection.execute(statement)
            connection.commit()
        finally:
            connection.close()

    def problems(self, **options):
        return [(p['code'], p['entry']) for p in self.store.verify(**options)['problems']]

    def test_every_write_records_actor_time_entity_values_and_batch(self):
        self.populated()
        self.store.update_session('s2', actor='analyst', actual='80.25')
        self.store.update_attendance('a4', actor='analyst', participant_id='p9')
        self.store.delete_attendance('a3', actor='analyst')
        self.store.delete_session('s4', actor='analyst')
        log = self.log()
        self.assertEqual([(e['batch_kind'], e['operation'], e['entity']) for e in log[-4:]],
                         [('update', 'update', 'session'), ('update', 'update', 'attendance'),
                          ('delete', 'delete', 'attendance'), ('delete', 'delete', 'session')])
        self.assertEqual(len(log), 4 + 4 + 4)
        first = log[0]
        self.assertEqual((first['actor'], first['batch_id'], first['recorded_at'], first['entity_id']), ('importer', 'B000001', '2026-10-01T12:00:00.000000Z', 's1'))
        self.assertIsNone(first['before'])
        self.assertEqual(json.loads(first['after']), {'session_id': 's1', 'program': 'Learning Lab', 'session_date': '2026-01-10',
                                                      'duration_hundredths': 150, 'budget_cents': 10010, 'actual_cents': 8005})
        update = log[8]
        self.assertEqual((json.loads(update['before'])['actual_cents'], json.loads(update['after'])['actual_cents']), (7500, 8025))
        self.assertEqual(update['actor'], 'analyst')
        self.assertIsNone(log[-1]['after'])
        self.assertEqual({e['batch_id'] for e in log[4:8]}, {'B000005'})
        self.assertEqual(log[1]['prev_hash'], log[0]['entry_hash'])
        report = self.store.verify()
        self.assertTrue(report['valid'], report['problems'])
        self.assertEqual((report['entries'], report['batches'], report['head']['hash']), (12, 6, log[-1]['entry_hash']))

    def test_rejected_writes_record_nothing(self):
        self.populated()
        before = len(self.log())
        for action in [lambda: self.store.update_session('missing', actual='1'),
                       lambda: self.store.update_session('s1', program='Learning Lab'),
                       lambda: self.store.delete_session('s1'),
                       lambda: self.store.update_attendance('a1', participant_id='p2'),
                       lambda: self.store.update_attendance('a1', session_id='nope'),
                       lambda: self.store.import_csv('sessions', SESSIONS.encode()),
                       lambda: self.store.update_session('s1', actor=' padded ', actual='1')]:
            with self.assertRaises(ValidationError):
                action()
        self.assertEqual(len(self.log()), before)
        self.assertTrue(self.store.verify()['valid'])

    def test_triggers_block_update_delete_replace_and_out_of_order_inserts(self):
        self.populated()
        entry = self.log()[1]
        attempts = [
            "UPDATE audit_log SET actor = 'someone else' WHERE seq = 2",
            'DELETE FROM audit_log WHERE seq = 2',
            'DELETE FROM audit_log',
            'INSERT OR REPLACE INTO audit_log SELECT * FROM audit_log WHERE seq = 2',
            "INSERT INTO audit_log SELECT * FROM audit_log WHERE seq = 2 ON CONFLICT(seq) DO UPDATE SET actor = 'x'",
            f"INSERT INTO audit_log VALUES (99, '2026-10-02T00:00:00.000000Z', 'x', 'B000099', 'update', NULL, 'delete', 'session', 's1', '{{}}', NULL, '{entry['entry_hash']}', 'f')",
        ]
        # Each insert breaks exactly one rule of the chain trigger: sequence, link or time order.
        last = self.log()[-1]
        for seq, previous, recorded_at in [(last['seq'] + 2, last['entry_hash'], last['recorded_at']),
                                           (last['seq'] + 1, entry['entry_hash'], last['recorded_at']),
                                           (last['seq'] + 1, last['entry_hash'], '2000-01-01T00:00:00.000000Z')]:
            attempts.append(f"INSERT INTO audit_log VALUES ({seq}, '{recorded_at}', 'x', 'B{seq:06d}', 'delete', NULL, 'delete', 'attendance', 'a1', '{{}}', NULL, '{previous}', 'forged-{seq}')")
        for statement in attempts:
            with self.subTest(statement=statement[:40]), self.assertRaises(sqlite3.DatabaseError):
                self.raw(statement)
        self.assertEqual(self.log()[1], entry)
        self.assertTrue(self.store.verify()['valid'])

    def test_verify_detects_an_edited_entry_after_triggers_are_dropped(self):
        self.populated()
        self.raw('DROP TRIGGER audit_log_no_update', "UPDATE audit_log SET after = replace(after, '8005', '9005') WHERE seq = 1")
        self.assertEqual(self.problems()[:2], [('protection_removed', None), ('hash_mismatch', 1)])
        self.assertFalse(self.store.verify()['valid'])

    def test_verify_detects_a_deleted_entry(self):
        self.populated()
        self.raw('DROP TRIGGER audit_log_no_delete', 'DELETE FROM audit_log WHERE seq = 3')
        codes = self.problems()
        self.assertIn(('sequence_gap', 4), codes)
        self.assertIn(('chain_break', 4), codes)

    def test_verify_detects_reordered_entries(self):
        self.populated()
        # Exchange the positions of entries 2 and 3.
        self.raw('DROP TRIGGER audit_log_no_update', 'UPDATE audit_log SET seq = 1000 WHERE seq = 2',
                 'UPDATE audit_log SET seq = 2 WHERE seq = 3', 'UPDATE audit_log SET seq = 3 WHERE seq = 1000')
        codes = {code for code, _ in self.problems()}
        self.assertTrue({'chain_break', 'hash_mismatch'} <= codes, codes)

    def test_verify_detects_table_edits_that_bypass_the_log(self):
        self.populated()
        self.raw('UPDATE sessions SET actual_cents = 1 WHERE session_id = \'s1\'')
        self.assertEqual(self.problems(), [('state_mismatch', None)])
        self.raw("INSERT INTO attendance VALUES ('ghost', 's1', 'p99')")
        self.assertEqual([code for code, _ in self.problems()], ['state_mismatch', 'state_mismatch'])

    def test_a_rewritten_chain_needs_a_saved_head_to_be_detected(self):
        self.populated()
        self.store.update_session('s1', actual='1.00')
        saved = self.store.verify()['head']['hash']  # kept outside the ledger, for example in a grant file
        # Truncate the newest batch and restore the table: the remaining chain is self-consistent.
        self.raw('DROP TRIGGER audit_log_no_delete', 'DELETE FROM audit_log WHERE seq = 9',
                 "UPDATE sessions SET actual_cents = 8005 WHERE session_id = 's1'")
        self.assertEqual(self.problems(), [('protection_removed', None)])
        self.assertIn(('head_mismatch', 8), self.problems(expect_head=saved))
        # Rewrite an early value and recompute every digest after it.
        connection = sqlite3.connect(self.path)
        log = audit.entries(connection)
        log[0]['after'] = log[0]['after'].replace('8005', '7005')
        previous = audit.GENESIS
        connection.execute('DROP TRIGGER IF EXISTS audit_log_no_update')
        for entry in log:
            entry['prev_hash'] = previous
            entry['entry_hash'] = previous = audit.entry_hash(entry)
            connection.execute('UPDATE audit_log SET after = ?, prev_hash = ?, entry_hash = ? WHERE seq = ?', (entry['after'], entry['prev_hash'], entry['entry_hash'], entry['seq']))
        connection.execute("UPDATE sessions SET actual_cents = 7005 WHERE session_id = 's1'")
        connection.commit()
        connection.close()
        self.assertEqual({code for code, _ in self.problems()}, {'protection_removed'})
        self.assertIn(('head_mismatch', 8), self.problems(expect_head=saved))

    def test_forged_entries_with_valid_digests_still_fail_replay(self):
        self.populated()
        connection = sqlite3.connect(self.path)
        last = audit.entries(connection)[-1]
        forged = {'seq': last['seq'] + 1, 'recorded_at': last['recorded_at'], 'actor': 'x', 'batch_id': f"B{last['seq'] + 1:06d}",
                  'batch_kind': 'delete', 'reverts': None, 'operation': 'delete', 'entity': 'session', 'entity_id': 's1',
                  'before': audit.canonical({'session_id': 's1', 'program': 'Other', 'session_date': '2026-01-10',
                                             'duration_hundredths': 150, 'budget_cents': 10010, 'actual_cents': 8005}),
                  'after': None, 'prev_hash': last['entry_hash']}
        forged['entry_hash'] = audit.entry_hash(forged)
        connection.execute(f'INSERT INTO audit_log ({",".join(audit.COLUMNS)}) VALUES ({",".join("?" * 13)})', [forged[c] for c in audit.COLUMNS])
        connection.commit()
        connection.close()
        self.assertEqual(self.problems(), [('invalid_transition', 9)])
        with self.assertRaisesRegex(ValidationError, 'entry 9'):
            self.store.summary(as_of_entry=9)
        self.assertEqual(self.store.summary(as_of_entry=8)['totals']['sessions'], 4)

    def test_past_reports_refuse_a_prefix_that_fails_verification(self):
        self.populated()
        self.raw('DROP TRIGGER audit_log_no_update', "UPDATE audit_log SET actor = 'x' WHERE seq = 2")
        with self.assertRaisesRegex(ValidationError, 'entry 2 \\(hash_mismatch\\)'):
            self.store.summary(as_of_entry=4)
        self.assertEqual(self.store.summary(as_of_entry=1)['totals']['sessions'], 1)
        self.assertEqual(self.store.summary()['totals']['sessions'], 4)

    def test_timestamps_never_decrease_when_the_clock_does(self):
        self.store.import_csv('sessions', SESSIONS.encode())
        self.clock.advance(-3600)
        self.store.update_session('s1', actual='1.00')
        log = self.log()
        self.assertEqual(log[-1]['recorded_at'], log[0]['recorded_at'])
        self.assertTrue(self.store.verify()['valid'])

    def test_undo_import_appends_a_compensating_batch_and_keeps_history(self):
        self.populated()
        with self.assertRaisesRegex(ValidationError, 'attendance record'):
            self.store.undo_import('B000001')
        undone = self.store.undo_import('B000005', actor='analyst')
        self.assertEqual(undone, {'batch_id': 'B000009', 'reverts': 'B000005', 'deleted': 4, 'entity': 'attendance'})
        self.assertEqual(self.store.summary()['totals']['attendance'], 0)
        self.assertEqual(self.store.summary(as_of_entry=8)['totals']['attendance'], 4)
        log = self.log()
        self.assertEqual(len(log), 12)
        self.assertEqual({(e['operation'], e['reverts'], e['batch_kind']) for e in log[8:]}, {('delete', 'B000005', 'undo')})
        with self.assertRaisesRegex(ValidationError, 'already undone by B000009'):
            self.store.undo_import('B000005')
        self.store.update_session('s2', actual='1.00')
        with self.assertRaisesRegex(ValidationError, 'changed or was deleted'):
            self.store.undo_import('B000001')
        with self.assertRaisesRegex(ValidationError, 'Only CSV import'):
            self.store.undo_import('B000013')
        with self.assertRaisesRegex(ValidationError, 'No batch'):
            self.store.undo_import('B999999')
        history = self.store.history()
        self.assertEqual([b['batch_id'] for b in history['batches']], ['B000013', 'B000009', 'B000005', 'B000001'])
        self.assertEqual(history['batches'][2]['undone_by'], 'B000009')
        self.assertTrue(self.store.verify()['valid'])

    def test_undo_refuses_rows_touched_since_the_import_even_when_values_match(self):
        # Comparing values alone cannot see these changes: each row ends up
        # identical to what the import wrote.
        self.store.import_csv('sessions', SESSIONS.encode())  # B000001: s1-s4
        self.store.delete_session('s4')
        again = self.store.import_csv('sessions', (SESSION_HEADER + 's4,Empty Session,2026-02-21,1,30,0\n').encode())
        with self.assertRaisesRegex(ValidationError, 'Session s4 changed or was deleted'):
            self.store.undo_import('B000001')  # Would delete the s4 that the later import created.
        self.assertEqual(self.store.summary()['totals']['sessions'], 4)
        self.assertEqual(self.store.undo_import(again['batch_id'])['deleted'], 1)
        extra = self.store.import_csv('sessions', (SESSION_HEADER + 's5,Learning Lab,2026-03-01,1,10,10\n').encode())
        self.store.update_session('s5', actual='11.00')
        self.store.update_session('s5', actual='10.00')  # Changed and changed back.
        with self.assertRaisesRegex(ValidationError, 'Session s5 changed or was deleted'):
            self.store.undo_import(extra['batch_id'])
        self.assertTrue(self.store.verify()['valid'])

    def test_verify_reports_an_entry_removed_by_insert_or_replace(self):
        # REPLACE conflict resolution deletes rows without firing delete
        # triggers, so the triggers cannot stop this; verify must catch it.
        self.populated()
        last, first = self.log()[-1], self.log()[0]
        self.raw(f"INSERT OR REPLACE INTO audit_log VALUES ({last['seq'] + 1}, '{last['recorded_at']}', 'x', "
                 f"'B{last['seq'] + 1:06d}', 'delete', NULL, 'delete', 'session', 's1', '{{}}', NULL, "
                 f"'{last['entry_hash']}', '{first['entry_hash']}')")
        self.assertNotIn(1, [entry['seq'] for entry in self.log()])
        self.assertIn(('sequence_gap', 2), self.problems())
        self.assertFalse(self.store.verify()['valid'])

    def test_schema_zero_ledgers_gain_a_baseline_batch(self):
        legacy = Path(self.temp.name) / 'legacy.db'
        connection = sqlite3.connect(legacy)
        connection.executescript('''
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY, program TEXT NOT NULL, session_date TEXT NOT NULL,
                duration_hundredths INTEGER NOT NULL, budget_cents INTEGER NOT NULL, actual_cents INTEGER NOT NULL);
            CREATE TABLE attendance (attendance_id TEXT PRIMARY KEY, session_id TEXT NOT NULL REFERENCES sessions(session_id),
                participant_id TEXT NOT NULL, UNIQUE(session_id, participant_id));
            INSERT INTO sessions VALUES ('old1', 'Lab', '2026-05-01', 100, 500, 400), ('old2', 'Lab', '2026-05-02', 100, 0, 0);
            INSERT INTO attendance VALUES ('olda', 'old1', 'p1');''')
        connection.commit()
        connection.close()
        self.assertFalse(Store.open_existing(legacy).verify()['valid'])
        store = Store(legacy, clock=self.clock)
        report = store.verify()
        self.assertTrue(report['valid'], report['problems'])
        self.assertEqual((report['entries'], store.history()['batches'][0]['kind']), (3, 'baseline'))
        self.assertEqual(store.summary(as_of_entry=0)['totals']['sessions'], 0)
        self.assertEqual(store.summary(as_of_entry=3)['totals'], store.summary()['totals'])
        Store(legacy, clock=self.clock)
        self.assertEqual(store.verify()['entries'], 3)
        with closing(sqlite3.connect(legacy)) as connection:
            self.assertEqual(connection.execute('PRAGMA user_version').fetchone()[0], 1)
            connection.execute('PRAGMA user_version = 2')
            connection.commit()
        with self.assertRaisesRegex(ValidationError, 'schema version 2'):
            Store(legacy)


if __name__ == '__main__':
    unittest.main()
