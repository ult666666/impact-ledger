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
    seeded = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'seed'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(seeded.stdout)['sessions'] == 36
    summary = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', 'ledger.db', 'summary', '--program', 'Learning Lab'], cwd=directory, check=True, capture_output=True, text=True, timeout=10)
    assert json.loads(summary.stdout)['totals']['attendance'] == 114
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
        with urlopen(base + '/api/health', timeout=5) as response:
            assert json.load(response) == {'status': 'ok', 'synthetic': True}
    finally:
        server.terminate()
        server.wait(timeout=5)
print('Installed package verified: seed, filtered summary, real HTTP health, HTML and JavaScript assets.')
