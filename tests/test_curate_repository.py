import json
import os
import tempfile
import time
import unittest
from pathlib import Path

from scripts import curate_repository


def write(path, value='{}'):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value)


class CurateRepositoryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name).resolve()
        write(self.root/'benchmark/release.json', json.dumps({'families': {}}))
        runs = self.root/'runs'
        for name in ('exports/claude-batch-1234abcd/batch.json', 'archives/y/archive.tar', 'factory-data/r14/bundle.json',
                     'asset-cache/abc.tar.gz', 'container-exports/ws/x', 'submissions/s/x'):
            write(runs/name)
        # A batch placed directly under runs/ and a lone policy run without a batch file.
        write(runs/'sol61-l1-20261104/batch.json')
        write(runs/'sol61-l1-20261104/profile/case/private/inputs/manifest.json')
        write(runs/'lone-policy-run/private/inputs/manifest.json')
        # The one real candidate: an old failed probe.
        write(runs/'failed-probe/report.json', json.dumps({'passed': False}))
        old = time.time()-86400*30
        for path in sorted(runs.rglob('*'), reverse=True):
            os.utime(path, (old, old), follow_symlinks=False)
        self.since = curate_repository.parse_since(time.strftime('%Y-%m-%d', time.localtime(time.time()-86400)))

    def tearDown(self):
        self.temporary.cleanup()

    def test_missing_cutoff_inventory_refuses_to_plan(self):
        with self.assertRaisesRegex(ValueError, 'Cutoff inventory'):
            curate_repository.plan(self.root)

    def test_data_roots_batches_and_policy_runs_are_never_proposed(self):
        result = curate_repository.plan(self.root, self.since)
        self.assertEqual([r['path'] for r in result['remove']], ['runs/failed-probe'])
        self.assertIn('runs/sol61-l1-20261104', result['protected'])
        self.assertIn('runs/lone-policy-run', result['protected'])

    def test_data_newer_than_the_cutoff_is_kept(self):
        write(self.root/'runs/failed-probe/late.log')
        self.assertEqual(curate_repository.plan(self.root, self.since)['remove'], [])

    def test_inventory_cutoff_and_since_take_the_earlier_time(self):
        inventory = self.root/'runs/engineering/cli-migration-cleanup-20261027/worktree-inventory.json'
        write(inventory)
        self.assertEqual([r['path'] for r in curate_repository.plan(self.root)['remove']], ['runs/failed-probe'])
        earlier = int((time.time()-86400*60)*1e9)
        self.assertEqual(curate_repository.plan(self.root, earlier)['remove'], [])

    def test_apply_replans_with_the_recorded_since(self):
        plan_file = self.root/'plan/plan.json'
        result = curate_repository.plan(self.root, self.since)
        write(plan_file, json.dumps(result))
        curate_repository.apply(plan_file)
        self.assertFalse((self.root/'runs/failed-probe').exists())
        self.assertTrue((self.root/'runs/factory-data/r14/bundle.json').exists())
        self.assertTrue((self.root/'runs/sol61-l1-20261104/batch.json').exists())


if __name__ == '__main__':
    unittest.main()
