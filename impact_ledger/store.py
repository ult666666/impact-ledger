"""Strict CSV boundaries and exact session/attendance accounting."""
from collections import defaultdict
from contextlib import contextmanager
import csv
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP
import io
from pathlib import Path
import re
import sqlite3

from . import audit
from .csv_import import (HEADERS, MAX_BYTES, MAX_ROWS, ValidationError, identifier, program_label, scaled,
                         valid_date, validate_csv, validate_kind)

SESSION_FIELDS = audit.ENTITIES['session'][2]
ATTENDANCE_FIELDS = audit.ENTITIES['attendance'][2]


def ratio(numerator, denominator):
    if not denominator:
        return None
    return float((Decimal(numerator) / Decimal(denominator)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP))


def hundredth_totals(rows):
    budget = sum(row['budget_cents'] for row in rows)
    actual = sum(row['actual_cents'] for row in rows)
    return {
        'participant_hours': sum(row['duration_hundredths'] * len(row['participants']) for row in rows),
        'session_hours': sum(row['duration_hundredths'] for row in rows),
        'budget': budget, 'actual': actual, 'variance': actual - budget,
    }


def summarize(rows):
    people = {person for row in rows for person in row['participants']}
    attendance = sum(len(row['participants']) for row in rows)
    budget = sum(row['budget_cents'] for row in rows)
    actual = sum(row['actual_cents'] for row in rows)
    return {
        'sessions': len(rows), 'unique_participants': len(people), 'attendance': attendance,
        'participant_hours': sum(row['duration_hundredths'] * len(row['participants']) for row in rows) / 100,
        'session_hours': sum(row['duration_hundredths'] for row in rows) / 100,
        'budget': budget / 100, 'actual': actual / 100, 'variance': (actual - budget) / 100,
        'variance_percent': ratio((actual - budget) * 100, budget),
        'attendance_per_participant': ratio(attendance, len(people)),
    }


