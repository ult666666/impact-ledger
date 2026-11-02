"""Append-only, hash-chained audit history and replay of past ledger states.

Every ledger write appends entries in the same SQLite transaction as the
change. An entry stores the row before and after the write as canonical JSON
and the SHA-256 digest of the previous entry, so editing, deleting or
reordering any entry breaks the chain. Reports as of a past time replay the
log prefix after checking it, rather than reading a second copy of history.
"""
from datetime import datetime, timezone
import hashlib
import json
import re

from .csv_import import ValidationError

SCHEMA_VERSION = 1
GENESIS = '0' * 64
ENTITIES = {
    'session': ('sessions', 'session_id', ('session_id', 'program', 'session_date', 'duration_hundredths', 'budget_cents', 'actual_cents')),
    'attendance': ('attendance', 'attendance_id', ('attendance_id', 'session_id', 'participant_id')),
}
BATCH_KINDS = ('baseline', 'seed', 'import', 'update', 'delete', 'undo')
HASHED_FIELDS = ('seq', 'recorded_at', 'actor', 'batch_id', 'batch_kind', 'reverts', 'operation',
                 'entity', 'entity_id', 'before', 'after', 'prev_hash')
COLUMNS = HASHED_FIELDS + ('entry_hash',)
TRIGGERS = ('audit_log_no_update', 'audit_log_no_delete', 'audit_log_extends_chain')
TIMESTAMP = re.compile(r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z')
MAX_PROBLEMS = 100

DDL = f'''
CREATE TABLE IF NOT EXISTS audit_log (
    seq INTEGER PRIMARY KEY CHECK(seq >= 1),
    recorded_at TEXT NOT NULL,
    actor TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    batch_kind TEXT NOT NULL CHECK(batch_kind IN {BATCH_KINDS}),
    reverts TEXT,
    operation TEXT NOT NULL CHECK(operation IN ('create', 'update', 'delete')),
    entity TEXT NOT NULL CHECK(entity IN ('session', 'attendance')),
    entity_id TEXT NOT NULL,
    before TEXT,
    after TEXT,
    prev_hash TEXT NOT NULL,
    entry_hash TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS audit_batch ON audit_log(batch_id);
CREATE INDEX IF NOT EXISTS audit_time ON audit_log(recorded_at);
CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_log_extends_chain BEFORE INSERT ON audit_log
WHEN NEW.seq IS NOT (SELECT COALESCE(MAX(seq), 0) + 1 FROM audit_log)
  OR NEW.prev_hash IS NOT COALESCE((SELECT entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1), '{GENESIS}')
  OR NEW.recorded_at < COALESCE((SELECT recorded_at FROM audit_log ORDER BY seq DESC LIMIT 1), '')
BEGIN SELECT RAISE(ABORT, 'audit_log entries must extend the chain in order'); END;
'''


def canonical(row):
    return json.dumps(row, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def entry_hash(entry):
    """SHA-256 of the hashed fields in a fixed order; prev_hash links the chain."""
    payload = json.dumps([entry[field] for field in HASHED_FIELDS], separators=(',', ':'), ensure_ascii=False)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


def timestamp(moment):
    if moment.tzinfo is None:
        raise ValueError('The audit clock must return timezone-aware times.')
    return moment.astimezone(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def utc_now():
    return datetime.now(timezone.utc)


def actor_label(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 64 or value != value.strip():
        raise ValidationError('Actor must have 1–64 characters without surrounding spaces.')
    if any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value):
        raise ValidationError('Actor contains a control character.')
    return value


def row_dict(entity, row):
    return {key: row[key] for key in ENTITIES[entity][2]}


def append_batch(connection, changes, *, actor, kind, clock, reverts=None):
    """Append one batch in the caller's write transaction and return its ID.

    `changes` holds (operation, entity, before, after) tuples, with before or
    after None for creates and deletes. All entries share one timestamp, which
    never runs behind the previous entry even if the system clock does.
    """
    actor_label(actor)
    if kind not in BATCH_KINDS or not changes:
        raise ValueError('An audit batch needs a known kind and at least one change.')
    last = connection.execute('SELECT seq, recorded_at, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1').fetchone()
    seq, previous = (last[0] + 1, last[2]) if last else (1, GENESIS)
    recorded_at = timestamp(clock())
    if last and recorded_at < last[1]:
        recorded_at = last[1]
    batch_id = f'B{seq:06d}'
    for operation, entity, before, after in changes:
        identifier = (after or before)[ENTITIES[entity][1]]
        entry = {'seq': seq, 'recorded_at': recorded_at, 'actor': actor, 'batch_id': batch_id, 'batch_kind': kind,
                 'reverts': reverts, 'operation': operation, 'entity': entity, 'entity_id': identifier,
                 'before': None if before is None else canonical(before),
                 'after': None if after is None else canonical(after), 'prev_hash': previous}
        entry['entry_hash'] = entry_hash(entry)
        connection.execute(f'INSERT INTO audit_log ({",".join(COLUMNS)}) VALUES ({",".join("?" * len(COLUMNS))})',
                           [entry[column] for column in COLUMNS])
        previous, seq = entry['entry_hash'], seq + 1
    return batch_id


def entries(connection, limit=None):
    sql = f'SELECT {",".join(COLUMNS)} FROM audit_log' + (' WHERE seq <= ?' if limit is not None else '') + ' ORDER BY seq'
    return [dict(zip(COLUMNS, row)) for row in connection.execute(sql, () if limit is None else (limit,))]


class HistoryError(Exception):
    def __init__(self, seq, code, message):
        super().__init__(message)
        self.seq, self.code = seq, code


def chain_problems(log):
    """Sequence, link, digest and time-order problems, in log order."""
    problems, expected, previous, last_time = [], 1, GENESIS, ''
    for entry in log:
        seq = entry['seq']
        if seq != expected:
            problems.append((seq, 'sequence_gap', f'Expected entry {expected} but found entry {seq}.'))
        if entry['prev_hash'] != previous:
            problems.append((seq, 'chain_break', 'The previous-entry digest does not match the entry before it.'))
        if entry_hash(entry) != entry['entry_hash']:
            problems.append((seq, 'hash_mismatch', 'The entry was changed after it was written.'))
        if not isinstance(entry['recorded_at'], str) or not TIMESTAMP.fullmatch(entry['recorded_at']) or entry['recorded_at'] < last_time:
            problems.append((seq, 'time_order', 'Timestamps must be UTC and never decrease.'))
        else:
            last_time = entry['recorded_at']
        expected, previous = seq + 1, entry['entry_hash']
    return problems


def replay(log):
    """Apply entries to an empty ledger. Every transition must match the state it changes."""
    state = {'session': {}, 'attendance': {}}
    for entry in log:
        try:
            before = None if entry['before'] is None else json.loads(entry['before'])
            after = None if entry['after'] is None else json.loads(entry['after'])
        except (TypeError, ValueError) as exc:
            raise HistoryError(entry['seq'], 'invalid_transition', 'Stored row values are not valid JSON.') from exc
        entity, key = entry['entity'], entry['entity_id']
        if entity not in state:
            raise HistoryError(entry['seq'], 'invalid_transition', 'Unknown entity type.')
        table, current = state[entity], state[entity].get(key)
        id_field = ENTITIES[entity][1]
        operation = entry['operation']
        valid = (
            (operation == 'create' and current is None and before is None and after is not None) or
            (operation == 'update' and current is not None and current == before and after is not None) or
            (operation == 'delete' and current is not None and current == before and after is None))
        if not valid or (after is not None and (after.get(id_field) != key or set(after) != set(ENTITIES[entity][2]))):
            raise HistoryError(entry['seq'], 'invalid_transition', f'The {operation} of {entity} {key} does not match the replayed state.')
        if entity == 'attendance' and after is not None and after['session_id'] not in state['session']:
            raise HistoryError(entry['seq'], 'invalid_transition', f'Attendance {key} references a session absent at that point.')
        if entity == 'session' and operation == 'delete' and any(row['session_id'] == key for row in state['attendance'].values()):
            raise HistoryError(entry['seq'], 'invalid_transition', f'Session {key} was deleted while attendance referenced it.')
        if after is None:
            del table[key]
        else:
            table[key] = after
    return state


def verified_state(connection, limit):
    """Replay entries 1..limit after checking that prefix; raise on any problem."""
    log = entries(connection, limit)
    problems = chain_problems(log)
    if problems:
        seq, code, _ = problems[0]
        raise ValidationError(f'Audit history fails verification at entry {seq} ({code}). Run verify before using past reports.')
    try:
        return replay(log)
    except HistoryError as exc:
        raise ValidationError(f'Audit history fails verification at entry {exc.seq} ({exc.code}). Run verify before using past reports.') from exc


def current_state(connection):
    state = {}
    for entity, (table, key, fields) in ENTITIES.items():
        state[entity] = {row[0]: dict(zip(fields, row)) for row in connection.execute(f'SELECT {",".join(fields)} FROM {table}')}
    return state


def head(connection):
    row = connection.execute('SELECT seq, recorded_at, entry_hash FROM audit_log ORDER BY seq DESC LIMIT 1').fetchone()
    return {'entry': row[0], 'recorded_at': row[1], 'hash': row[2]} if row else {'entry': 0, 'recorded_at': None, 'hash': GENESIS}


def verify(connection, expect_head=None):
    """Check protections, the chain, batch structure, replay and the current tables."""
    problems = []

    def add(seq, code, message):
        problems.append({'entry': seq, 'code': code, 'message': message})

    if not connection.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'audit_log'").fetchone():
        add(None, 'no_history', 'This ledger has no audit log. Open it once with this version to record a baseline batch.')
        return {'valid': False, 'entries': 0, 'batches': 0, 'head': None, 'protections': [], 'problems': problems, 'problems_total': 1}
    present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'audit_log'")}
    for name in TRIGGERS:
        if name not in present:
            add(None, 'protection_removed', f'Append-only trigger {name} is missing.')
    log = entries(connection)
    for seq, code, message in chain_problems(log):
        add(seq, code, message)
    batches, first = {}, {}
    for index, entry in enumerate(log):
        signature = (entry['recorded_at'], entry['actor'], entry['batch_kind'], entry['reverts'])
        if entry['batch_id'] in batches:
            if batches[entry['batch_id']] != signature or log[index - 1]['batch_id'] != entry['batch_id']:
                add(entry['seq'], 'batch_structure', 'Entries of one batch must be contiguous and share time, actor and kind.')
        else:
            batches[entry['batch_id']], first[entry['batch_id']] = signature, entry['seq']
            if entry['batch_id'] != f"B{entry['seq']:06d}":
                add(entry['seq'], 'batch_structure', 'A batch ID must name its first entry.')
    try:
        replayed = replay(log)
    except HistoryError as exc:
        add(exc.seq, exc.code, str(exc))
    else:
        actual = current_state(connection)
        for entity in ENTITIES:
            differing = sum(replayed[entity].get(key) != actual[entity].get(key) for key in set(replayed[entity]) | set(actual[entity]))
            if differing:
                add(None, 'state_mismatch', f'{differing} {entity} record(s) differ from the replayed history: a table changed outside the audit log.')
    current = head(connection)
    if expect_head is not None and expect_head != current['hash']:
        add(current['entry'], 'head_mismatch', 'The latest entry digest differs from the expected head.')
    return {'valid': not problems, 'entries': len(log), 'batches': len(batches), 'head': current,
            'protections': sorted(present & set(TRIGGERS)), 'problems': problems[:MAX_PROBLEMS],
            'problems_total': len(problems)}


def resolve_as_of(connection, as_of=None, as_of_entry=None):
    """Map a UTC timestamp, a date (end of that UTC day) or an entry number to a log prefix."""
    if as_of is not None and as_of_entry is not None:
        raise ValidationError('Use either as_of or as_of_entry, not both.')
    latest = head(connection)['entry']
    if as_of_entry is not None:
        if isinstance(as_of_entry, str):
            if not re.fullmatch(r'(?:0|[1-9]\d{0,9})', as_of_entry):
                raise ValidationError('as_of_entry must be a whole number.')
            as_of_entry = int(as_of_entry)
        if not isinstance(as_of_entry, int) or isinstance(as_of_entry, bool) or not 0 <= as_of_entry <= latest:
            raise ValidationError(f'as_of_entry must be from 0 to {latest}, the latest entry.')
        limit, requested = as_of_entry, {'entry': as_of_entry}
    else:
        if not isinstance(as_of, str):
            raise ValidationError('as_of must be a UTC timestamp or a date.')
        moment = parse_as_of(as_of)
        row = connection.execute('SELECT MAX(seq) FROM audit_log WHERE recorded_at <= ?', (moment,)).fetchone()
        limit, requested = row[0] or 0, {'timestamp': moment}
    row = connection.execute('SELECT recorded_at, entry_hash FROM audit_log WHERE seq = ?', (limit,)).fetchone()
    return {'requested': requested, 'entry': limit, 'recorded_at': row[0] if row else None, 'hash': row[1] if row else GENESIS}


def parse_as_of(value):
    """YYYY-MM-DD means the end of that UTC day; full timestamps must end in Z."""
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
        try:
            datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValidationError('as_of date does not exist.') from exc
        return value + 'T23:59:59.999999Z'
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d{1,6}))?Z', value)
    if not match:
        raise ValidationError('as_of must be YYYY-MM-DD or a UTC timestamp such as 2026-09-30T23:59:59Z.')
    try:
        datetime.fromisoformat(match.group(1))
    except ValueError as exc:
        raise ValidationError('as_of timestamp does not exist.') from exc
    return f'{match.group(1)}.{(match.group(2) or "").ljust(6, "0")}Z'
