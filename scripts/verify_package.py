"""Run with an installed package interpreter; exercise CLI/assets outside source root."""
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[1]
(ROOT / '.local').mkdir(exist_ok=True)
with tempfile.TemporaryDirectory(prefix='package-check-', dir=ROOT / '.local') as directory:
    installed = subprocess.run([sys.executable, '-c', "import json, impact_ledger; from importlib.metadata import version; print(json.dumps([impact_ledger.__version__, version('impact-ledger'), impact_ledger.__file__]))"], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    package_version, distribution_version, module_path = json.loads(installed.stdout)
    assert package_version == distribution_version == '1.1.0'
    assert Path(module_path).resolve() != ROOT / 'impact_ledger' / '__init__.py'
    seeded = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'seed'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(seeded.stdout)['sessions'] == 36
    summary = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'summary', '--program', 'Learning Lab'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(summary.stdout)['totals']['attendance'] == 114
    comparison = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'comparison', '--start', '2026-09-01', '--end', '2026-09-30', '--program', 'Learning Lab'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    comparison_result = json.loads(comparison.stdout)
    assert comparison_result['current']['totals']['sessions'] == 3
    assert comparison_result['previous']['totals']['sessions'] == 5
    assert comparison_result['deltas']['sessions'] == -2
    server = subprocess.Popen([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'serve', '--port', '0'], cwd=directory, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    try:
        line = server.stdout.readline()
        match = re.search(r'http://127\.0\.0\.1:\d+', line)
        assert match, line
        base = match.group(0)
        for route, fragment in [('/', b'Good work.'), ('/app.js', b'function render'), ('/model.js', b'summaryFromSnapshot')]:
            with urlopen(base + route, timeout=5) as response:
                assert response.status == 200
                assert fragment in response.read()
        with urlopen(base + '/api/comparison?start=2026-09-01&end=2026-09-30&program=Learning%20Lab', timeout=5) as response:
            assert json.load(response) == comparison_result
        with urlopen(base + '/styles.css', timeout=5) as response:
            assert b'@media print' in response.read()
        with urlopen(base + '/api/health', timeout=5) as response:
            assert json.load(response) == {'status': 'ok', 'synthetic': True}
    finally:
        server.terminate()
        server.wait(timeout=5)
print('Installed package verified: seed, summary/comparison CLI, matching real comparison API, health, HTML/JS and print CSS assets.')
