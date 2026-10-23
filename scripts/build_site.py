"""Build or verify the exact portable synthetic preview; never upload a directory unchecked."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from impact_ledger.store import Store  # noqa: E402

ASSETS = ('index.html', 'app.js', 'model.js', 'styles.css', 'favicon.svg')
NAMES = (*ASSETS, 'demo.json', '.nojekyll')
SOURCE = ROOT / 'impact_ledger' / 'static'


class PayloadError(Exception):
    def __init__(self, code, name=None):
        self.error = {'code': code}
        if name is not None:
            self.error['file'] = name


def preflight(selected, *, verify):
    """Check the selected entry before canonicalizing trusted ancestor aliases."""
    try:
        info = selected.lstat()
    except FileNotFoundError:
        info = None
    if info is not None and stat.S_ISLNK(info.st_mode):
        raise PayloadError('selected_symlink')
    target = selected.resolve()
    source = SOURCE.resolve()
    if target == source or source in target.parents or target in source.parents:
        raise PayloadError('source_overlap')
    if info is None:
        if verify:
            raise PayloadError('missing_output')
        return target
    if not stat.S_ISDIR(info.st_mode):
        raise PayloadError('output_not_directory')
    # Inspect every entry before any target writes; never open unknown names.
    for entry in target.iterdir():
        if entry.name not in NAMES:
            raise PayloadError('unexpected_entry')
        if not stat.S_ISREG(entry.lstat().st_mode):
            raise PayloadError('nonregular_entry', entry.name)
    return target


def expected_payload():
    payload = {name: (SOURCE / name).read_bytes() for name in ASSETS}
    payload['index.html'] = payload['index.html'].replace(b'data-mode="local"', b'data-mode="static"')
    # Verification is read-only with respect to the selected target, not all of
    # the filesystem: expected synthetic data uses its own private temporary DB.
    with tempfile.TemporaryDirectory(prefix='impact-static-seed-') as directory:
        store = Store(Path(directory) / 'demo.db')
        store.seed_demo()
        payload['demo.json'] = (json.dumps(store.snapshot(), ensure_ascii=False, separators=(',', ':')) + '\n').encode('utf-8')
    payload['.nojekyll'] = b''
    return payload


def write_payload(target, payload):
    target.mkdir(exist_ok=True)
    staged = []
    try:
        # Stage all bytes before replacing any generated name. Never truncate an
        # existing entry: os.replace detaches a hard link from an unselected file.
        for name, body in payload.items():
            with tempfile.NamedTemporaryFile(dir=target, prefix='.impact-static-', delete=False) as stream:
                temporary = Path(stream.name)
                staged.append((temporary, target / name))
                stream.write(body)
        for temporary, destination in staged:
            os.replace(temporary, destination)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)


def verify_payload(target, payload):
    preflight(target, verify=True)
    files = []
    for name, expected in payload.items():
        path = target / name
        try:
            actual = path.read_bytes()
        except FileNotFoundError:
            raise PayloadError('missing_file', name) from None
        if actual != expected:
            raise PayloadError('content_mismatch', name)
        files.append({'name': name, 'bytes': len(actual), 'sha256': hashlib.sha256(actual).hexdigest()})
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-directory', type=Path, default=ROOT / 'site', help='Selected output directory; its parent must exist (default: repository site/).')
    parser.add_argument('--verify-only', action='store_true', help='Read/compare the exact selected payload without repairing or writing it.')
    arguments = parser.parse_args()
    receipt = {'operation': 'verify' if arguments.verify_only else 'build', 'valid': False, 'files': [], 'errors': []}
    try:
        target = preflight(arguments.output_directory, verify=arguments.verify_only)
        payload = expected_payload()
        if not arguments.verify_only:
            write_payload(target, payload)
        receipt['files'] = verify_payload(target, payload)
        receipt['valid'] = True
    except PayloadError as error:
        receipt['errors'] = [error.error]
    except (OSError, sqlite3.Error, ValueError, RuntimeError):
        # Never echo paths, exception text, unknown names or file contents.
        receipt['errors'] = [{'code': 'io_error'}]
    print(json.dumps(receipt, separators=(',', ':')))
    return 0 if receipt['valid'] else 1


if __name__ == '__main__':
    sys.exit(main())
