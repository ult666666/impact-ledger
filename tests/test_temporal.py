"""Property test: a report as of time t equals the report of the state replayed to t.

The test keeps its own model of the ledger, independent of the audit log. After
each random operation it records the model state and the operation time. For a
query time t, the expected report comes from a fresh ledger loaded with the
model state at t through ordinary CSV import, using the current-state SQL path.
"""
import copy
from contextlib import closing
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import random
import sqlite3
import tempfile
import unittest

from impact_ledger import audit
from impact_ledger.store import Store, ValidationError
from test_audit import FakeClock

PROGRAMS = ['Learning Lab', 'Community Kitchen', '社区服务']
SEQUENCES, OPERATIONS = 12, 26


def sessions_csv(state):
    lines = ['session_id,program,session_date,duration_hours,budget,actual']
    for row in sorted(state['session'].values(), key=lambda row: row['session_id']):
        lines.append(','.join([row['session_id'], row['program'], row['session_date'], f"{row['duration_hundredths'] / 100:.2f}",
                               f"{row['budget_cents'] / 100:.2f}", f"{row['actual_cents'] / 100:.2f}"]))
    return ('\n'.join(lines) + '\n').encode()


def attendance_csv(state):
    lines = ['attendance_id,session_id,participant_id']
    lines += [f"{row['attendance_id']},{row['session_id']},{row['participant_id']}" for row in sorted(state['attendance'].values(), key=lambda row: row['attendance_id'])]
    return ('\n'.join(lines) + '\n').encode()


