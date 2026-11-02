import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest


class CLITests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.db = Path(self.temp.name) / 'cli.db'

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', str(self.db), *args], text=True, capture_output=True, timeout=5)

    def test_seed_and_summary_commands_have_machine_readable_output(self):
        seeded = self.run_cli('seed')
        self.assertEqual(seeded.returncode, 0, seeded.stderr)
        self.assertEqual(json.loads(seeded.stdout)['sessions'], 36)
        summary = self.run_cli('summary', '--program', 'Learning Lab')
        self.assertEqual(summary.returncode, 0, summary.stderr)
        self.assertEqual(json.loads(summary.stdout)['totals']['sessions'], 12)

    def test_comparison_cli_outputs_equal_calendar_windows_and_filters(self):
        self.run_cli('seed')
        result = self.run_cli('comparison', '--start', '2026-09-01', '--end', '2026-09-30', '--program', 'Learning Lab')
        self.assertEqual(result.returncode, 0, result.stderr)
        comparison = json.loads(result.stdout)
        self.assertEqual(comparison['days'], 30)
        self.assertEqual(comparison['previous']['start'], '2026-08-02')
        self.assertEqual(comparison['previous']['end'], '2026-08-31')
        self.assertEqual(comparison['current']['totals']['sessions'], 3)
        self.assertEqual(comparison['filters']['program'], 'Learning Lab')

    def test_comparison_cli_validation_does_not_emit_tracebacks(self):
        for filters in [[], ['--start', '2026-01-01'], ['--start', '0001-01-01', '--end', '0001-01-01'], ['--start', '2026-02-30', '--end', '2026-03-01']]:
            result = self.run_cli('comparison', *filters)
            self.assertEqual(result.returncode, 2)
            self.assertNotIn('Traceback', result.stderr)
            self.assertTrue(result.stderr.startswith('impact-ledger:'), result.stderr)

    def test_cli_errors_use_exit_two_without_traceback(self):
        self.run_cli('seed')
        repeated = self.run_cli('seed')
        self.assertEqual(repeated.returncode, 2)
        self.assertIn('empty database', repeated.stderr)
        self.assertNotIn('Traceback', repeated.stderr)

    def test_import_and_export_commands_roundtrip(self):
        source = Path(self.temp.name) / 'sessions.csv'
        source.write_text('session_id,program,session_date,duration_hours,budget,actual\ns1,社区厨房,2026-01-01,1.25,100,110\n')
        imported = self.run_cli('import', 'sessions', str(source))
        self.assertEqual(imported.returncode, 0, imported.stderr)
        output = Path(self.temp.name) / 'export.csv'
        result = self.run_cli('export', 'sessions', '--output', str(output))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('社区厨房,2026-01-01,1.25,100.00,110.00', output.read_text())

    def test_preview_cli_outputs_json_exit_zero_or_one_and_never_imports(self):
        self.assertEqual(self.run_cli('init').returncode, 0)
        source = Path(self.temp.name) / 'sessions.csv'
        source.write_text('session_id,program,session_date,duration_hours,budget,actual\ns1,Lab,2026-01-01,1,0,1\n')
        before = (self.db.read_bytes(), self.db.stat().st_mtime_ns)
        valid = self.run_cli('preview-import', 'sessions', str(source))
        self.assertEqual(valid.returncode, 0, valid.stderr)
        self.assertEqual((json.loads(valid.stdout)['valid'], json.loads(valid.stdout)['rows']), (True, 1))
        source.write_bytes(b'\xff')
        invalid = self.run_cli('preview-import', 'sessions', str(source))
        self.assertEqual(invalid.returncode, 1, invalid.stderr)
        self.assertEqual(json.loads(invalid.stdout)['errors'][0]['code'], 'encoding')
        self.assertEqual(before, (self.db.read_bytes(), self.db.stat().st_mtime_ns))
        self.assertEqual(json.loads(self.run_cli('summary').stdout)['totals']['sessions'], 0)

    def test_preview_cli_requires_existing_initialized_database_without_creating_paths(self):
        source = Path(self.temp.name) / 'sessions.csv'
        source.write_text('session_id,program,session_date,duration_hours,budget,actual\ns1,Lab,2026-01-01,1,0,1\n')
        self.db = Path(self.temp.name) / 'missing-parent' / 'ledger.db'
        result = self.run_cli('preview-import', 'sessions', str(source))
        self.assertEqual(result.returncode, 2)
        self.assertFalse(self.db.parent.exists())
        self.db = Path(self.temp.name) / 'uninitialized.db'
        self.db.touch()
        result = self.run_cli('preview-import', 'sessions', str(source))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(self.db.read_bytes(), b'')
        self.assertNotIn('Traceback', result.stderr)
        self.run_cli('init')
        missing = self.run_cli('preview-import', 'sessions', '/does-not-exist.csv')
        self.assertEqual(missing.returncode, 2)
        self.assertNotIn('Traceback', missing.stderr)
        self.assertEqual(self.run_cli('preview-import', 'unknown', str(source)).returncode, 2)

    def test_missing_import_file_is_a_readable_error(self):
        result = self.run_cli('import', 'sessions', '/does-not-exist.csv')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)


    def test_audit_cli_records_corrections_undoes_imports_and_reports_as_of(self):
        self.assertEqual(self.run_cli('seed').returncode, 0)
        sessions = Path(__file__).resolve().parents[1] / 'examples' / 'sessions.csv'
        imported = json.loads(self.run_cli('import', 'sessions', str(sessions)).stdout)
        self.assertEqual(imported['batch_id'], 'B000379')
        corrected = self.run_cli('--actor', 'analyst', 'update-session', 'demo-s01-1', '--actual', '190.50')
        self.assertEqual(corrected.returncode, 0, corrected.stderr)
        self.assertEqual(json.loads(corrected.stdout)['after']['actual_cents'], 19050)
        history = json.loads(self.run_cli('history', '--limit', '2').stdout)
        self.assertEqual([(b['batch_id'], b['actor'], b['kind']) for b in history['batches']],
                         [('B000381', 'analyst', 'update'), ('B000379', 'local-cli', 'import')])
        before = json.loads(self.run_cli('summary', '--as-of-entry', '378').stdout)
        self.assertEqual((before['totals']['sessions'], before['as_of']['entry']), (36, 378))
        self.assertEqual(json.loads(self.run_cli('summary', '--as-of', '2000-01-01').stdout)['totals']['sessions'], 0)
        exported = self.run_cli('export', 'sessions', '--as-of-entry', '378')
        self.assertEqual(len(exported.stdout.strip().splitlines()), 37)
        undone = self.run_cli('undo-import', 'B000379')
        self.assertEqual(json.loads(undone.stdout)['deleted'], 2)
        again = self.run_cli('undo-import', 'B000379')
        self.assertEqual((again.returncode, 'already undone' in again.stderr), (2, True))
        verified = self.run_cli('verify')
        self.assertEqual(verified.returncode, 0, verified.stdout)
        head = json.loads(verified.stdout)['head']['hash']
        self.assertEqual(self.run_cli('verify', '--expect-head', head).returncode, 0)
        self.assertEqual(self.run_cli('verify', '--expect-head', '0' * 64).returncode, 1)
        self.assertEqual(self.run_cli('verify', '--expect-head', 'not-a-digest').returncode, 2)
        conflict = self.run_cli('summary', '--as-of', '2026-01-01', '--as-of-entry', '1')
        self.assertEqual(conflict.returncode, 2)
        for args in [['delete-session', 'demo-s01-1'], ['update-session', 'missing', '--actual', '1'], ['update-attendance', 'demo-s01-1-a01', '--participant', 'demo-p001']]:
            result = self.run_cli(*args)
            self.assertEqual(result.returncode, 2, args)
            self.assertNotIn('Traceback', result.stderr)

    def test_verify_cli_exits_one_on_tampering_and_never_creates_a_ledger(self):
        missing = self.db.with_name('missing.db')
        result = subprocess.run([sys.executable, '-m', 'impact_ledger', '--db', str(missing), 'verify'], text=True, capture_output=True, timeout=5)
        self.assertEqual(result.returncode, 2)
        self.assertFalse(missing.exists())
        self.run_cli('seed')
        connection = sqlite3.connect(self.db)
        connection.execute('DROP TRIGGER audit_log_no_update')
        connection.execute("UPDATE audit_log SET actor = 'someone' WHERE seq = 7")
        connection.commit()
        connection.close()
        tampered = self.run_cli('verify')
        self.assertEqual(tampered.returncode, 1)
        report = json.loads(tampered.stdout)
        self.assertEqual([(p['code'], p['entry']) for p in report['problems']], [('protection_removed', None), ('hash_mismatch', 7), ('batch_structure', 7)])


if __name__ == '__main__':
    unittest.main()
