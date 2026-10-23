import {test} from 'node:test';
import assert from 'node:assert/strict';
import {spawn, spawnSync} from 'node:child_process';
import {mkdtemp, mkdir, readFile, rm} from 'node:fs/promises';
import {createServer} from 'node:http';
import {resolve, extname} from 'node:path';
import {chromium} from 'playwright';

await mkdir('.local', {recursive: true});
const temp = await mkdtemp(resolve('.local/browser-'));
const db = resolve(temp, 'ledger.db');
const seeded = spawnSync('python3', ['-m', 'impact_ledger', '--db', db, 'seed'], {encoding: 'utf8'});
assert.equal(seeded.status, 0, seeded.stderr);
const api = spawn('python3', ['-m', 'impact_ledger', '--db', db, 'serve', '--port', '0'], {stdio: ['ignore', 'pipe', 'pipe']});
const apiUrl = await new Promise((resolveUrl, reject) => {
  const timer = setTimeout(() => reject(new Error('Local server did not start.')), 5000);
  api.stdout.on('data', chunk => {
    const match = String(chunk).match(/http:\/\/127\.0\.0\.1:\d+/);
    if (match) {clearTimeout(timer); resolveUrl(match[0]);}
  });
  api.on('exit', code => reject(new Error(`API exited with ${code}`)));
});
const staticServer = createServer(async (request, response) => {
  const pathname = new URL(request.url, 'http://local').pathname;
  const file = pathname === '/' || pathname === '/impact-ledger/' ? 'index.html' : pathname.replace(/^\/(?:impact-ledger\/)?/, '');
  if (!['index.html', 'styles.css', 'app.js', 'model.js', 'demo.json', 'favicon.svg'].includes(file)) {response.writeHead(404).end(); return;}
  try {
    const body = await readFile(resolve('site', file));
    const mime = {'.html': 'text/html', '.css': 'text/css', '.js': 'text/javascript', '.json': 'application/json', '.svg': 'image/svg+xml'}[extname(file)];
    response.writeHead(200, {'Content-Type': mime}).end(body);
  } catch {response.writeHead(404).end();}
});
await new Promise(done => staticServer.listen(0, '127.0.0.1', done));
const staticUrl = `http://127.0.0.1:${staticServer.address().port}/impact-ledger/`;
const browser = await chromium.launch({headless: true});
const errors = [];
const httpErrors = [];
const context = await browser.newContext({viewport: {width: 1440, height: 1100}, acceptDownloads: true});
context.setDefaultTimeout(5000);
const page = await context.newPage();
page.on('pageerror', error => errors.push(String(error)));
page.on('console', message => {if (message.type() === 'error' && !message.text().startsWith('Failed to load resource:')) errors.push(message.text());});
page.on('response', response => {if (response.status() >= 400) httpErrors.push({status: response.status(), path: new URL(response.url()).pathname});});

async function ready(url) {
  await page.goto(url);
  await page.locator('#app-status').filter({hasText: /Showing/}).waitFor();
}
async function download(button) {
  const promise = page.waitForEvent('download');
  await page.getByRole('button', {name: button, exact: true}).click();
  const result = await promise;
  return readFile(await result.path(), 'utf8');
}

