import { comparisonFromSnapshot, csvFromSnapshot, metadataFromSnapshot, summaryFromSnapshot } from './model.js';
function element(id) {
    const found = document.getElementById(id);
    if (!found)
        throw new Error(`Missing interface element: ${id}`);
    return found;
}
const setText = (id, value) => { element(id).textContent = value; };
const number = (value) => new Intl.NumberFormat('en-US', { maximumFractionDigits: 2 }).format(value);
const money = (value) => new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 0, maximumFractionDigits: 2 }).format(value);
const dateLabel = (value) => new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', year: 'numeric', timeZone: 'UTC' }).format(new Date(value + 'T00:00:00Z'));
const monthLabel = (value) => new Intl.DateTimeFormat('en-US', { month: 'short', year: 'numeric', timeZone: 'UTC' }).format(new Date(value + '-01T00:00:00Z'));
const isStatic = document.documentElement.dataset.mode === 'static';
const colors = ['#718b59', '#365e4c', '#b5bf88', '#879d7a', '#768f95'];
let snapshot = null;
let metadata = null;
let appliedFilters = {};
let submittedFilters = {};
let summaryState = 'pending';
let comparisonState = 'disabled';
let importPending = false;
let previewPending = false;
let previewRevision = 0;
let requestRevision = 0;
let comparisonRevision = 0;
const measures = [
    { key: 'sessions', label: 'Sessions' }, { key: 'unique_participants', label: 'Unique participants' },
    { key: 'attendance', label: 'Attendance' }, { key: 'participant_hours', label: 'Participant hours' },
    { key: 'session_hours', label: 'Session hours' }, { key: 'budget', label: 'Budget', currency: true },
    { key: 'actual', label: 'Actual', currency: true }, { key: 'variance', label: 'Variance (actual − budget)', currency: true },
];
function measureValue(value, currency = false, signed = false) {
    return `${signed && value > 0 ? '+' : value < 0 ? '−' : ''}${currency ? money(Math.abs(value)) : number(Math.abs(value))}`;
}
function updateReportReadiness() {
    let reason = '';
    if (summaryState === 'pending')
        reason = 'Print report is unavailable while the current view loads.';
    else if (summaryState === 'error')
        reason = 'Print report is unavailable because the current view could not load. Apply filters again.';
    else if (importPending)
        reason = 'Print report is unavailable while imported data refreshes.';
    else if (element('compare-prior').checked && comparisonState === 'pending')
        reason = 'Print report is unavailable while the prior-period comparison loads.';
    element('print-report').disabled = reason !== '';
    setText('report-status', reason);
    element('report-status').hidden = reason === '';
}
function clearComparison(message) {
    ++comparisonRevision;
    element('comparison-panel').hidden = true;
    element('comparison-body').replaceChildren();
    setText('comparison-status', message);
    comparisonState = element('compare-prior').checked ? 'pending' : 'disabled';
    updateReportReadiness();
}
async function refreshComparison() {
    const enabled = element('compare-prior').checked;
    clearComparison(enabled ? 'Updating comparison for the applied filters…' : 'Compare the immediately preceding equal-duration period using applied filters.');
    if (!enabled)
        return;
    if (summaryState !== 'ready') {
        setText('comparison-status', 'Comparison waits for the submitted view to finish loading.');
        return;
    }
    const revision = comparisonRevision;
    const filters = { ...appliedFilters };
    try {
        if (!filters.start || !filters.end)
            throw new Error('Comparison requires both start and end dates. Set both dates and apply filters.');
        const result = isStatic && snapshot ? comparisonFromSnapshot(snapshot, filters) : await json('./api/comparison?' + query(filters));
        if (revision !== comparisonRevision)
            return;
        setText('comparison-ranges', `Current: ${result.current.start} – ${result.current.end} · Previous: ${result.previous.start} – ${result.previous.end} · ${result.days} days each`);
        const body = element('comparison-body');
        for (const measure of measures)
            tableRow(body, [measure.label, measureValue(result.current.totals[measure.key], measure.currency), measureValue(result.previous.totals[measure.key], measure.currency), measureValue(result.deltas[measure.key], measure.currency, true)]);
        element('comparison-panel').hidden = false;
        comparisonState = 'ready';
        setText('comparison-status', 'Comparison reflects the applied dates and program. Delta = current − previous.');
    }
    catch (error) {
        if (revision !== comparisonRevision)
            return;
        comparisonState = 'unavailable';
        setText('comparison-status', 'Comparison unavailable: ' + (error instanceof Error ? error.message : 'Apply your filters again.'));
    }
    finally {
        if (revision === comparisonRevision)
            updateReportReadiness();
    }
}
function renderReportTotals(totals) {
    const body = element('report-totals-body');
    body.replaceChildren();
    for (const measure of measures)
        tableRow(body, [measure.label, measureValue(totals[measure.key], measure.currency)]);
}
async function json(url, options) {
    const response = await fetch(url, options);
    const result = await response.json();
    if (!response.ok)
        throw new Error(result.error ?? `Request failed (${response.status}).`);
    return result;
}
function query(filters) {
    const params = new URLSearchParams();
    for (const [key, value] of Object.entries(filters))
        if (value)
            params.set(key, value);
    return params.toString();
}
function readFilters() {
    const start = element('start-date').value;
    const end = element('end-date').value;
    if (start && end && start > end)
        throw new Error('Start date must be on or before end date.');
    return { start: start || null, end: end || null, program: element('program-filter').value || null };
}
function showError(error) {
    setText('app-error', error instanceof Error ? error.message : 'Something went wrong. Please try again.');
    element('app-error').hidden = false;
}
function tableRow(body, values) {
    const row = document.createElement('tr');
    for (const value of values) {
        const cell = document.createElement('td');
        cell.textContent = value;
        row.append(cell);
    }
    body.append(row);
    return row;
}
function svgNode(name, attrs, text) {
    const node = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [key, value] of Object.entries(attrs))
        node.setAttribute(key, String(value));
    if (text !== undefined)
        node.textContent = text;
    return node;
}
function renderAttendance(summary) {
    const container = element('attendance-chart');
    container.replaceChildren();
    const rows = summary.monthly;
    const width = 500, height = 200, left = 28, top = 20, bottom = 27, chartHeight = height - top - bottom;
    const max = Math.max(1, ...rows.map(row => row.attendance));
    const ceiling = Math.max(4, Math.ceil(max / 4) * 4);
    const svg = svgNode('svg', { viewBox: `0 0 ${width} ${height}`, 'aria-hidden': 'true' });
    for (let tick = 0; tick <= 4; tick++) {
        const value = ceiling * tick / 4;
        const y = height - bottom - chartHeight * tick / 4;
        svg.append(svgNode('line', { x1: left, y1: y, x2: width - 5, y2: y, class: 'chart-gridline' }));
        svg.append(svgNode('text', { x: left - 9, y: y + 3, 'text-anchor': 'end', class: 'chart-label' }, String(value)));
    }
    const step = (width - left - 6) / Math.max(1, rows.length);
    rows.forEach((row, index) => {
        const barWidth = Math.min(68, step * 0.45);
        const barHeight = row.attendance / ceiling * chartHeight;
        const x = left + step * (index + 0.5);
        svg.append(svgNode('rect', { x: x - barWidth / 2, y: height - bottom - barHeight, width: barWidth, height: barHeight, rx: 3, class: index === rows.length - 1 ? 'chart-bar-highlight' : 'chart-bar' }));
        svg.append(svgNode('text', { x, y: height - bottom - barHeight - 8, 'text-anchor': 'middle', class: 'chart-value' }, number(row.attendance)));
        // Long time ranges remain legible by labeling up to six evenly spaced ticks.
        if (rows.length <= 6 || index % Math.ceil(rows.length / 6) === 0 || index === rows.length - 1) {
            svg.append(svgNode('text', { x, y: height - 5, 'text-anchor': 'middle', class: 'chart-label' }, monthLabel(row.month)));
        }
    });
    container.append(svg);
    const body = element('monthly-body');
    body.replaceChildren();
    for (const row of rows)
        tableRow(body, [monthLabel(row.month), number(row.attendance), number(row.unique_participants), number(row.participant_hours)]);
}
function renderPrograms(summary) {
    const container = element('program-chart');
    const body = element('program-body');
    container.replaceChildren();
    body.replaceChildren();
    summary.programs.forEach((row, index) => {
        const share = summary.totals.attendance ? row.attendance / summary.totals.attendance * 100 : 0;
        const item = document.createElement('div');
        item.className = 'program-item';
        const line = document.createElement('div');
        line.className = 'program-row';
        const label = document.createElement('div');
        const name = document.createElement('span');
        name.className = 'program-label';
        name.textContent = row.program;
        label.append(name);
        const value = document.createElement('strong');
        value.textContent = number(row.attendance);
        const percentage = document.createElement('span');
        percentage.className = 'program-share';
        percentage.textContent = `${number(share)}%`;
        value.append(percentage);
        line.append(label, value);
        const track = svgNode('svg', { viewBox: '0 0 300 6', preserveAspectRatio: 'none', class: 'program-track', 'aria-hidden': 'true' });
        track.append(svgNode('rect', { x: 0, y: 0, width: 300, height: 6, rx: 3, fill: '#f0f3e8' }));
        track.append(svgNode('rect', { x: 0, y: 0, width: share * 3, height: 6, rx: 3, fill: colors[index % colors.length] ?? colors[0] ?? '#718b59' }));
        item.append(line, track);
        container.append(item);
        tableRow(body, [row.program, number(row.attendance), number(row.unique_participants), money(row.budget), money(row.actual)]);
    });
    setText('program-total', number(summary.totals.attendance));
}
function render(summary) {
    const totals = summary.totals;
    setText('report-filters', `Applied filters · ${summary.filters.start ?? 'Unbounded start'} – ${summary.filters.end ?? 'Unbounded end'} · ${summary.filters.program ?? 'All programs'}`);
    renderReportTotals(totals);
    setText('metric-unique', number(totals.unique_participants));
    setText('metric-attendance', number(totals.attendance));
    setText('metric-hours', number(totals.participant_hours));
    setText('metric-actual', money(totals.actual));
    setText('metric-repeat', totals.attendance_per_participant === null ? 'No participant denominator' : `${number(totals.attendance_per_participant)} attendances per participant`);
    setText('metric-sessions', `${number(totals.sessions)} sessions delivered`);
    setText('metric-session-hours', `${number(totals.session_hours)} session hours delivered`);
    setText('metric-budget', `Against ${money(totals.budget)} planned budget`);
    const variance = element('metric-variance');
    variance.classList.toggle('over', totals.variance > 0);
    const amount = totals.variance === 0 ? 'On budget' : `${money(Math.abs(totals.variance))} ${totals.variance > 0 ? 'over' : 'under'} budget`;
    variance.textContent = `${amount} · ${totals.variance_percent === null ? 'no % (zero budget)' : number(Math.abs(totals.variance_percent)) + '%'}`;
    const start = summary.filters.start ?? metadata?.start;
    const end = summary.filters.end ?? metadata?.end;
    setText('reporting-window', start && end ? `${dateLabel(start)} – ${dateLabel(end)}` : 'All recorded dates');
    setText('filter-count', `${number(summary.programs.length)} programs · ${number(totals.sessions)} sessions`);
    setText('app-status', `Showing ${number(totals.sessions)} synthetic sessions${summary.filters.program ? ' · ' + summary.filters.program : ' across all programs'}.`);
    setText('ledger-count', `${number(totals.sessions)} sessions in this view`);
    element('empty-state').hidden = totals.sessions !== 0;
    element('chart-grid').hidden = totals.sessions === 0;
    renderAttendance(summary);
    renderPrograms(summary);
    const body = element('sessions-body');
    body.replaceChildren();
    for (const session of summary.sessions) {
        const row = tableRow(body, [dateLabel(session.session_date), session.program, number(session.attendance), number(session.duration_hours), money(session.budget), money(session.actual), `${session.variance > 0 ? '+' : session.variance < 0 ? '−' : ''}${money(Math.abs(session.variance))}`]);
        const program = row.cells[1];
        if (program) {
            const id = document.createElement('span');
            id.textContent = session.session_id;
            program.append(id);
        }
        row.cells[6]?.classList.add(session.variance > 0 ? 'variance-positive' : 'variance-negative');
    }
}
async function refresh(filtersToApply) {
    const revision = ++requestRevision;
    summaryState = 'pending';
    updateReportReadiness();
    try {
        const filters = { ...(filtersToApply ?? readFilters()) };
        submittedFilters = filters;
        element('app-error').hidden = true;
        setText('app-status', 'Updating this view…');
        clearComparison('Comparison cleared while the view updates.');
        const summary = isStatic && snapshot ? summaryFromSnapshot(snapshot, filters) : await json('./api/summary?' + query(filters));
        if (revision !== requestRevision)
            return;
        appliedFilters = filters;
        render(summary);
        summaryState = 'ready';
        await refreshComparison();
    }
    catch (error) {
        if (revision !== requestRevision)
            return;
        summaryState = 'error';
        clearComparison('Comparison cleared because the view could not be updated. Apply valid filters to compare again.');
        setText('app-status', 'The view could not be updated. Check your filters or local service.');
        showError(error);
    }
}
async function loadMetadata() {
    metadata = isStatic && snapshot ? metadataFromSnapshot(snapshot) : await json('./api/meta');
    const select = element('program-filter');
    const selected = select.value;
    select.replaceChildren(new Option('All programs', ''));
    for (const program of metadata.programs)
        select.add(new Option(program, program));
    select.value = metadata.programs.includes(selected) ? selected : '';
}
function resetFilters() {
    element('start-date').value = metadata?.start ?? '';
    element('end-date').value = metadata?.end ?? '';
    element('program-filter').value = '';
    void refresh();
}
function downloadBlob(content, filename) {
    const link = document.createElement('a');
    const url = URL.createObjectURL(content);
    link.href = url;
    link.download = filename;
    link.hidden = true;
    document.body.append(link);
    link.click();
    link.remove();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}
