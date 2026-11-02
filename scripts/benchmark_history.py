"""Time current reports, as-of reports and verification on a synthetic 25,000-entry ledger.

As-of reports replay and check the audit log prefix, so their cost grows with
the number of entries. This script measures that cost against the ordinary
current-table report. It writes only to a new temporary database.

    python3 scripts/benchmark_history.py
"""
import json
from pathlib import Path
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from impact_ledger.store import Store  # noqa: E402


def best_of(function, repeat=3):
    timings = []
    for _ in range(repeat):
        start = time.perf_counter()
        function()
        timings.append(time.perf_counter() - start)
    return round(min(timings) * 1000)


def main():
    with tempfile.TemporaryDirectory(prefix='impact-history-benchmark-') as directory:
        store = Store(Path(directory) / 'benchmark.db')
        for batch in range(5):
            rows = ['session_id,program,session_date,duration_hours,budget,actual']
            rows += [f's{batch}-{i},Program {i % 7},2026-{1 + i % 12:02}-{1 + i % 28:02},1.50,100.00,95.00' for i in range(1000)]
            store.import_csv('sessions', ('\n'.join(rows) + '\n').encode())
        for batch in range(4):
            rows = ['attendance_id,session_id,participant_id']
            rows += [f'a{batch}-{i},s{(batch * 5000 + i) % 5}-{(batch * 5000 + i) // 5 % 1000},p{batch}-{i % 997}' for i in range(5000)]
            store.import_csv('attendance', ('\n'.join(rows) + '\n').encode())
        entries = store.history(1)['head']['entry']
        assert store.summary(as_of_entry=entries)['totals'] == store.summary()['totals']
        print(json.dumps({
            'entries': entries,
            'milliseconds': {
                'summary_current_tables': best_of(store.summary),
                'summary_as_of_latest_entry': best_of(lambda: store.summary(as_of_entry=entries)),
                'summary_as_of_half_the_log': best_of(lambda: store.summary(as_of_entry=entries // 2)),
                'verify': best_of(store.verify),
            },
            'note': 'Best of three runs on the machine that ran this script; synthetic data only.',
        }, indent=2))


if __name__ == '__main__':
    main()