try {
  await test('local dashboard renders synthetic accounting and accessible chart tables', async () => {
    await ready(apiUrl);
    await page.getByRole('heading', {name: 'Good work. Clearer data.'}).waitFor();
    assert.match(await page.locator('#mode-badge').innerText(), /Local service/);
    assert.equal(await page.locator('#metric-unique').innerText(), '55');
    assert.equal(await page.locator('#metric-attendance').innerText(), '342');
    assert.equal(await page.locator('#sessions-body tr').count(), 36);
    await page.getByText('View attendance data', {exact: true}).click();
    assert.equal(await page.getByRole('table', {name: 'Monthly attendance data'}).locator('tbody tr').count(), 3);
    await page.getByLabel('Program', {exact: true}).selectOption('Learning Lab');
    await page.getByRole('button', {name: 'Apply filters'}).click();
    await page.waitForFunction(() => document.querySelector('#sessions-body')?.querySelectorAll('tr').length === 12);
    assert.equal(await page.locator('#sessions-body tr').count(), 12);
    assert.equal(await page.locator('#metric-attendance').innerText(), '114');
    await page.getByRole('button', {name: 'Reset filters'}).click();
    await page.waitForFunction(() => document.querySelector('#sessions-body')?.querySelectorAll('tr').length === 36);
    await page.screenshot({path: 'docs/screenshots/desktop.png', fullPage: true});
  });

  await test('empty date filter renders zero metrics and a useful empty state', async () => {
    await page.getByLabel('Start date', {exact: true}).fill('2020-01-01');
    await page.getByLabel('End date', {exact: true}).fill('2020-01-31');
    await page.getByRole('button', {name: 'Apply filters'}).click();
    await page.getByText('No sessions in this view', {exact: true}).waitFor();
    assert.equal(await page.locator('#metric-unique').innerText(), '0');
    assert.equal(await page.locator('#metric-attendance').innerText(), '0');
    await page.getByRole('button', {name: 'Reset filters'}).click();
    await page.waitForFunction(() => document.querySelector('#metric-unique')?.textContent === '55');
  });

  await test('local CSV export downloads the filtered sessions', async () => {
    await page.getByLabel('Program', {exact: true}).selectOption('Digital Access');
    await page.getByRole('button', {name: 'Apply filters'}).click();
    await page.waitForFunction(() => document.querySelector('#sessions-body')?.querySelectorAll('tr').length === 12);
    const csv = await download('Export sessions CSV');
    assert.ok(csv.startsWith('session_id,program,session_date,duration_hours,budget,actual'));
    assert.equal(csv.trim().split(/\r?\n/).length, 13);
    assert.ok(csv.includes('Digital Access'));
    assert.ok(!csv.includes('Learning Lab'));
  });

  await test('real import displays atomic errors and renders hostile labels as text', async () => {
    const header = 'session_id,program,session_date,duration_hours,budget,actual\n';
    const file = page.getByLabel('CSV file', {exact: true});
    await file.setInputFiles({name: 'invalid.csv', mimeType: 'text/csv', buffer: Buffer.from(header + 'not-added,Lab,2026-09-01,1,1,1\nbad,Lab,2026-02-30,1,1,1\n')});
    await page.getByRole('button', {name: 'Import CSV', exact: true}).click();
    await page.locator('#import-status').filter({hasText: /Row 3/}).waitFor();
    assert.equal((await (await page.request.get(apiUrl + '/api/meta')).json()).sessions, 36);
    await file.setInputFiles({name: 'markup.csv', mimeType: 'text/csv', buffer: Buffer.from(header + 'hostile,<img src=x onerror=alert(1)>,2026-09-01,1,1,1\nmandarin,社区服务,2026-09-02,1,1,1\n')});
    await page.getByRole('button', {name: 'Import CSV', exact: true}).click();
    await page.locator('#import-status').filter({hasText: /2 sessions imported/}).waitFor();
    await page.getByRole('button', {name: 'Reset filters'}).click();
    await page.waitForFunction(() => document.querySelector('#sessions-body')?.querySelectorAll('tr').length === 38);
    assert.equal(await page.locator('#sessions-body img').count(), 0);
    assert.ok((await page.locator('#sessions-body').innerText()).includes('<img src=x onerror=alert(1)>'));
    assert.ok((await page.locator('#sessions-body').innerText()).includes('社区服务'));
  });

  await test('mobile layout stays inside viewport and offers scrollable tables', async () => {
    await page.setViewportSize({width: 390, height: 844});
    await ready(staticUrl);
    assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
    assert.ok(await page.locator('.ledger-scroll').evaluate(el => el.scrollWidth > el.clientWidth));
    await page.screenshot({path: 'docs/screenshots/mobile.png', fullPage: true});
  });

  await test('static preview filters and exports while imports clearly require local service', async () => {
    await page.setViewportSize({width: 1440, height: 1100});
    await ready(staticUrl);
    assert.match(await page.locator('#mode-badge').innerText(), /Static preview/);
    assert.equal(await page.locator('#metric-unique').innerText(), '55');
    assert.ok(await page.getByRole('button', {name: 'Import CSV', exact: true}).isDisabled());
    assert.match(await page.locator('#import-help').innerText(), /local service/);
    await page.getByLabel('Program', {exact: true}).selectOption('Learning Lab');
    await page.getByRole('button', {name: 'Apply filters'}).click();
    await page.waitForFunction(() => document.querySelector('#sessions-body')?.querySelectorAll('tr').length === 12);
    assert.equal(await page.locator('#metric-attendance').innerText(), '114');
    const csv = await download('Export attendance CSV');
    assert.equal(csv.trim().split(/\r?\n/).length, 115);
    assert.deepEqual(errors, []);
    assert.deepEqual(httpErrors, [{status: 400, path: '/api/import'}]);
  });
} finally {
  await browser.close();
  api.kill('SIGTERM');
  await new Promise(done => staticServer.close(done));
  await rm(temp, {recursive: true, force: true});
}
