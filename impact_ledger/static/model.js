function assertSafeInteger(value) {
    if (!Number.isSafeInteger(value))
        throw new Error('Static calculation exceeds safe integer limits.');
}
function ratio(numerator, denominator, multiplier = 1) {
    if (!denominator)
        return null;
    assertSafeInteger(numerator);
    assertSafeInteger(denominator);
    const sign = numerator < 0 ? -1 : 1;
    const scaled = BigInt(Math.abs(numerator)) * BigInt(multiplier) * 100n;
    const divisor = BigInt(denominator);
    const quotient = scaled / divisor;
    const rounded = quotient + (2n * (scaled % divisor) >= divisor ? 1n : 0n);
    if (rounded > BigInt(Number.MAX_SAFE_INTEGER))
        throw new Error('Static ratio exceeds safe integer limits.');
    return sign * Number(rounded) / 100;
}
function hundredthTotals(rows) {
    const budget = rows.reduce((sum, row) => sum + row.budget_cents, 0);
    const actual = rows.reduce((sum, row) => sum + row.actual_cents, 0);
    const units = {
        participant_hours: rows.reduce((sum, row) => sum + row.duration_hundredths * row.participants.length, 0),
        session_hours: rows.reduce((sum, row) => sum + row.duration_hundredths, 0),
        budget, actual, variance: actual - budget,
    };
    for (const value of Object.values(units))
        assertSafeInteger(value);
    return units;
}
function summarize(rows) {
    const people = new Set(rows.flatMap(row => row.participants));
    const attendance = rows.reduce((sum, row) => sum + row.participants.length, 0);
    const budget = rows.reduce((sum, row) => sum + row.budget_cents, 0);
    const actual = rows.reduce((sum, row) => sum + row.actual_cents, 0);
    const participantHundredths = rows.reduce((sum, row) => sum + row.duration_hundredths * row.participants.length, 0);
    const sessionHundredths = rows.reduce((sum, row) => sum + row.duration_hundredths, 0);
    for (const value of [attendance, budget, actual, participantHundredths, sessionHundredths])
        assertSafeInteger(value);
    return {
        sessions: rows.length, unique_participants: people.size, attendance,
        participant_hours: participantHundredths / 100,
        session_hours: sessionHundredths / 100,
        budget: budget / 100, actual: actual / 100, variance: (actual - budget) / 100,
        variance_percent: ratio(actual - budget, budget, 100),
        attendance_per_participant: ratio(attendance, people.size),
    };
}
function filterRows(snapshot, filters) {
    for (const value of [filters.start, filters.end]) {
        if (value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || value.startsWith('0000') || Number.isNaN(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) {
            throw new Error('Enter a valid date in YYYY-MM-DD format.');
        }
    }
    if (filters.start && filters.end && filters.start > filters.end)
        throw new Error('Start date must be on or before end date.');
    const program = filters.program;
    // Match Python str.strip whitespace and codepoint length (JS trim/length differ).
    if (program && (/^[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]|[\u0009-\u000d\u001c-\u0020\u0085\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]$/u.test(program) || [...program].length > 80 || /^[=+@-]/.test(program) || /[\u0000-\u001f\u007f\ud800-\udfff]/u.test(program))) {
        throw new Error('Program must be a valid label with 1–80 characters.');
    }
    return snapshot.sessions.filter(row => (!filters.start || row.session_date >= filters.start) &&
        (!filters.end || row.session_date <= filters.end) && (!filters.program || row.program === filters.program));
}
export function comparisonFromSnapshot(snapshot, filters) {
    if (!filters.start || !filters.end)
        throw new Error('Comparison requires both start and end dates. Set both dates and apply filters.');
    const rows = filterRows(snapshot, filters);
    const program = filters.program;
    // ISO dates and UTC day numbers have no dependence on local time or DST.
    const day = 86400000;
    const first = Date.parse(filters.start + 'T00:00:00Z');
    const last = Date.parse(filters.end + 'T00:00:00Z');
    const days = (last - first) / day + 1;
    if (first - days * day < Date.parse('0001-01-01T00:00:00Z')) {
        throw new Error('Previous period would start before 0001-01-01. Choose a later or shorter range.');
    }
    const previousStart = new Date(first - days * day).toISOString().slice(0, 10);
    const previousEnd = new Date(first - day).toISOString().slice(0, 10);
    const current = summarize(rows);
    const previousRows = filterRows(snapshot, { start: previousStart, end: previousEnd, program: program ?? null });
    const previous = summarize(previousRows);
    const currentExact = hundredthTotals(rows), previousExact = hundredthTotals(previousRows);
    const deltas = {};
    for (const key of ['sessions', 'unique_participants', 'attendance'])
        deltas[key] = current[key] - previous[key];
    for (const key of ['participant_hours', 'session_hours', 'budget', 'actual', 'variance']) {
        const currentUnits = currentExact[key], previousUnits = previousExact[key];
        assertSafeInteger(currentUnits);
        assertSafeInteger(previousUnits);
        const units = BigInt(currentUnits) - BigInt(previousUnits);
        if (units > BigInt(Number.MAX_SAFE_INTEGER) || units < -BigInt(Number.MAX_SAFE_INTEGER))
            throw new Error('Static calculation exceeds safe integer limits.');
        deltas[key] = Number(units) / 100;
    }
    return { synthetic: true, currency: 'USD', filters: { start: filters.start, end: filters.end, program: program || null }, days,
        current: { start: filters.start, end: filters.end, totals: current },
        previous: { start: previousStart, end: previousEnd, totals: previous }, deltas };
}
export function summaryFromSnapshot(snapshot, filters) {
    const rows = filterRows(snapshot, filters);
    const programs = [...new Set(rows.map(row => row.program))].sort();
    const months = [...new Set(rows.map(row => row.session_date.slice(0, 7)))].sort();
    return {
        synthetic: true, currency: 'USD', filters, totals: summarize(rows),
        programs: programs.map(program => ({ program, ...summarize(rows.filter(row => row.program === program)) })),
        monthly: months.map(month => ({ month, ...summarize(rows.filter(row => row.session_date.startsWith(month))) })),
        sessions: rows.map(row => ({ session_id: row.session_id, program: row.program, session_date: row.session_date,
            duration_hours: row.duration_hundredths / 100, attendance: row.participants.length,
            participant_hours: row.duration_hundredths * row.participants.length / 100,
            budget: row.budget_cents / 100, actual: row.actual_cents / 100, variance: (row.actual_cents - row.budget_cents) / 100 })),
    };
}
export function metadataFromSnapshot(snapshot) {
    const days = snapshot.sessions.map(row => row.session_date).sort();
    return { synthetic: true, currency: 'USD', programs: [...new Set(snapshot.sessions.map(row => row.program))].sort(),
        start: days[0] ?? null, end: days.at(-1) ?? null, sessions: snapshot.sessions.length,
        attendance: snapshot.sessions.reduce((sum, row) => sum + row.participants.length, 0) };
}
export function csvFromSnapshot(kind, snapshot, filters) {
    const rows = filterRows(snapshot, filters);
    const headers = kind === 'sessions' ? ['session_id', 'program', 'session_date', 'duration_hours', 'budget', 'actual'] : ['attendance_id', 'session_id', 'participant_id'];
    const records = kind === 'sessions'
        ? rows.map(row => [row.session_id, row.program, row.session_date, (row.duration_hundredths / 100).toFixed(2), (row.budget_cents / 100).toFixed(2), (row.actual_cents / 100).toFixed(2)])
        : rows.flatMap(row => row.attendance_records.map(person => [person.attendance_id, row.session_id, person.participant_id])).sort((a, b) => (a[0] ?? '') < (b[0] ?? '') ? -1 : 1);
    return [headers, ...records].map(row => row.map(cell => /[",\r\n]/.test(cell) ? `"${cell.replaceAll('"', '""')}"` : cell).join(',')).join('\r\n') + '\r\n';
}
