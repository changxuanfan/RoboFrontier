import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((ROOT / '.github/workflows').glob('*.yml'))


class WorkflowTests(unittest.TestCase):
    def test_every_action_is_pinned_to_a_commit_with_its_version(self):
        uses = [
            (path.name, line.strip())
            for path in WORKFLOWS
            for line in path.read_text().splitlines()
            if re.match(r'\s*(-\s+)?uses:', line)
        ]
        self.assertTrue(uses)
        loose = [
            entry
            for entry in uses
            if not re.fullmatch(r'(-\s+)?uses: [\w.-]+/[\w./-]+@[0-9a-f]{40} # v\d+\.\d+\.\d+', entry[1])
        ]
        self.assertEqual(loose, [])

    def test_one_job_runs_the_protocol_check_and_every_test(self):
        text = (ROOT / '.github/workflows/harness.yml').read_text()
        self.assertEqual(
            re.findall(r'^  ([\w-]+):$', text.split('\njobs:\n', 1)[1], flags=re.M), ['all-tests']
        )
        self.assertIn('scripts.dev.check_harness --protocol-only', text)
        self.assertIn('scripts.dev.run_tests', text)

    def test_documentation_changes_do_not_start_the_tests_but_files_tests_read_do(self):
        text = (ROOT / '.github/workflows/harness.yml').read_text()
        for trigger in ('pull_request', 'push'):
            paths = re.findall(
                r"- '([^']+)'",
                text.split('  ' + trigger + ':', 1)[1]
                .split('\n  workflow_dispatch', 1)[0]
                .split('\n  push:', 1)[0],
            )
            self.assertEqual(paths[0], '**')
            self.assertLessEqual({'!docs/**', '!site/**', '!README.md'}, set(paths))
            # Later patterns win: the files tests read are named after the exclusions.
            for kept in ('docs/runs/continuation.md', 'site/data/**'):
                self.assertGreater(paths.index(kept), paths.index('!docs/**'))
                self.assertTrue((ROOT / kept.replace('/**', '')).exists())


if __name__ == '__main__':
    unittest.main()
