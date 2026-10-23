"""Strict CSV boundaries and exact session/attendance accounting."""
from collections import defaultdict
from contextlib import contextmanager
import csv
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import io
from pathlib import Path
import re
import sqlite3

MAX_BYTES = 1024 * 1024
MAX_ROWS = 5000
HEADERS = {
    'sessions': ['session_id', 'program', 'session_date', 'duration_hours', 'budget', 'actual'],
    'attendance': ['attendance_id', 'session_id', 'participant_id'],
}
IDENTIFIER = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z')


class ValidationError(ValueError):
    """A user-supplied request violates the import/filter contract."""


def valid_date(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        raise ValidationError('Dates must use YYYY-MM-DD.')
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise ValidationError('Date does not exist.') from exc
    return value


def program_label(value):
    if not isinstance(value, str) or not value or value != value.strip() or len(value) > 80:
        raise ValidationError('Program must have 1–80 characters without surrounding spaces.')
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValidationError('Program contains a control character.')
    if value[0] in '=+-@':
        raise ValidationError('Program cannot begin with a spreadsheet formula marker.')
    return value


def identifier(value):
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise ValidationError('IDs must be 1–64 ASCII letters, digits, dots, underscores or hyphens, starting with a letter or digit.')
    return value


def scaled(value, label, maximum, allow_zero=True):
    # Bounded syntax prevents nonfinite values, exponent bombs and accidental rounding.
    if not re.fullmatch(r'(?:0|[1-9]\d{0,7})(?:\.\d{1,2})?', value):
        raise ValidationError(f'{label} must be a nonnegative decimal with at most two decimal places.')
    try:
        number = Decimal(value)
    except InvalidOperation as exc:
        raise ValidationError(f'Invalid {label}.') from exc
    if number > maximum or (not allow_zero and number == 0):
        raise ValidationError(f'{label} is outside the supported range.')
    return int(number * 100)


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
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
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
            ''')

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

    def import_csv(self, kind, payload):
        if kind not in HEADERS:
            raise ValidationError('Import kind must be sessions or attendance.')
        if len(payload) > MAX_BYTES:
            raise ValidationError('CSV exceeds the 1 MiB limit.')
        try:
            content = payload.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValidationError('CSV must be valid UTF-8.') from exc
        rows = []
        try:
            reader = csv.reader(io.StringIO(content, newline=''), strict=True)
            if next(reader, None) != HEADERS[kind]:
                raise ValidationError('CSV headers must exactly match: ' + ','.join(HEADERS[kind]))
            for index, row in enumerate(reader, 2):
                if len(rows) >= MAX_ROWS:
                    raise ValidationError('CSV exceeds the 5,000 data-row limit.')
                if len(row) != len(HEADERS[kind]):
                    raise ValidationError(f'Row {index}: wrong number of columns.')
                try:
                    if kind == 'sessions':
                        sid, program, day, hours, budget, actual = row
                        parsed = (identifier(sid), program_label(program), valid_date(day),
                                  scaled(hours, 'Duration hours', Decimal(24), False),
                                  scaled(budget, 'Budget', Decimal(10000000)),
                                  scaled(actual, 'Actual', Decimal(10000000)))
                    else:
                        parsed = tuple(identifier(value) for value in row)
                except ValidationError as exc:
                    raise ValidationError(f'Row {index}: {exc}') from exc
                rows.append(parsed)
        except csv.Error as exc:
            raise ValidationError('Malformed CSV quoting or field size.') from exc
        if not rows:
            raise ValidationError('CSV must contain at least one data row.')
        table = 'sessions' if kind == 'sessions' else 'attendance'
        placeholders = '?,?,?,?,?,?' if kind == 'sessions' else '?,?,?'
        try:
            with self._connection() as connection:
                connection.executemany(f'INSERT INTO {table} VALUES ({placeholders})', rows)
        except sqlite3.IntegrityError as exc:
            raise ValidationError('Import rejected: duplicate ID, duplicate person/session pair, or unknown session. No rows were added.') from exc
        return {'kind': kind, 'imported': len(rows)}

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

    def snapshot(self, start=None, end=None, program=None):
        with self._connection() as connection:
            connection.execute('BEGIN')
            return {'synthetic': True, 'currency': 'USD', 'sessions': self._rows(connection, start, end, program)}

    def summary(self, start=None, end=None, program=None):
        rows = self.snapshot(start, end, program)['sessions']
        programs, months = defaultdict(list), defaultdict(list)
        for row in rows:
            programs[row['program']].append(row)
            months[row['session_date'][:7]].append(row)
        return {
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

    def comparison(self, start=None, end=None, program=None):
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
            current_rows = self._rows(connection, start, end, program)
            previous_rows = self._rows(connection, previous_start, previous_end, program)
        current, previous = summarize(current_rows), summarize(previous_rows)
        current_exact, previous_exact = hundredth_totals(current_rows), hundredth_totals(previous_rows)
        counts = ('sessions', 'unique_participants', 'attendance')
        amounts = ('participant_hours', 'session_hours', 'budget', 'actual', 'variance')
        return {
            'synthetic': True, 'currency': 'USD',
            'filters': {'start': start, 'end': end, 'program': program or None}, 'days': days,
            'current': {'start': start, 'end': end, 'totals': current},
            'previous': {'start': previous_start, 'end': previous_end, 'totals': previous},
            'deltas': {**{key: current[key] - previous[key] for key in counts},
                       **{key: (current_exact[key] - previous_exact[key]) / 100 for key in amounts}},
        }

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

    def export_csv(self, kind, start=None, end=None, program=None):
        if kind not in HEADERS:
            raise ValidationError('Export kind must be sessions or attendance.')
        clause, values = self._where(start, end, program)
        output = io.StringIO(newline='')
        writer = csv.writer(output, lineterminator='\r\n')
        writer.writerow(HEADERS[kind])
        with self._connection() as connection:
            if kind == 'sessions':
                for row in connection.execute('SELECT s.* FROM sessions s' + clause + ' ORDER BY s.session_date,s.session_id', values):
                    writer.writerow([row['session_id'], row['program'], row['session_date'],
                                     f"{Decimal(row['duration_hundredths']) / 100:.2f}",
                                     f"{Decimal(row['budget_cents']) / 100:.2f}", f"{Decimal(row['actual_cents']) / 100:.2f}"])
            else:
                for row in connection.execute('SELECT a.* FROM attendance a JOIN sessions s USING(session_id)' + clause + ' ORDER BY a.attendance_id', values):
                    writer.writerow([row['attendance_id'], row['session_id'], row['participant_id']])
        return output.getvalue().encode('utf-8')

    def seed_demo(self):
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
        return {'sessions': len(sessions), 'attendance': len(attendance), 'synthetic': True}
