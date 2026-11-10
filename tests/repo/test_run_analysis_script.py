"""scripts/run_analysis.py reports missing and failed runs instead of passing them as empty."""

import contextlib
import io
import json
from pathlib import Path
import tempfile
import unittest

from scripts import run_analysis
from analysis.test_run_analysis_segments import BASE, Fixture, action, header, snap


def dial_run(root, name):
    f = Fixture(root, name)
    angles = lambda t, a: snap(float(t), private_angles_deg=[a], valid_trials=0, display=0, solved=False)
    f.log([header(), angles(0, 0.0), angles(1, 0.0), angles(3, 60.0), angles(5, 60.0)])
    f.db([action('A', 0, 2), action('A', 3, 5)], [(BASE, 'START', {})])
    return f


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(self.enterContext(tempfile.TemporaryDirectory()))
        dial_run(self.tmp / 'data', 'good')
        self.runs = self.tmp / 'runs.json'
        self.runs.write_text(json.dumps([dict(id='good', k='good', family='dial'),
                                         dict(id='gone', k='no/such/run', family='dial')]))

    def main(self, *argv):
        err = io.StringIO()
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(err):
            code = run_analysis.main([str(a) for a in argv])
        return code, err.getvalue()

    def test_extract_fails_for_a_missing_run_and_redoes_a_truncated_record(self):
        out = self.tmp / 'extracted'
        out.mkdir()
        (out / 'good.json').write_text('{"sel": {"id": "go')  # a worker killed mid-write
        code, err = self.main('extract', '--root', self.tmp / 'data', '--runs', self.runs, '--out', out,
                              '--workers', 1)
        self.assertEqual(code, 1)
        self.assertIn('gone', err)
        self.assertFalse((out / 'gone.json').exists())
        self.assertGreater(json.loads((out / 'good.json').read_text())['nfiles'], 0)
        self.assertEqual(sorted(p.name for p in out.iterdir()), ['good.json'])

    def test_dial_turns_reports_failing_runs(self):
        out = self.tmp / 'turns.json'
        code, err = self.main('dial-turns', '--root', self.tmp / 'data', '--runs', self.runs, '--out', out,
                              '--workers', 1)
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(out.read_text())['good']['turns'], [[3.0, 0]])
        self.assertEqual(list(json.loads(Path(str(out) + '.errors.json').read_text())), ['gone'])

    def test_atomic_v2_lists_dial_runs_without_turns(self):
        out = self.tmp / 'extracted'
        self.runs.write_text(json.dumps([dict(id='good', k='good', family='dial')]))
        self.assertEqual(self.main('extract', '--root', self.tmp / 'data', '--runs', self.runs, '--out', out,
                                   '--workers', 1)[0], 0)
        turns = self.tmp / 'turns.json'
        turns.write_text(json.dumps({}))
        result = self.tmp / 'v2.json'
        code, err = self.main('atomic-v2', '--extracted', out, '--dial-turns', turns, '--out', result)
        self.assertEqual(code, 1)
        skipped = json.loads(Path(str(result) + '.skipped.json').read_text())
        self.assertEqual([(x['id'], x['missing']) for x in skipped], [('good', True)])
        turns.write_text(json.dumps({'good': {'turns': [[3.0, 0]], 'unknown': None}}))
        code, err = self.main('atomic-v2', '--extracted', out, '--dial-turns', turns, '--out', result)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(result.read_text())[0]['delivered'], 1)


if __name__ == '__main__':
    unittest.main()
