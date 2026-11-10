import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.batch.codex_batch import memory_snapshot
from robofrontier.engines.codex.launch import initialize_codex_home


class CodexStartupTests(unittest.TestCase):
    def test_handshake_uses_batch_home_and_propagates_failure(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CODEX_HOME': tmp+'/home'}):
            folder=Path(tmp)
            with patch('robofrontier.engines.codex.launch.subprocess.run') as run:
                initialize_codex_home({'args':['-c','model="test"']}, folder)
                self.assertIn('codex_initialize.js',run.call_args.args[0][1])
                self.assertEqual(run.call_args.args[0][-2:],['-c','model="test"'])
                self.assertTrue(run.call_args.kwargs['check'])
            with patch('robofrontier.engines.codex.launch.subprocess.run',side_effect=subprocess.CalledProcessError(1,'node')):
                with self.assertRaises(subprocess.CalledProcessError):
                    initialize_codex_home({'args':[]}, folder)

    def test_initializations_with_shared_home_are_serialized(self):
        import concurrent.futures
        import threading
        import time
        active=0
        peak=0
        gate=threading.Lock()
        def fake_run(*args,**kwargs):
            nonlocal active,peak
            with gate:
                active+=1
                peak=max(peak,active)
            time.sleep(.03)
            with gate:active-=1
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CODEX_HOME': tmp+'/home'}):
            with patch('robofrontier.engines.codex.launch.subprocess.run',side_effect=fake_run):
                with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                    list(pool.map(lambda _:initialize_codex_home({'args':[]},Path(tmp)),range(6)))
        self.assertEqual(peak,1)

    def test_memory_snapshot_does_not_claim_capacity(self):
        self.assertFalse(memory_snapshot()['parallel_memory_requirement_known'])


if __name__=='__main__':unittest.main()
