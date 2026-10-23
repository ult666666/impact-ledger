"""Build a portable read-only synthetic preview from the same browser assets."""
import json
from pathlib import Path
import shutil
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from impact_ledger.store import Store  # noqa: E402


def main():
    target = ROOT / 'site'
    target.mkdir(exist_ok=True)
    source = ROOT / 'impact_ledger' / 'static'
    for name in ['index.html', 'styles.css', 'app.js', 'model.js', 'favicon.svg']:
        shutil.copyfile(source / name, target / name)
    page = (target / 'index.html').read_text()
    (target / 'index.html').write_text(page.replace('data-mode="local"', 'data-mode="static"'))
    with tempfile.TemporaryDirectory() as directory:
        store = Store(Path(directory) / 'demo.db')
        store.seed_demo()
        (target / 'demo.json').write_text(json.dumps(store.snapshot(), ensure_ascii=False, separators=(',', ':')) + '\n')
    (target / '.nojekyll').touch()
    print('Built local assets and read-only synthetic preview in site/.')


if __name__ == '__main__':
    main()