async function exportCSV(kind) {
    try {
        let blob;
        if (isStatic && snapshot)
            blob = new Blob([csvFromSnapshot(kind, snapshot, appliedFilters)], { type: 'text/csv;charset=utf-8' });
        else {
            const response = await fetch(`./api/export?kind=${kind}&${query(appliedFilters)}`);
            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.error);
            }
            blob = await response.blob();
        }
        downloadBlob(blob, `impact-ledger-${kind}.csv`);
    }
    catch (error) {
        showError(error);
    }
}
function updateImportActions() {
    const disabled = isStatic || importPending || previewPending;
    element('import-button').disabled = disabled;
    element('preview-button').disabled = disabled;
}
function clearPreview() {
    ++previewRevision;
    previewPending = false;
    element('preview-result').hidden = true;
    element('preview-errors-body').replaceChildren();
    element('preview-errors').hidden = true;
    setText('preview-status', '');
    setText('preview-limit', '');
    updateImportActions();
}
async function previewCSV() {
    if (isStatic || importPending || previewPending)
        return;
    clearPreview();
    const revision = previewRevision;
    const status = element('preview-status');
    status.classList.remove('error');
    element('preview-result').hidden = false;
    try {
        const file = element('import-file').files?.[0];
        if (!file)
            throw new Error('Choose a UTF-8 CSV file first.');
        if (file.size > 1024 * 1024)
            throw new Error('CSV exceeds the 1 MiB limit. Choose a smaller file.');
        const kind = element('import-kind').value;
        previewPending = true;
        updateImportActions();
        status.textContent = 'Checking CSV against the current ledger. No rows will be added…';
        const result = await json(`./api/import/preview?kind=${encodeURIComponent(kind)}`, { method: 'POST', headers: { 'Content-Type': 'text/csv; charset=utf-8' }, body: file });
        if (revision !== previewRevision)
            return;
        status.classList.toggle('error', !result.valid);
        status.textContent = `${result.valid ? 'Valid' : 'Invalid'} · ${number(result.rows)} data row${result.rows === 1 ? '' : 's'} checked. No rows were added.`;
        setText('preview-limit', result.errors_truncated ? `Showing ${result.errors.length} of ${number(result.errors_total)} errors (100 displayed maximum). Fix these and preview again for a complete review.` : `${number(result.errors_total)} errors found (100 displayed maximum).${result.valid ? ' Choose Import CSV separately when ready.' : ' Fix the listed errors, then preview or import again.'}`);
        for (const error of result.errors)
            tableRow(element('preview-errors-body'), [error.row === null ? 'File' : String(error.row), error.field ?? '—', error.code, error.message]);
        element('preview-errors').hidden = result.errors.length === 0;
    }
    catch (error) {
        if (revision !== previewRevision)
            return;
        status.classList.add('error');
        status.textContent = 'Preview unavailable: ' + (error instanceof Error ? error.message : 'Try the local service again.');
    }
    finally {
        if (revision === previewRevision) {
            previewPending = false;
            updateImportActions();
        }
    }
}
async function importCSV() {
    if (isStatic || importPending || previewPending)
        return;
    const fileInput = element('import-file');
    const file = fileInput.files?.[0];
    const status = element('import-status');
    status.classList.remove('error');
    try {
        if (!file)
            throw new Error('Choose a UTF-8 CSV file first.');
        if (file.size > 1024 * 1024)
            throw new Error('CSV exceeds the 1 MiB limit. No rows were added.');
        clearPreview();
        importPending = true;
        updateImportActions();
        updateReportReadiness();
        status.textContent = 'Validating every row…';
        const kind = element('import-kind').value;
        const result = await json(`./api/import?kind=${encodeURIComponent(kind)}`, { method: 'POST', headers: { 'Content-Type': 'text/csv; charset=utf-8' }, body: file });
        status.textContent = `${result.imported} ${kind} imported. Current filters still apply; reset filters to view all dates.`;
        fileInput.value = '';
        await loadMetadata();
        await refresh({ ...submittedFilters });
    }
    catch (error) {
        status.classList.add('error');
        status.textContent = 'Import revalidates the current ledger state; it may have changed since preview. ' + (error instanceof Error ? error.message : 'Import failed. No rows were added.');
    }
    finally {
        importPending = false;
        updateImportActions();
        updateReportReadiness();
    }
}
element('filters').addEventListener('submit', event => { event.preventDefault(); void refresh(); });
element('reset-filters').addEventListener('click', resetFilters);
element('compare-prior').addEventListener('change', () => { void refreshComparison(); });
element('print-report').addEventListener('click', () => {
    updateReportReadiness();
    if (!element('print-report').disabled)
        window.print();
});
let printDisclosures = [];
window.addEventListener('beforeprint', () => {
    printDisclosures.push(...document.querySelectorAll('.chart-details:not([open])'));
    for (const disclosure of printDisclosures)
        disclosure.open = true;
});
window.addEventListener('afterprint', () => {
    for (const disclosure of printDisclosures)
        disclosure.open = false;
    printDisclosures = [];
});
element('export-sessions').addEventListener('click', () => { void exportCSV('sessions'); });
element('export-attendance').addEventListener('click', () => { void exportCSV('attendance'); });
element('preview-button').addEventListener('click', () => { void previewCSV(); });
element('import-file').addEventListener('change', clearPreview);
element('import-kind').addEventListener('change', clearPreview);
element('import-form').addEventListener('submit', event => { event.preventDefault(); void importCSV(); });
element('download-template').addEventListener('click', () => {
    const kind = element('import-kind').value;
    const header = kind === 'sessions' ? 'session_id,program,session_date,duration_hours,budget,actual\r\n' : 'attendance_id,session_id,participant_id\r\n';
    downloadBlob(new Blob([header], { type: 'text/csv;charset=utf-8' }), `impact-ledger-${kind}-template.csv`);
});
for (const link of document.querySelectorAll('.nav-link')) {
    link.addEventListener('click', () => {
        document.querySelector('.nav-link.active')?.classList.remove('active');
        link.classList.add('active');
    });
}
async function start() {
    updateReportReadiness();
    setText('mode-badge', isStatic ? 'Static preview · synthetic' : 'Local service · synthetic');
    if (isStatic) {
        setText('import-help', 'This static preview uses a bundled synthetic snapshot. CSV preview against SQLite requires the local API; to preview or import CSV, run the local service using the README quickstart. Filters and CSV exports work here.');
        updateImportActions();
        element('import-file').disabled = true;
        // The record-type selector stays available so both blank templates can be downloaded.
        snapshot = await json('./demo.json');
    }
    await loadMetadata();
    resetFilters();
}
void start().catch(error => { summaryState = 'error'; updateReportReadiness(); showError(error); setText('app-status', 'Unable to load the workspace. Start the local service or rebuild the static preview.'); });
