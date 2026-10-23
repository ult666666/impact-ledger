import json
from pathlib import Path
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

    def test_missing_import_file_is_a_readable_error(self):
        result = self.run_cli('import', 'sessions', '/does-not-exist.csv')
        self.assertEqual(result.returncode, 2)
        self.assertNotIn('Traceback', result.stderr)


if __name__ == '__main__':
    unittest.main()
