import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((ROOT/'.github/workflows').glob('*.yml'))


class WorkflowTests(unittest.TestCase):
    def test_every_action_is_pinned_to_a_commit_with_its_version(self):
        uses = [(path.name, line.strip()) for path in WORKFLOWS for line in path.read_text().splitlines()
                if re.match(r'\s*(-\s+)?uses:', line)]
        self.assertTrue(uses)
        loose = [entry for entry in uses
                 if not re.fullmatch(r'(-\s+)?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+', entry[1])]
        self.assertEqual(loose, [])

    def test_analysis_job_runs_existing_paper_statistics_and_script_tests(self):
        text = (ROOT/'.github/workflows/harness.yml').read_text()
        job = text.split('  analysis-and-scripts:', 1)[1]
        self.assertNotIn('bootstrap', job)  # No scene assets: the job cannot load scenes or step physics.
        modules = re.findall(r'\btest_\w+', job.split('-m unittest', 1)[1])
        self.assertEqual([m for m in modules if not (ROOT/'tests'/(m+'.py')).is_file()], [])
        self.assertLessEqual({'test_run_metrics', 'test_run_analysis_atomic', 'test_scripts_index', 'test_workflows'},
                             set(modules))


if __name__ == '__main__':
    unittest.main()