class Store:
    def __init__(self, path, clock=None):
        self.path = Path(path)
        self.clock = clock or audit.utc_now
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            version = connection.execute('PRAGMA user_version').fetchone()[0]
            if version > audit.SCHEMA_VERSION:
                raise ValidationError(f'This ledger uses schema version {version}; this impact-ledger reads up to {audit.SCHEMA_VERSION}.')
            connection.executescript('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    program TEXT NOT NULL,
                    session_date TEXT NOT NULL,
                    duration_hundredths INTEGER NOT NULL CHECK(duration_hundredths > 0 AND duration_hundredths <= 2400),
                    budget_cents INTEGER NOT NULL CHECK(budget_cents >= 0),
                    actual_cents INTEGER NOT NULL CHECK(actual_cents >= 0)
                );
                CREATE TABLE IF NOT EXISTS attendance (
                    attendance_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL REFERENCES sessions(session_id),
                    participant_id TEXT NOT NULL,
                    UNIQUE(session_id, participant_id)
                );
                CREATE INDEX IF NOT EXISTS sessions_date_program ON sessions(session_date, program);
                CREATE INDEX IF NOT EXISTS attendance_session ON attendance(session_id);
            ''' + audit.DDL)
        with self._connection() as connection:
            # Schema 0 ledgers (1.2.x) had no history. Their rows become one
            # baseline batch, so replaying the log reproduces the tables.
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('PRAGMA user_version').fetchone()[0] == 0:
                if not connection.execute('SELECT 1 FROM audit_log LIMIT 1').fetchone():
                    state = audit.current_state(connection)
                    changes = [('create', entity, None, state[entity][key]) for entity in ('session', 'attendance') for key in sorted(state[entity])]
                    if changes:
                        audit.append_batch(connection, changes, actor='migration', kind='baseline', clock=self.clock)
                connection.execute(f'PRAGMA user_version = {audit.SCHEMA_VERSION}')

    @classmethod
    def open_existing(cls, path):
        """Open an initialized ledger without creating paths or running schema DDL."""
        store = cls.__new__(cls)
        store.path = Path(path)
        store.clock = audit.utc_now
        with store._read_connection() as connection:
            connection.execute('SELECT session_id,program,session_date,duration_hundredths,budget_cents,actual_cents FROM sessions LIMIT 0')
            connection.execute('SELECT attendance_id,session_id,participant_id FROM attendance LIMIT 0')
        return store

    @contextmanager
    def _connection(self):
        connection = sqlite3.connect(self.path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA foreign_keys = ON')
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    @contextmanager
    def _read_connection(self):
        # mode=ro cannot create the database or execute schema/data writes.
        connection = sqlite3.connect(self.path.resolve().as_uri() + '?mode=ro', uri=True, timeout=5)
        connection.row_factory = sqlite3.Row
        try:
            connection.execute('BEGIN')
            yield connection
        finally:
            connection.close()

    def preview_csv(self, kind, payload):
        validate_kind(kind)
        with self._read_connection() as connection:
            result, _ = validate_csv(kind, payload, connection)
            return result

    def import_csv(self, kind, payload, actor='local'):
        validate_kind(kind)
        audit.actor_label(actor)
        try:
            with self._connection() as connection:
                # Revalidate current state after acquiring the writer transaction.
                # A prior preview never reserves an ID or authorizes these bytes.
                connection.execute('BEGIN IMMEDIATE')
                result, rows = validate_csv(kind, payload, connection)
                if not result['valid']:
                    first = result['errors'][0]
                    location = f"Row {first['row']}: " if first['row'] is not None else ''
                    raise ValidationError(location + first['message'] + ' No rows were added.')
                placeholders = '?,?,?,?,?,?' if kind == 'sessions' else '?,?,?'
                connection.executemany(f'INSERT INTO {kind} VALUES ({placeholders})', rows)
                entity, fields = ('session', SESSION_FIELDS) if kind == 'sessions' else ('attendance', ATTENDANCE_FIELDS)
                batch_id = audit.append_batch(connection, [('create', entity, None, dict(zip(fields, row))) for row in rows],
                                              actor=actor, kind='import', clock=self.clock)
        except sqlite3.IntegrityError as exc:
            raise ValidationError('Import rejected: duplicate ID, duplicate person/session pair, or unknown session. No rows were added.') from exc
        return {'kind': kind, 'imported': len(rows), 'batch_id': batch_id}

    def _record(self, connection, entity, key):
        table, id_field, fields = audit.ENTITIES[entity]
        row = connection.execute(f'SELECT {",".join(fields)} FROM {table} WHERE {id_field} = ?', (key,)).fetchone()
        return None if row is None else dict(zip(fields, row))

    def _write(self, actor, kind, apply):
        """Run one audited change in a writer transaction: apply() returns (operation, entity, before, after)."""
        audit.actor_label(actor)
        try:
            with self._connection() as connection:
                connection.execute('BEGIN IMMEDIATE')
                operation, entity, before, after = apply(connection)
                table, id_field, fields = audit.ENTITIES[entity]
                key = (after or before)[id_field]
                if operation == 'delete':
                    connection.execute(f'DELETE FROM {table} WHERE {id_field} = ?', (key,))
                else:
                    connection.execute(f'UPDATE {table} SET {",".join(f + " = ?" for f in fields[1:])} WHERE {id_field} = ?',
                                       [after[f] for f in fields[1:]] + [key])
                batch_id = audit.append_batch(connection, [(operation, entity, before, after)], actor=actor, kind=kind, clock=self.clock)
        except sqlite3.IntegrityError as exc:
            raise ValidationError('Change rejected: duplicate person/session pair or unknown session. Nothing was changed.') from exc
        return {'batch_id': batch_id, 'operation': operation, 'entity': entity, 'entity_id': key, 'before': before, 'after': after}

    def update_session(self, session_id, actor='local', program=None, session_date=None, duration_hours=None, budget=None, actual=None):
        """Correct one session. Text values use the CSV field rules; omitted fields keep their value."""
        identifier(session_id)
        changes = {'program': program_label(program) if program is not None else None,
                   'session_date': valid_date(session_date) if session_date is not None else None,
                   'duration_hundredths': scaled(duration_hours, 'Duration hours', Decimal(24), False) if duration_hours is not None else None,
                   'budget_cents': scaled(budget, 'Budget', Decimal(10000000)) if budget is not None else None,
                   'actual_cents': scaled(actual, 'Actual', Decimal(10000000)) if actual is not None else None}

        def apply(connection):
            before = self._record(connection, 'session', session_id)
            if before is None:
                raise ValidationError('Session does not exist.')
            after = {**before, **{key: value for key, value in changes.items() if value is not None}}
            if after == before:
                raise ValidationError('No field changes. Nothing was recorded.')
            return 'update', 'session', before, after
        return self._write(actor, 'update', apply)

    def update_attendance(self, attendance_id, actor='local', session_id=None, participant_id=None):
        identifier(attendance_id)
        changes = {'session_id': identifier(session_id) if session_id is not None else None,
                   'participant_id': identifier(participant_id) if participant_id is not None else None}

        def apply(connection):
            before = self._record(connection, 'attendance', attendance_id)
            if before is None:
                raise ValidationError('Attendance record does not exist.')
            after = {**before, **{key: value for key, value in changes.items() if value is not None}}
            if after == before:
                raise ValidationError('No field changes. Nothing was recorded.')
            if self._record(connection, 'session', after['session_id']) is None:
                raise ValidationError('Session does not exist.')
            return 'update', 'attendance', before, after
        return self._write(actor, 'update', apply)

    def delete_session(self, session_id, actor='local'):
        identifier(session_id)

        def apply(connection):
            before = self._record(connection, 'session', session_id)
            if before is None:
                raise ValidationError('Session does not exist.')
            count = connection.execute('SELECT COUNT(*) FROM attendance WHERE session_id = ?', (session_id,)).fetchone()[0]
            if count:
                raise ValidationError(f'Session has {count} attendance record(s). Delete them first; nothing was changed.')
            return 'delete', 'session', before, None
        return self._write(actor, 'delete', apply)

    def delete_attendance(self, attendance_id, actor='local'):
        identifier(attendance_id)

        def apply(connection):
            before = self._record(connection, 'attendance', attendance_id)
            if before is None:
                raise ValidationError('Attendance record does not exist.')
            return 'delete', 'attendance', before, None
        return self._write(actor, 'delete', apply)

    def undo_import(self, batch_id, actor='local'):
        """Reverse one CSV import with a compensating delete batch. History is never removed."""
        audit.actor_label(actor)
        if not isinstance(batch_id, str) or not re.fullmatch(r'B\d{6,}', batch_id):
            raise ValidationError('Batch IDs look like B000012.')
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            created = connection.execute('SELECT batch_kind, entity, entity_id, after FROM audit_log WHERE batch_id = ? ORDER BY seq', (batch_id,)).fetchall()
            if not created:
                raise ValidationError('No batch with that ID exists in this ledger.')
            if created[0][0] != 'import':
                raise ValidationError('Only CSV import batches can be undone.')
            undone = connection.execute('SELECT batch_id FROM audit_log WHERE reverts = ? LIMIT 1', (batch_id,)).fetchone()
            if undone:
                raise ValidationError(f'Batch {batch_id} was already undone by {undone[0]}.')
            entity = created[0][1]
            keys = {row[2] for row in created}
            changes = []
            for _, _, key, after in reversed(created):
                current = self._record(connection, entity, key)
                if current is None or audit.canonical(current) != after:
                    raise ValidationError(f'{entity.capitalize()} {key} changed or was deleted after this import. Correct it explicitly; nothing was undone.')
                changes.append(('delete', entity, current, None))
            if entity == 'session':
                placeholders = ','.join('?' * len(keys))
                dependent = connection.execute(f'SELECT COUNT(*) FROM attendance WHERE session_id IN ({placeholders})', sorted(keys)).fetchone()[0]
                if dependent:
                    raise ValidationError(f'{dependent} attendance record(s) reference sessions from this import. Undo or delete them first; nothing was undone.')
            table, id_field, _ = audit.ENTITIES[entity]
            connection.executemany(f'DELETE FROM {table} WHERE {id_field} = ?', [(change[2][id_field],) for change in changes])
            undo_id = audit.append_batch(connection, changes, actor=actor, kind='undo', clock=self.clock, reverts=batch_id)
        return {'batch_id': undo_id, 'reverts': batch_id, 'deleted': len(changes), 'entity': entity}

    def history(self, limit=100):
        if isinstance(limit, str):
            if not re.fullmatch(r'[1-9]\d{0,3}', limit):
                raise ValidationError('limit must be a whole number from 1 to 500.')
            limit = int(limit)
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValidationError('limit must be a whole number from 1 to 500.')
        with self._connection() as connection:
            connection.execute('BEGIN')
            undone = dict(connection.execute('SELECT reverts, batch_id FROM audit_log WHERE reverts IS NOT NULL GROUP BY batch_id'))
            batches = [{
                'batch_id': row[0], 'kind': row[1], 'actor': row[2], 'recorded_at': row[3], 'reverts': row[4],
                'first_entry': row[5], 'last_entry': row[6], 'entries': row[7],
                'created': row[8], 'updated': row[9], 'deleted': row[10], 'undone_by': undone.get(row[0]),
            } for row in connection.execute('''
                SELECT batch_id, batch_kind, actor, recorded_at, reverts, MIN(seq), MAX(seq), COUNT(*),
                       SUM(operation = 'create'), SUM(operation = 'update'), SUM(operation = 'delete')
                FROM audit_log GROUP BY batch_id ORDER BY MIN(seq) DESC LIMIT ?''', (limit,))]
            return {'synthetic': True, 'head': audit.head(connection), 'batches': batches,
                    'batches_total': connection.execute('SELECT COUNT(DISTINCT batch_id) FROM audit_log').fetchone()[0]}

    def verify(self, expect_head=None):
        if expect_head is not None and not re.fullmatch(r'[0-9a-f]{64}', expect_head):
            raise ValidationError('expect_head must be a 64-character lowercase SHA-256 hex digest.')
        with self._read_connection() as connection:
            return audit.verify(connection, expect_head)

    def _where(self, start=None, end=None, program=None):
        if start:
            valid_date(start)
        if end:
            valid_date(end)
        if start and end and start > end:
            raise ValidationError('Start date must be on or before end date.')
        if program:
            program_label(program)
        conditions, values = [], []
        for field, operator, value in [('s.session_date', '>=', start), ('s.session_date', '<=', end), ('s.program', '=', program)]:
            if value:
                conditions.append(f'{field} {operator} ?')
                values.append(value)
        return (' WHERE ' + ' AND '.join(conditions) if conditions else ''), values

    def _rows(self, connection, start=None, end=None, program=None):
        clause, values = self._where(start, end, program)
        rows = [dict(row) for row in connection.execute('SELECT s.* FROM sessions s' + clause + ' ORDER BY s.session_date,s.session_id', values)]
        people = defaultdict(list)
        records = defaultdict(list)
        for row in connection.execute('SELECT a.* FROM attendance a JOIN sessions s USING(session_id)' + clause + ' ORDER BY a.attendance_id', values):
            people[row['session_id']].append(row['participant_id'])
            records[row['session_id']].append({'attendance_id': row['attendance_id'], 'participant_id': row['participant_id']})
        for row in rows:
            row['participants'] = people[row['session_id']]
            row['attendance_records'] = records[row['session_id']]
        return rows

    def _rows_from_state(self, state, start=None, end=None, program=None):
        """The rows _rows would return if the tables held this replayed state."""
        self._where(start, end, program)
        selected = sorted((row for row in state['session'].values()
                           if (not start or row['session_date'] >= start) and (not end or row['session_date'] <= end)
                           and (not program or row['program'] == program)),
                          key=lambda row: (row['session_date'], row['session_id']))
        records = defaultdict(list)
        for record in sorted(state['attendance'].values(), key=lambda record: record['attendance_id']):
            records[record['session_id']].append(record)
        rows = []
        for selected_row in selected:
            row = {field: selected_row[field] for field in SESSION_FIELDS}
            row['participants'] = [record['participant_id'] for record in records[row['session_id']]]
            row['attendance_records'] = [{'attendance_id': record['attendance_id'], 'participant_id': record['participant_id']}
                                         for record in records[row['session_id']]]
            rows.append(row)
        return rows

    def _view(self, connection, as_of=None, as_of_entry=None):
        """None for the current tables, or the as-of point and its verified replayed state."""
        if as_of is None and as_of_entry is None:
            return None, None
        point = audit.resolve_as_of(connection, as_of, as_of_entry)
        return point, audit.verified_state(connection, point['entry'])

    def _select(self, connection, state, start=None, end=None, program=None):
        return self._rows(connection, start, end, program) if state is None else self._rows_from_state(state, start, end, program)

    def snapshot(self, start=None, end=None, program=None, as_of=None, as_of_entry=None):
        with self._connection() as connection:
            connection.execute('BEGIN')
            point, state = self._view(connection, as_of, as_of_entry)
            result = {'synthetic': True, 'currency': 'USD', 'sessions': self._select(connection, state, start, end, program)}
        if point is not None:
            result['as_of'] = point
        return result

    def summary(self, start=None, end=None, program=None, as_of=None, as_of_entry=None):
        view = self.snapshot(start, end, program, as_of, as_of_entry)
        rows = view['sessions']
        programs, months = defaultdict(list), defaultdict(list)
        for row in rows:
            programs[row['program']].append(row)
            months[row['session_date'][:7]].append(row)
        result = {
            'synthetic': True, 'currency': 'USD',
            'filters': {'start': start or None, 'end': end or None, 'program': program or None},
            'totals': summarize(rows),
            'programs': [{'program': key, **summarize(value)} for key, value in sorted(programs.items())],
            'monthly': [{'month': key, **summarize(value)} for key, value in sorted(months.items())],
            'sessions': [{
                'session_id': row['session_id'], 'program': row['program'], 'session_date': row['session_date'],
                'duration_hours': row['duration_hundredths'] / 100,
                'attendance': len(row['participants']),
                'participant_hours': row['duration_hundredths'] * len(row['participants']) / 100,
                'budget': row['budget_cents'] / 100, 'actual': row['actual_cents'] / 100,
                'variance': (row['actual_cents'] - row['budget_cents']) / 100,
            } for row in rows],
        }
        if 'as_of' in view:
            result['as_of'] = view['as_of']
        return result

    def comparison(self, start=None, end=None, program=None, as_of=None, as_of_entry=None):
        """Compare two inclusive calendar windows in one database read transaction."""
        if not start or not end:
            raise ValidationError('Comparison requires both start and end dates. Set both dates and apply filters.')
        self._where(start, end, program)
        first, last = date.fromisoformat(start), date.fromisoformat(end)
        days = (last - first).days + 1
        if first.toordinal() <= days:
            raise ValidationError('Previous period would start before 0001-01-01. Choose a later or shorter range.')
        previous_start = (first - timedelta(days=days)).isoformat()
        previous_end = (first - timedelta(days=1)).isoformat()
        with self._connection() as connection:
            connection.execute('BEGIN')
            point, state = self._view(connection, as_of, as_of_entry)
            current_rows = self._select(connection, state, start, end, program)
            previous_rows = self._select(connection, state, previous_start, previous_end, program)
        current, previous = summarize(current_rows), summarize(previous_rows)
        current_exact, previous_exact = hundredth_totals(current_rows), hundredth_totals(previous_rows)
        counts = ('sessions', 'unique_participants', 'attendance')
        amounts = ('participant_hours', 'session_hours', 'budget', 'actual', 'variance')
        result = {
            'synthetic': True, 'currency': 'USD',
            'filters': {'start': start, 'end': end, 'program': program or None}, 'days': days,
            'current': {'start': start, 'end': end, 'totals': current},
            'previous': {'start': previous_start, 'end': previous_end, 'totals': previous},
            'deltas': {**{key: current[key] - previous[key] for key in counts},
                       **{key: (current_exact[key] - previous_exact[key]) / 100 for key in amounts}},
        }
        if point is not None:
            result['as_of'] = point
        return result

    def metadata(self):
        with self._connection() as connection:
            connection.execute('BEGIN')
            bounds = connection.execute('SELECT MIN(session_date),MAX(session_date),COUNT(*) FROM sessions').fetchone()
            return {
                'synthetic': True, 'currency': 'USD',
                'programs': [row[0] for row in connection.execute('SELECT DISTINCT program FROM sessions ORDER BY program')],
                'start': bounds[0], 'end': bounds[1], 'sessions': bounds[2],
                'attendance': connection.execute('SELECT COUNT(*) FROM attendance').fetchone()[0],
                'limits': {'bytes': MAX_BYTES, 'rows': MAX_ROWS},
            }

    def export_csv(self, kind, start=None, end=None, program=None, as_of=None, as_of_entry=None):
        if kind not in HEADERS:
            raise ValidationError('Export kind must be sessions or attendance.')
        clause, values = self._where(start, end, program)
        output = io.StringIO(newline='')
        writer = csv.writer(output, lineterminator='\r\n')
        writer.writerow(HEADERS[kind])
        with self._connection() as connection:
            connection.execute('BEGIN')
            point, state = self._view(connection, as_of, as_of_entry)
            if state is not None:
                rows = self._rows_from_state(state, start, end, program)
                if kind == 'sessions':
                    for row in rows:
                        writer.writerow([row['session_id'], row['program'], row['session_date'],
                                         f"{Decimal(row['duration_hundredths']) / 100:.2f}",
                                         f"{Decimal(row['budget_cents']) / 100:.2f}", f"{Decimal(row['actual_cents']) / 100:.2f}"])
                else:
                    selected = {row['session_id'] for row in rows}
                    for record in sorted(state['attendance'].values(), key=lambda record: record['attendance_id']):
                        if record['session_id'] in selected:
                            writer.writerow([record['attendance_id'], record['session_id'], record['participant_id']])
            elif kind == 'sessions':
                for row in connection.execute('SELECT s.* FROM sessions s' + clause + ' ORDER BY s.session_date,s.session_id', values):
                    writer.writerow([row['session_id'], row['program'], row['session_date'],
                                     f"{Decimal(row['duration_hundredths']) / 100:.2f}",
                                     f"{Decimal(row['budget_cents']) / 100:.2f}", f"{Decimal(row['actual_cents']) / 100:.2f}"])
            else:
                for row in connection.execute('SELECT a.* FROM attendance a JOIN sessions s USING(session_id)' + clause + ' ORDER BY a.attendance_id', values):
                    writer.writerow([row['attendance_id'], row['session_id'], row['participant_id']])
        return output.getvalue().encode('utf-8')

    def seed_demo(self, actor='seed'):
        # Single transaction: seed only an empty database; stable identities are fictional.
        sessions, attendance = [], []
        for week in range(12):
            for program_index, (program, hours, budget) in enumerate([
                ('Learning Lab', 150, 18500), ('Community Kitchen', 250, 29000), ('Digital Access', 200, 14500),
            ]):
                sid = f'demo-s{week + 1:02}-{program_index + 1}'
                day = date(2026, 7, 6) + timedelta(days=week * 7 + program_index)
                planned = budget + (week % 3) * 1200
                actual = planned + ((week * 3 + program_index) % 7 - 3) * 700
                sessions.append((sid, program, day.isoformat(), hours, planned, actual))
                for person in range(7 + (week + program_index * 2) % 6):
                    pid = f'demo-p{(week * 4 + person + program_index * 13) % 55 + 1:03}'
                    attendance.append((f'{sid}-a{person + 1:02}', sid, pid))
        with self._connection() as connection:
            connection.execute('BEGIN IMMEDIATE')
            if connection.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]:
                raise ValidationError('Demo seed requires an empty database. Choose a new --db path.')
            connection.executemany('INSERT INTO sessions VALUES (?,?,?,?,?,?)', sessions)
            connection.executemany('INSERT INTO attendance VALUES (?,?,?)', attendance)
            changes = [('create', 'session', None, dict(zip(SESSION_FIELDS, row))) for row in sessions]
            changes += [('create', 'attendance', None, dict(zip(ATTENDANCE_FIELDS, row))) for row in attendance]
            batch_id = audit.append_batch(connection, changes, actor=actor, kind='seed', clock=self.clock)
        return {'sessions': len(sessions), 'attendance': len(attendance), 'synthetic': True, 'batch_id': batch_id}