class TemporalPropertyTests(unittest.TestCase):
    def setUp(self):
        # Hundreds of small throwaway ledgers: a RAM-backed directory, where
        # available, avoids waiting on disk syncs for every commit.
        self.temp = tempfile.TemporaryDirectory(dir='/dev/shm' if os.path.isdir('/dev/shm') else None)
        self.addCleanup(self.temp.cleanup)
        self.oracles = {}

    def oracle(self, state):
        """A fresh ledger holding exactly this state, built with ordinary imports."""
        key = (audit.canonical(state['session']), audit.canonical(state['attendance']))
        if key not in self.oracles:
            store = Store(Path(self.temp.name) / f'oracle-{len(self.oracles)}.db')
            if state['session']:
                store.import_csv('sessions', sessions_csv(state))
            if state['attendance']:
                store.import_csv('attendance', attendance_csv(state))
            self.oracles[key] = store
        return self.oracles[key]

    def run_sequence(self, seed):
        rng = random.Random(seed)
        clock = FakeClock(datetime(2026, 10, 1, tzinfo=timezone.utc))
        store = Store(Path(self.temp.name) / f'ledger-{seed}.db', clock=clock)
        state = {'session': {}, 'attendance': {}}
        imports = {}  # batch_id -> (entity, created ids)
        checkpoints = [(None, 0, copy.deepcopy(state))]
        counter = 0

        def new_session():
            nonlocal counter
            counter += 1
            return {'session_id': f's{counter}', 'program': rng.choice(PROGRAMS),
                    'session_date': (datetime(2026, 1, 1) + timedelta(days=rng.randrange(90))).date().isoformat(),
                    'duration_hundredths': rng.randrange(1, 801), 'budget_cents': rng.randrange(0, 50001), 'actual_cents': rng.randrange(0, 50001)}

        def free_pairs():
            taken = {(row['session_id'], row['participant_id']) for row in state['attendance'].values()}
            return [(sid, f'p{n}') for sid in state['session'] for n in range(1, 9) if (sid, f'p{n}') not in taken]

        for _ in range(OPERATIONS):
            clock.advance(rng.choice([0, 0, 1, 2, 3600]))
            choice = rng.random()
            expect_refusal = False
            if choice < 0.25 or not state['session']:
                rows = [new_session() for _ in range(rng.randint(1, 3))]
                result = store.import_csv('sessions', sessions_csv({'session': {r['session_id']: r for r in rows}}))
                for row in rows:
                    state['session'][row['session_id']] = row
                imports[result['batch_id']] = ('session', [r['session_id'] for r in rows])
            elif choice < 0.45 and free_pairs():
                pairs = rng.sample(free_pairs(), min(len(free_pairs()), rng.randint(1, 4)))
                rows = []
                for sid, pid in pairs:
                    counter += 1
                    rows.append({'attendance_id': f'a{counter}', 'session_id': sid, 'participant_id': pid})
                result = store.import_csv('attendance', attendance_csv({'attendance': {r['attendance_id']: r for r in rows}}))
                for row in rows:
                    state['attendance'][row['attendance_id']] = row
                imports[result['batch_id']] = ('attendance', [r['attendance_id'] for r in rows])
            elif choice < 0.6:
                key = rng.choice(sorted(state['session']))
                field = rng.choice(['program', 'session_date', 'duration_hundredths', 'budget_cents', 'actual_cents'])
                replacement = new_session()[field]
                if replacement == state['session'][key][field]:
                    expect_refusal = True
                name = {'duration_hundredths': 'duration_hours', 'budget_cents': 'budget', 'actual_cents': 'actual'}.get(field, field)
                arguments = (name, replacement if isinstance(replacement, str) else f'{replacement / 100:.2f}')
                try:
                    store.update_session(key, **{arguments[0]: arguments[1]})
                    self.assertFalse(expect_refusal)
                    state['session'][key][field] = replacement
                except ValidationError:
                    self.assertTrue(expect_refusal)
                    continue
            elif choice < 0.7 and state['attendance'] and free_pairs():
                key = rng.choice(sorted(state['attendance']))
                sid, pid = rng.choice(free_pairs())
                store.update_attendance(key, session_id=sid, participant_id=pid)
                state['attendance'][key].update(session_id=sid, participant_id=pid)
            elif choice < 0.8 and state['attendance']:
                key = rng.choice(sorted(state['attendance']))
                store.delete_attendance(key)
                del state['attendance'][key]
            elif choice < 0.88:
                key = rng.choice(sorted(state['session']))
                used = any(row['session_id'] == key for row in state['attendance'].values())
                try:
                    store.delete_session(key)
                    self.assertFalse(used)
                    del state['session'][key]
                except ValidationError:
                    self.assertTrue(used)
                    continue
            elif imports:
                batch = rng.choice(sorted(imports))
                entity, keys = imports[batch]
                created = [entry for entry in self.batch_entries(store, batch)]
                allowed = all(key in state[entity] and audit.canonical(state[entity][key]) == after for key, after in created)
                if entity == 'session':
                    allowed = allowed and not any(row['session_id'] in keys for row in state['attendance'].values())
                try:
                    store.undo_import(batch)
                    self.assertTrue(allowed, batch)
                    for key in keys:
                        del state[entity][key]
                    del imports[batch]
                except ValidationError:
                    self.assertFalse(allowed, batch)
                    continue
            else:
                continue
            checkpoints.append((audit.timestamp(clock()), store.history(1)['head']['entry'], copy.deepcopy(state)))
        return store, checkpoints, rng

    def batch_entries(self, store, batch):
        with closing(sqlite3.connect(store.path)) as connection:
            return [(row[0], row[1]) for row in connection.execute('SELECT entity_id, after FROM audit_log WHERE batch_id = ? ORDER BY seq', (batch,))]

    def expected_at(self, checkpoints, moment):
        state = checkpoints[0][2]
        for time, _, snapshot in checkpoints[1:]:
            if time <= moment:
                state = snapshot
        return state

    def assert_same_report(self, actual, expected, label):
        for key in ['totals', 'programs', 'monthly', 'sessions']:
            self.assertEqual(actual[key], expected[key], f'{label}: {key}')

    def test_as_of_reports_equal_reports_of_the_replayed_state(self):
        checked = 0
        for seed in range(SEQUENCES):
            store, checkpoints, rng = self.run_sequence(seed)
            boundaries = {0} | {entry for _, entry, _ in checkpoints}
            times = sorted({time for time, _, _ in checkpoints[1:]})
            probes = ['2026-09-30'] + times + [audit.timestamp(datetime.fromisoformat(t[:-1] + '+00:00') - timedelta(microseconds=1)) for t in times[1:]]
            for moment in probes:
                state = self.expected_at(checkpoints, audit.parse_as_of(moment))
                oracle = self.oracle(state)
                dates = sorted(row['session_date'] for row in state['session'].values()) or ['2026-02-01']
                filters = rng.choice([{}, {'program': rng.choice(PROGRAMS)}, {'start': dates[0], 'end': dates[len(dates) // 2]},
                                      {'start': rng.choice(dates), 'end': '2026-12-31', 'program': rng.choice(PROGRAMS)}])
                summary = store.summary(**filters, as_of=moment)
                self.assertIn(summary['as_of']['entry'], boundaries, 'an as-of time never splits a batch')
                self.assert_same_report(summary, oracle.summary(**filters), f'seed {seed} at {moment} {filters}')
                self.assertEqual(store.snapshot(as_of=moment)['sessions'], oracle.snapshot()['sessions'])
                for kind in ['sessions', 'attendance']:
                    self.assertEqual(store.export_csv(kind, **filters, as_of=moment), oracle.export_csv(kind, **filters))
                if 'start' in filters:
                    comparison = store.comparison(**filters, as_of=moment)
                    expected = oracle.comparison(**filters)
                    self.assertEqual({k: comparison[k] for k in expected}, expected)
                checked += 1
            for _, entry, state in checkpoints:
                self.assert_same_report(store.summary(as_of_entry=entry), self.oracle(state).summary(), f'seed {seed} entry {entry}')
            self.assert_same_report(store.summary(as_of_entry=checkpoints[-1][1]), store.summary(), 'latest entry equals current tables')
            self.assertTrue(store.verify()['valid'])
        self.assertGreater(checked, SEQUENCES * 10)

    def test_as_of_input_validation(self):
        store = Store(Path(self.temp.name) / 'v.db', clock=FakeClock())
        store.seed_demo()
        for kwargs, message in [({'as_of': '2026-13-01'}, 'exist'), ({'as_of': '2026-10-01T12:00:00'}, 'UTC'),
                                ({'as_of': '2026-10-01', 'as_of_entry': 1}, 'either'), ({'as_of_entry': 10**6}, 'from 0 to 378'),
                                ({'as_of_entry': '-1'}, 'whole number'), ({'as_of_entry': True}, 'from 0')]:
            with self.subTest(kwargs=kwargs), self.assertRaisesRegex(ValidationError, message):
                store.summary(**kwargs)
        self.assertEqual(store.summary(as_of='2026-10-01T11:59:59.999999Z')['totals']['sessions'], 0)
        self.assertEqual(store.summary(as_of='2026-10-01T12:00:00Z')['totals']['sessions'], 36)
        self.assertEqual(store.summary(as_of='2026-10-01')['as_of']['entry'], 378)


if __name__ == '__main__':
    unittest.main()
