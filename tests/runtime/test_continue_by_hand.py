"""`robofrontier continue`: an operator continues stopped runs of a batch as the same trials."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier import cli
from robofrontier.configuration import load_configuration
from robofrontier.runtime import segments
from robofrontier.runtime.store import RuntimeStore
from engines.test_engine_parity import prepared


class Reader:
    meta = {'case_id': 'transport-a04-d1', 'source_scene_sha256': 'scene'}
    def selected_frames(self, indices):
        for i in indices: yield i, 12.5, np.zeros(9)


class ContinueByHandTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        self.batch = root/'batch'; self.batch.mkdir()
        self.runs = {}
        for case in ('transport-a04-d1', 'transport-a04-d2'):
            (root/case).mkdir(); self.runs[case] = prepared(root/case, 'codex', case).resolve()
        config = load_configuration(None, {'policy': {'engine': 'codex'}})
        (self.batch/'effective-config.json').write_text(json.dumps(config))
        digest = hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()
        self.document = {'status': 'closed', 'effective_configuration_sha256': digest,
                         'execution': {**config['runtime'], 'startup_interval_s': config['batch']['startup_interval_s']},
                         'jobs': [{'case_id': case, 'run_directory': str(run), 'status': 'closed'} for case, run in self.runs.items()]}
        (self.batch/'batch.json').write_text(json.dumps(self.document))
        for run in self.runs.values():
            store = RuntimeStore(run/'private/state/runtime.sqlite')
            store.put('lifecycle', 'ended'); store.put('start_at', time.time()-30)
            store.event('TEAM_FINISH_PROPOSED', 'Meta', {}); store.close()
        patcher = patch.object(segments, '_last_frame', lambda run, segment: (Reader(), 41, 12.5, np.zeros(9)))
        patcher.start(); self.addCleanup(patcher.stop)

    def test_a_named_finished_run_continues_and_the_batch_reopens_for_it_only(self):
        report = cli.continue_runs(self.batch, ['transport-a04-d2'])
        self.assertEqual((report['prepared'], report['refused']), (['transport-a04-d2'], {}))
        document = json.loads((self.batch/'batch.json').read_text())
        self.assertEqual(document['status'], 'running')
        self.assertEqual([j['status'] for j in document['jobs']], ['closed', 'prepared'])
        store = RuntimeStore(self.runs['transport-a04-d2']/'private/state/runtime.sqlite')
        try:
            self.assertEqual((store.get('lifecycle'), store.get('segment')), ('resuming', 1))
            self.assertEqual(store.get('after_score')['reason'], 'finish')
        finally: store.close()

    def test_every_run_that_may_continue_by_default_and_unknown_cases_are_refused(self):
        with self.assertRaisesRegex(ValueError, 'Not in this batch'): cli.continue_runs(self.batch, ['mosaic-x'])
        self.assertEqual(sorted(cli.continue_runs(self.batch)['prepared']), sorted(self.runs))
        # Now prepared: a second call refuses each run and leaves them as they are.
        report = cli.continue_runs(self.batch)
        self.assertEqual(report['prepared'], [])
        self.assertTrue(all('already prepared' in why for why in report['refused'].values()))


if __name__ == '__main__': unittest.main()
