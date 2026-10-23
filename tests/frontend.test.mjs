import {test} from 'node:test';
import assert from 'node:assert/strict';
import {summaryFromSnapshot, csvFromSnapshot} from '../impact_ledger/static/model.js';

const snapshot = {synthetic: true, currency: 'USD', sessions: [
  {session_id: 's1', program: 'Learning Lab', session_date: '2026-01-10', duration_hundredths: 150, budget_cents: 10010, actual_cents: 8005, participants: ['p1', 'p2'], attendance_records: [{attendance_id: 'a1', participant_id: 'p1'}, {attendance_id: 'a2', participant_id: 'p2'}]},
  {session_id: 's2', program: 'Learning Lab', session_date: '2026-02-10', duration_hundredths: 200, budget_cents: 5000, actual_cents: 7500, participants: ['p1'], attendance_records: [{attendance_id: 'a3', participant_id: 'p1'}]},
  {session_id: 's3', program: 'Community Kitchen', session_date: '2026-02-20', duration_hundredths: 300, budget_cents: 0, actual_cents: 2000, participants: ['p3'], attendance_records: [{attendance_id: 'a4', participant_id: 'p3'}]},
  {session_id: 's4', program: 'Empty Session', session_date: '2026-02-21', duration_hundredths: 100, budget_cents: 3000, actual_cents: 0, participants: [], attendance_records: []},
]};

test('static metrics use session spending and distinct participants', () => {
  assert.deepEqual(summaryFromSnapshot(snapshot, {}).totals, {
    sessions: 4, unique_participants: 3, attendance: 4, participant_hours: 8,
    session_hours: 7.5, budget: 180.1, actual: 175.05, variance: -5.05,
    variance_percent: -2.8, attendance_per_participant: 1.33,
  });
});
test('static inclusive filters constrain all measures together', () => {
  const filtered = summaryFromSnapshot(snapshot, {start: '2026-02-10', end: '2026-02-10', program: 'Learning Lab'});
  assert.equal(filtered.totals.attendance, 1);
  assert.equal(filtered.totals.budget, 50);
  assert.equal(filtered.totals.variance_percent, 50);
  assert.equal(filtered.sessions.length, 1);
});
test('static empty and zero-budget rates are undefined', () => {
  const empty = summaryFromSnapshot(snapshot, {program: 'Missing'});
  assert.equal(empty.totals.attendance, 0);
  assert.equal(empty.totals.attendance_per_participant, null);
  assert.equal(empty.totals.variance_percent, null);
  assert.deepEqual(empty.monthly, []);
  assert.equal(summaryFromSnapshot(snapshot, {program: 'Community Kitchen'}).totals.variance_percent, null);
});
test('static month and program subtotals count people within each group', () => {
  const summary = summaryFromSnapshot(snapshot, {});
  assert.equal(summary.monthly[0].month, '2026-01');
  assert.equal(summary.monthly[1].unique_participants, 2);
  assert.equal(summary.programs.find(p => p.program === 'Learning Lab').unique_participants, 2);
});
test('static session CSV quotes data and preserves exact decimal units', () => {
  const csv = csvFromSnapshot('sessions', snapshot, {start: '2026-02-10', end: '2026-02-10'});
  assert.equal(csv, 'session_id,program,session_date,duration_hours,budget,actual\r\ns2,Learning Lab,2026-02-10,2.00,50.00,75.00\r\n');
  const special = structuredClone(snapshot);
  special.sessions[0].program = 'Lab, "社区"';
  assert.ok(csvFromSnapshot('sessions', special, {}).includes('"Lab, ""社区"""'));
});
test('static attendance export retains original attendance IDs and filters', () => {
  assert.equal(csvFromSnapshot('attendance', snapshot, {program: 'Community Kitchen'}), 'attendance_id,session_id,participant_id\r\na4,s3,p3\r\n');
});
test('static filters reject invalid and reversed dates', () => {
  for (const filters of [{start: '0000-01-01'}, {start: '2026-2-01'}, {start: '2026-02-30'}, {start: '2026-02-01', end: '2026-01-01'}]) {
    assert.throws(() => summaryFromSnapshot(snapshot, filters));
  }
});

test('static percentage rounds positive and negative exact half ties away from zero', () => {
  for (const [actual, expected] of [[20201, 1.01], [19799, -1.01]]) {
    const fixture = structuredClone(snapshot);
    fixture.sessions = [fixture.sessions[0]];
    fixture.sessions[0].budget_cents = 20000;
    fixture.sessions[0].actual_cents = actual;
    assert.equal(summaryFromSnapshot(fixture, {}).totals.variance_percent, expected);
  }
});

test('static aggregation refuses totals outside the exact integer range', () => {
  const fixture = structuredClone(snapshot);
  fixture.sessions[0].budget_cents = Number.MAX_SAFE_INTEGER;
  assert.throws(() => summaryFromSnapshot(fixture, {}), /safe integer/i);
});

test('static comparison matches the shared Python calendar and exact accounting oracle', async () => {
  const {readFile} = await import('node:fs/promises');
  const model = await import('../impact_ledger/static/model.js');
  assert.equal(typeof model.comparisonFromSnapshot, 'function');
  const fixture = JSON.parse(await readFile(new URL('./fixtures/comparison.json', import.meta.url), 'utf8'));
  for (const item of fixture.cases) assert.deepEqual(model.comparisonFromSnapshot(fixture.snapshot, item.filters), item.expected, item.name);
});

test('static comparison rejects shared absent, invalid, reversed and underflow ranges', async () => {
  const {readFile} = await import('node:fs/promises');
  const model = await import('../impact_ledger/static/model.js');
  assert.equal(typeof model.comparisonFromSnapshot, 'function');
  const fixture = JSON.parse(await readFile(new URL('./fixtures/comparison.json', import.meta.url), 'utf8'));
  for (const filters of fixture.invalid_filters) assert.throws(() => model.comparisonFromSnapshot(fixture.snapshot, filters), undefined, JSON.stringify(filters));
});

test('comparison subtracts integer cents before JSON conversion at large exact totals', async () => {
  const {comparisonFromSnapshot} = await import('../impact_ledger/static/model.js');
  const fixture = structuredClone(snapshot);
  const previous = {...fixture.sessions[0], session_date: '2026-01-01', budget_cents: 9007199254740962, actual_cents: 0};
  const current = {...previous, session_date: '2026-01-02', budget_cents: 9007199254740963};
  fixture.sessions = [previous, current];
  assert.equal(comparisonFromSnapshot(fixture, {start: '2026-01-02', end: '2026-01-02'}).deltas.budget, 0.01);
});

test('all static filter paths reject invalid program labels consistently with the local store', () => {
  for (const program of ['=Formula', '\u0085Lab', 'Lab ', '🌱'.repeat(81), '\ud800']) {
    assert.throws(() => summaryFromSnapshot(snapshot, {program}));
    assert.throws(() => csvFromSnapshot('sessions', snapshot, {program}));
  }
  assert.equal(summaryFromSnapshot(snapshot, {program: '🌱'.repeat(80)}).totals.sessions, 0);
});
