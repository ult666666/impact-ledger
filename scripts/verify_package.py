"""Run with an installed package interpreter; exercise CLI/assets outside source root."""
import json
from contextlib import closing
from pathlib import Path
import re
import subprocess
import sqlite3
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
    # A closed WAL ledger remains valid input. Read-only SQL may cause SQLite
    # to manage WAL/SHM files; it must not change main bytes or logical data.
    wal_path = Path(directory) / 'wal.db'
    subprocess.run([cli, '--db', str(wal_path), 'seed'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    with closing(sqlite3.connect(wal_path)) as connection:
        connection.execute("CREATE TRIGGER forbid_wal_preview_insert BEFORE INSERT ON sessions BEGIN SELECT RAISE(ABORT, 'preview must not insert'); END")
        connection.commit()

    def wal_logical_state(connection):
        return (connection.execute('PRAGMA schema_version').fetchone(),
                connection.execute('SELECT type,name,tbl_name,sql FROM sqlite_schema ORDER BY type,name').fetchall(),
                connection.execute('SELECT * FROM sessions ORDER BY session_id').fetchall(),
                connection.execute('SELECT * FROM attendance ORDER BY attendance_id').fetchall())

    for operation in ['library', 'cli']:
        with closing(sqlite3.connect(wal_path)) as connection:
            assert connection.execute('PRAGMA journal_mode=WAL').fetchone()[0] == 'wal'
            wal_before_state = wal_logical_state(connection)
        assert not Path(str(wal_path) + '-wal').exists() and not Path(str(wal_path) + '-shm').exists()
        wal_before_main = (wal_path.read_bytes(), wal_path.stat().st_mtime_ns)
        wal_before_entries = {path.name for path in Path(directory).iterdir()}
        command = [cli, '--db', str(wal_path), 'preview-import', 'sessions', str(source)] if operation == 'cli' else [
            sys.executable, '-c', "import json; from pathlib import Path; from impact_ledger.store import Store; print(json.dumps(Store.open_existing('wal.db').preview_csv('sessions', Path('preview.csv').read_bytes())))"]
        wal_preview = subprocess.run(command, cwd=directory, check=True, capture_output=True, text=True, timeout=10)
        assert json.loads(wal_preview.stdout) == {'kind': 'sessions', 'valid': True, 'rows': 1, 'errors': [], 'errors_truncated': False, 'errors_total': 0}
        assert wal_before_main == (wal_path.read_bytes(), wal_path.stat().st_mtime_ns)
        wal_after_entries = {path.name for path in Path(directory).iterdir()}
        assert wal_before_entries <= wal_after_entries
        assert wal_after_entries - wal_before_entries <= {'wal.db-wal', 'wal.db-shm'}
        with closing(sqlite3.connect(wal_path.resolve().as_uri() + '?mode=ro', uri=True)) as connection:
            connection.execute('BEGIN')
            assert wal_logical_state(connection) == wal_before_state
        assert wal_before_main == (wal_path.read_bytes(), wal_path.stat().st_mtime_ns)
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
print('Installed 1.2.0 wheel verified outside checkout: console preview CLI exits 0/1/2, no ledger initialization or SQL writes, closed-WAL library/CLI semantics, preview API diagnostics, separate real import, summary/comparison CLI/API, health, exact HTML/JS and print CSS assets.')
