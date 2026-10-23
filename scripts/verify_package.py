"""Run with an installed package interpreter; exercise CLI/assets outside source root."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
with tempfile.TemporaryDirectory(prefix='impact-ledger-installed-') as directory:
    installed = subprocess.run([sys.executable, '-c', "import json, impact_ledger; from importlib.metadata import version; print(json.dumps([impact_ledger.__version__, version('impact-ledger'), impact_ledger.__file__]))"], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    package_version, distribution_version, module_path = json.loads(installed.stdout)
    assert package_version == distribution_version == '1.2.0'
    assert Path(module_path).resolve() != ROOT / 'impact_ledger' / '__init__.py'
    for name in ['__init__.py', 'store.py', 'csv_import.py', 'server.py', '__main__.py']:
        assert Path(module_path).with_name(name).read_bytes() == (ROOT / 'impact_ledger' / name).read_bytes()
    seeded = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'seed'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(seeded.stdout)['sessions'] == 36
    summary = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'summary', '--program', 'Learning Lab'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(summary.stdout)['totals']['attendance'] == 114
    comparison = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'comparison', '--start', '2026-09-01', '--end', '2026-09-30', '--program', 'Learning Lab'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    comparison_result = json.loads(comparison.stdout)
    assert comparison_result['current']['totals']['sessions'] == 3
    assert comparison_result['previous']['totals']['sessions'] == 5
    assert comparison_result['deltas']['sessions'] == -2
    source = Path(directory) / 'preview.csv'
    source.write_bytes(b'session_id,program,session_date,duration_hours,budget,actual\ninstalled-new,Lab,2026-09-01,1.25,0.10,0.20\n')
    db_path = Path(directory) / 'ledger.db'
    before = (db_path.read_bytes(), db_path.stat().st_mtime_ns)
    cli = str(Path(sys.executable).with_name('impact-ledger'))
    preview = subprocess.run([cli, '--db', 'ledger.db', 'preview-import', 'sessions', str(source)], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(preview.stdout) == {'kind': 'sessions', 'valid': True, 'rows': 1, 'errors': [], 'errors_truncated': False, 'errors_total': 0}
    assert before == (db_path.read_bytes(), db_path.stat().st_mtime_ns)
    invalid_source = Path(directory) / 'invalid.csv'
    invalid_source.write_bytes(b'\xff')
    invalid = subprocess.run([cli, '--db', 'ledger.db', 'preview-import', 'sessions', str(invalid_source)], cwd=directory, capture_output=True, text=True, timeout=10)
    assert invalid.returncode == 1 and json.loads(invalid.stdout)['errors'][0]['code'] == 'encoding'
    missing = subprocess.run([cli, '--db', 'missing-parent/ledger.db', 'preview-import', 'sessions', str(source)], cwd=directory, capture_output=True, text=True, timeout=10)
    assert missing.returncode == 2 and not (Path(directory) / 'missing-parent').exists()
    server = subprocess.Popen([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'serve', '--port', '0'], cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = server.stdout.readline()
        match = re.search(r'http://127\.0\.0\.1:\d+', line)
        assert match, line
        base = match.group(0)
        for route, fragment in [('/', b'Preview CSV'), ('/app.js', b'api/import/preview'), ('/model.js', b'summaryFromSnapshot')]:
            with urlopen(base + route, timeout=5) as response:
                assert response.status == 200
                body = response.read()
                assert fragment in body
                name = 'index.html' if route == '/' else route.lstrip('/')
                assert body == (ROOT / 'impact_ledger' / 'static' / name).read_bytes()
        with urlopen(base + '/api/comparison?start=2026-09-01&end=2026-09-30&program=Learning%20Lab', timeout=5) as response:
            assert json.load(response) == comparison_result
        for payload, valid in [(source.read_bytes(), True), (b'\xff', False)]:
            request = Request(base + '/api/import/preview?kind=sessions', data=payload, headers={'Content-Type': 'text/csv; charset=utf-8'}, method='POST')
            with urlopen(request, timeout=5) as response:
                assert response.status == 200 and json.load(response)['valid'] == valid
        assert before == (db_path.read_bytes(), db_path.stat().st_mtime_ns)
        with urlopen(base + '/api/meta', timeout=5) as response:
            assert json.load(response)['sessions'] == 36
        request = Request(base + '/api/import?kind=sessions', data=source.read_bytes(), headers={'Content-Type': 'text/csv'}, method='POST')
        with urlopen(request, timeout=5) as response:
            assert response.status == 201 and json.load(response) == {'kind': 'sessions', 'imported': 1}
        with urlopen(base + '/api/meta', timeout=5) as response:
            assert json.load(response)['sessions'] == 37
        with urlopen(base + '/styles.css', timeout=5) as response:
            body = response.read()
            assert b'@media print' in body
            assert body == (ROOT / 'impact_ledger' / 'static' / 'styles.css').read_bytes()
        with urlopen(base + '/api/health', timeout=5) as response:
            assert json.load(response) == {'status': 'ok', 'synthetic': True}
    finally:
        server.terminate()
        server.wait(timeout=5)
print('Installed 1.2.0 wheel verified outside checkout: console preview CLI exits 0/1/2, no initialization or writes, preview API diagnostics, separate real import, summary/comparison CLI/API, health, exact HTML/JS and print CSS assets.')
