"""Bounded CSV validation shared by advisory preview and atomic import.

All messages describe rules, never echo file values. Database checks use the
caller's transaction; this module issues SELECTs only.
"""
import csv
from datetime import date
from decimal import Decimal, InvalidOperation
import io
import re

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



MAX_ERRORS = 100


def validate_csv(kind, payload, connection):
    """Return public diagnostics and validated tuples; never write to the ledger."""
    if kind not in HEADERS:
        raise ValidationError('Import kind must be sessions or attendance.')
    result = {'kind': kind, 'valid': False, 'rows': 0, 'errors': [],
              'errors_truncated': False, 'errors_total': 0}
    parsed_rows = []

    def error(row, field, code, message):
        result['errors_total'] += 1
        item = {'row': row, 'field': field, 'code': code, 'message': message}
        if len(result['errors']) < MAX_ERRORS:
            result['errors'].append(item)
        elif row is None:
            # Keep a terminal file/limit error visible even after many row errors.
            result['errors'][-1] = item
        result['errors_truncated'] = result['errors_total'] > MAX_ERRORS

    if len(payload) > MAX_BYTES:
        error(None, None, 'too_large', 'CSV exceeds the 1 MiB limit.')
        return result, parsed_rows
    try:
        content = payload.decode('utf-8-sig')
    except UnicodeDecodeError:
        error(None, None, 'encoding', 'CSV must be valid UTF-8.')
        return result, parsed_rows
    validators = [identifier, program_label, valid_date,
                  lambda value: scaled(value, 'Duration hours', Decimal(24), False),
                  lambda value: scaled(value, 'Budget', Decimal(10000000)),
                  lambda value: scaled(value, 'Actual', Decimal(10000000))] if kind == 'sessions' else [identifier] * 3
    ids, pairs = set(), set()
    try:
        reader = csv.reader(io.StringIO(content, newline=''), strict=True)
        if next(reader, None) != HEADERS[kind]:
            error(None, None, 'headers', 'CSV headers must exactly match: ' + ','.join(HEADERS[kind]))
            return result, parsed_rows
        while True:
            line = reader.line_num + 1
            row = next(reader, None)
            if row is None:
                break
            if result['rows'] >= MAX_ROWS:
                error(None, None, 'row_limit', 'CSV exceeds the 5,000 data-row limit.')
                break
            result['rows'] += 1
            if len(row) != len(HEADERS[kind]):
                error(line, None, 'columns', 'Wrong number of columns.')
                continue
            before = result['errors_total']
            parsed = []
            for field, value, validator in zip(HEADERS[kind], row, validators):
                try:
                    parsed.append(validator(value))
                except ValidationError as exc:
                    parsed.append(None)
                    error(line, field, 'invalid_value', str(exc))
            primary = parsed[0]
            if primary is not None:
                # Table/column names come only from the closed HEADERS mapping.
                exists = connection.execute(f'SELECT 1 FROM {kind} WHERE {HEADERS[kind][0]} = ?', (primary,)).fetchone()
                if primary in ids or exists:
                    error(line, HEADERS[kind][0], 'duplicate_id', 'ID already exists in the ledger or earlier in this file.')
                ids.add(primary)
            if kind == 'attendance':
                session, participant = parsed[1:]
                if session is not None:
                    if not connection.execute('SELECT 1 FROM sessions WHERE session_id = ?', (session,)).fetchone():
                        error(line, 'session_id', 'missing_session', 'Session does not exist. Import sessions first.')
                    if participant is not None:
                        pair = (session, participant)
                        exists = connection.execute('SELECT 1 FROM attendance WHERE session_id = ? AND participant_id = ?', pair).fetchone()
                        if pair in pairs or exists:
                            error(line, 'participant_id', 'duplicate_pair', 'Participant/session pair already exists in the ledger or earlier in this file.')
                        pairs.add(pair)
            if result['errors_total'] == before:
                parsed_rows.append(tuple(parsed))
    except csv.Error:
        error(None, None, 'malformed_csv', 'Malformed CSV quoting or field size.')
    if result['rows'] == 0 and result['errors_total'] == 0:
        error(None, None, 'empty', 'CSV must contain at least one data row.')
    result['valid'] = result['errors_total'] == 0
    return result, parsed_rows
