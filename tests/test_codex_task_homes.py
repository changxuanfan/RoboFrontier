import hashlib
from robofrontier import preflight_probe
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from contextlib import contextmanager

from robofrontier.codex import batch as benchmark
from robofrontier.codex import launch
from robofrontier.run_setup import write_json


class CodexTaskHomesTests(unittest.TestCase):
    def test_job_scope_uses_one_engine_distinct_channels_and_never_redispatches_a_failed_host(self):
        from robofrontier.codex.job_engine import fingerprint as gateway_fingerprint
        from robofrontier.codex.tool_backend import fingerprint as backend_fingerprint
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            folder, private = root/'batch', root/'engine'
            home = private/'codex'
            home.mkdir(parents=True)
            (home/'auth.json').write_text('synthetic fixture; never read by this orchestration test')
            selected = {'provider': 'openai', 'tool_backend': 'landlock-v1', 'runner_backend': 'slurm-managed-v1'}
            backend = backend_fingerprint(selected)
            gateway_sha = gateway_fingerprint()
            jobs = []
            for case in ('one', 'two', 'three'):
                run = folder/'luna_subscription'/case
                write_json(run/'private/inputs/codex.json', {'profile': selected, 'args': [], 'tool_backend_sha256': backend})
                write_json(run/'private/inputs/models.json', {'models': []})
                (run/'private/outputs').mkdir(parents=True)
                jobs.append({'profile': 'luna_subscription', 'case_id': case, 'run_directory': str(run), 'status': 'prepared'})
            catalog = (Path(jobs[0]['run_directory'])/'private/inputs/models.json').read_bytes()
            write_json(root/'runs/engineering/model-compatibility/luna_subscription/report.json', {
                'passed': True, 'profile_sha256': hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
                'catalog_sha256': hashlib.sha256(catalog).hexdigest(), 'codex_version': 'test-cli',
                'probe_version': preflight_probe.VERSION, 'tool_backend': 'landlock-v1',
                'broker_tools_verified': True, 'tool_backend_sha256': backend, 'job_gateway_sha256': gateway_sha})
            write_json(folder/'batch.json', {'status': 'prepared_not_started', 'jobs': jobs,
                                           'execution': {'codex_home_scope': 'job', 'startup_interval_s': 0}})
            entered, launched = [], []
            @contextmanager
            def engine(admitted, *, env):
                entered.append(admitted)
                yield {'endpoint': str(private/'s'), 'backend': 'slurm-managed-v1', 'fingerprint': gateway_sha}, None
            def host(*args, **kwargs):
                self.assertEqual(len(entered), 1)
                launched.append(kwargs['env'])
                return SimpleNamespace(pid=99999, wait=lambda: 1)
            with patch.object(benchmark, 'ROOT', root), patch.object(benchmark, 'verify_inputs', return_value=[]), \
                    patch.object(benchmark, 'initialize_codex_home') as initialize, \
                    patch.object(benchmark.subprocess, 'run') as native_start, \
                    patch.object(benchmark.subprocess, 'check_output', return_value='test-cli'), \
                    patch.object(benchmark.subprocess, 'Popen', side_effect=host), \
                    patch.object(benchmark, 'try_continue') as redispatch, \
                    patch('robofrontier.codex.job_engine.engine', side_effect=engine), \
                    patch.dict(os.environ, {'SLURM_JOB_ID': 'fixture-only', 'CODEX_HOME': str(home),
                                            'ROBOFRONTIER_JOB_PRIVATE_ROOT': str(private)}):
                benchmark.run_batch(folder, 3)
                initialize.assert_not_called()
                native_start.assert_not_called()
                redispatch.assert_not_called()
            self.assertEqual(len(launched), 3)
            self.assertEqual(len({env['ROBOFRONTIER_CODEX_TASK'] for env in launched}), 3)
            self.assertEqual({env['ROBOFRONTIER_CODEX_GATEWAY'] for env in launched}, {str(private/'s')})
            self.assertEqual(json.loads((folder/'batch.json').read_text())['status'], 'needs_review')

    def test_all_task_homes_are_initialized_serially_before_concurrent_hosts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = root/'batch'
            selected = {'provider': 'openai_api', 'env_key': 'RF_TEST_KEY'}
            launch = {'profile': selected, 'args': []}
            jobs = []
            for case in ('one', 'two', 'three'):
                run = batch/'luna'/case
                write_json(run/'private/inputs/codex.json', launch)
                write_json(run/'private/inputs/models.json', {'models': []})
                (run/'private/outputs').mkdir(parents=True)
                jobs.append({'profile': 'luna', 'case_id': case, 'run_directory': str(run), 'status': 'prepared'})
            catalog = (Path(jobs[0]['run_directory'])/'private/inputs/models.json').read_bytes()
            write_json(root/'runs/engineering/model-compatibility/luna/report.json', {
                'passed': True, 'profile_sha256': hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest(),
                'catalog_sha256': hashlib.sha256(catalog).hexdigest(), 'codex_version': 'test-cli',
                'probe_version': preflight_probe.VERSION})
            write_json(batch/'batch.json', {'status': 'prepared_not_started', 'jobs': jobs,
                'execution': {'codex_home_scope': 'task', 'startup_interval_s': 0}})
            initialized, launched = [], []
            def initialize(launch, folder, *, env):
                self.assertFalse(launched)
                initialized.append(env['CODEX_HOME'])
            def host(*args, **kwargs):
                self.assertEqual(len(initialized), 3)
                launched.append(kwargs['env']['CODEX_HOME'])
                return SimpleNamespace(pid=99999, wait=lambda: 0)
            with patch.object(benchmark, 'ROOT', root), patch.object(benchmark, 'verify_inputs', return_value=[]), \
                    patch.object(benchmark, 'initialize_codex_home', side_effect=initialize), \
                    patch.object(benchmark.subprocess, 'check_output', return_value='test-cli'), \
                    patch.object(benchmark.subprocess, 'run'), \
                    patch.object(benchmark.subprocess, 'Popen', side_effect=host), \
                    patch.dict(os.environ, {'RF_TEST_KEY': 'never-persist-this'}):
                benchmark.run_batch(batch, 3)
            self.assertEqual(len(set(initialized)), 3)
            self.assertEqual(set(initialized), set(launched))
            for job in jobs:
                marker = json.loads((Path(job['run_directory'])/'codex-home.json').read_text())
                home = Path(marker['codex_home'])
                self.assertTrue(home.is_dir())
                self.assertFalse(home.is_relative_to(batch))
            self.assertEqual(json.loads((batch/'batch.json').read_text())['status'], 'closed')
            for path in root.rglob('*'):
                if path.is_file():
                    self.assertNotIn(b'never-persist-this', path.read_bytes())


class SharedCodexHomeTests(unittest.TestCase):
    def test_batches_never_default_to_the_personal_codex_home(self):
        self.assertEqual(launch.codex_home({}), launch.BENCHMARK_CODEX_HOME.resolve())
        self.assertNotEqual(launch.codex_home({}), (Path.home()/'.codex').resolve())
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(launch.codex_home({'CODEX_HOME': tmp}), Path(tmp).resolve())


if __name__ == '__main__':
    unittest.main()
