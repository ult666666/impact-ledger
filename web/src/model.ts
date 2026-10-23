/** Exact integer accounting for the read-only static preview. */
export interface Filters { start?: string | null; end?: string | null; program?: string | null }
export interface Session {
  session_id: string; program: string; session_date: string;
  duration_hundredths: number; budget_cents: number; actual_cents: number;
  participants: string[];
  attendance_records: {attendance_id: string; participant_id: string}[];
}
export interface Snapshot { synthetic: true; currency: 'USD'; sessions: Session[] }
export interface Totals {
  sessions: number; unique_participants: number; attendance: number;
  participant_hours: number; session_hours: number; budget: number; actual: number;
  variance: number; variance_percent: number | null; attendance_per_participant: number | null;
}
export interface SessionSummary {
  session_id: string; program: string; session_date: string; duration_hours: number;
  attendance: number; participant_hours: number; budget: number; actual: number; variance: number;
}
export interface Summary {
  synthetic: true; currency: 'USD'; filters: Filters; totals: Totals;
  programs: (Totals & {program: string})[];
  monthly: (Totals & {month: string})[];
  sessions: SessionSummary[];
}
export interface Metadata {
  synthetic: true; currency: 'USD'; programs: string[];
  start: string | null; end: string | null; sessions: number; attendance: number;
}

function assertSafeInteger(value: number): void {
  if (!Number.isSafeInteger(value)) throw new Error('Static calculation exceeds safe integer limits.');
}

function ratio(numerator: number, denominator: number, multiplier = 1): number | null {
  if (!denominator) return null;
  assertSafeInteger(numerator);
  assertSafeInteger(denominator);
  const sign = numerator < 0 ? -1 : 1;
  const scaled = BigInt(Math.abs(numerator)) * BigInt(multiplier) * 100n;
  const divisor = BigInt(denominator);
  const quotient = scaled / divisor;
  const rounded = quotient + (2n * (scaled % divisor) >= divisor ? 1n : 0n);
  if (rounded > BigInt(Number.MAX_SAFE_INTEGER)) throw new Error('Static ratio exceeds safe integer limits.');
  return sign * Number(rounded) / 100;
}

function summarize(rows: Session[]): Totals {
  const people = new Set(rows.flatMap(row => row.participants));
  const attendance = rows.reduce((sum, row) => sum + row.participants.length, 0);
  const budget = rows.reduce((sum, row) => sum + row.budget_cents, 0);
  const actual = rows.reduce((sum, row) => sum + row.actual_cents, 0);
  const participantHundredths = rows.reduce((sum, row) => sum + row.duration_hundredths * row.participants.length, 0);
  const sessionHundredths = rows.reduce((sum, row) => sum + row.duration_hundredths, 0);
  for (const value of [attendance, budget, actual, participantHundredths, sessionHundredths]) assertSafeInteger(value);
  return {
    sessions: rows.length, unique_participants: people.size, attendance,
    participant_hours: participantHundredths / 100,
    session_hours: sessionHundredths / 100,
    budget: budget / 100, actual: actual / 100, variance: (actual - budget) / 100,
    variance_percent: ratio(actual - budget, budget, 100),
    attendance_per_participant: ratio(attendance, people.size),
  };
}

function filterRows(snapshot: Snapshot, filters: Filters): Session[] {
  for (const value of [filters.start, filters.end]) {
    if (value && (!/^\d{4}-\d{2}-\d{2}$/.test(value) || Number.isNaN(Date.parse(value)) || new Date(value).toISOString().slice(0, 10) !== value)) {
      throw new Error('Enter a valid date in YYYY-MM-DD format.');
    }
  }
  if (filters.start && filters.end && filters.start > filters.end) throw new Error('Start date must be on or before end date.');
  return snapshot.sessions.filter(row => (!filters.start || row.session_date >= filters.start) &&
    (!filters.end || row.session_date <= filters.end) && (!filters.program || row.program === filters.program));
}

export function summaryFromSnapshot(snapshot: Snapshot, filters: Filters): Summary {
  const rows = filterRows(snapshot, filters);
  const programs = [...new Set(rows.map(row => row.program))].sort();
  const months = [...new Set(rows.map(row => row.session_date.slice(0, 7)))].sort();
  return {
    synthetic: true, currency: 'USD', filters, totals: summarize(rows),
    programs: programs.map(program => ({program, ...summarize(rows.filter(row => row.program === program))})),
    monthly: months.map(month => ({month, ...summarize(rows.filter(row => row.session_date.startsWith(month)))})),
    sessions: rows.map(row => ({session_id: row.session_id, program: row.program, session_date: row.session_date,
      duration_hours: row.duration_hundredths / 100, attendance: row.participants.length,
      participant_hours: row.duration_hundredths * row.participants.length / 100,
      budget: row.budget_cents / 100, actual: row.actual_cents / 100, variance: (row.actual_cents - row.budget_cents) / 100})),
  };
}

export function metadataFromSnapshot(snapshot: Snapshot): Metadata {
  const days = snapshot.sessions.map(row => row.session_date).sort();
  return {synthetic: true, currency: 'USD', programs: [...new Set(snapshot.sessions.map(row => row.program))].sort(),
    start: days[0] ?? null, end: days.at(-1) ?? null, sessions: snapshot.sessions.length,
    attendance: snapshot.sessions.reduce((sum, row) => sum + row.participants.length, 0)};
}

export function csvFromSnapshot(kind: 'sessions' | 'attendance', snapshot: Snapshot, filters: Filters): string {
  const rows = filterRows(snapshot, filters);
  const headers = kind === 'sessions' ? ['session_id', 'program', 'session_date', 'duration_hours', 'budget', 'actual'] : ['attendance_id', 'session_id', 'participant_id'];
  const records = kind === 'sessions'
    ? rows.map(row => [row.session_id, row.program, row.session_date, (row.duration_hundredths / 100).toFixed(2), (row.budget_cents / 100).toFixed(2), (row.actual_cents / 100).toFixed(2)])
    : rows.flatMap(row => row.attendance_records.map(person => [person.attendance_id, row.session_id, person.participant_id])).sort((a, b) => (a[0] ?? '') < (b[0] ?? '') ? -1 : 1);
  return [headers, ...records].map(row => row.map(cell => /[",\r\n]/.test(cell) ? `"${cell.replaceAll('"', '""')}"` : cell).join(',')).join('\r\n') + '\r\n';
}
