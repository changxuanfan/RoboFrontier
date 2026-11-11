import fcntl
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
import zipfile
from unittest.mock import patch

from robofrontier.configuration import load_configuration
from robofrontier.batch import slurm_job as slurm


class SlurmJobTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.repo = self.root/'repo'
        self.repo.mkdir()
        (self.repo/'robofrontier').mkdir()
        (self.repo/'robofrontier/__init__.py').write_text('"""Frozen fixture."""\n')
        subprocess.run(['git', 'init', '-q', str(self.repo)], check=True)
        subprocess.run(['git', 'add', '.'], cwd=self.repo, check=True)
        subprocess.run(['git', '-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid',
                        'commit', '-qm', 'fixture'], cwd=self.repo, check=True)
        receipt = self.repo/'runs/engineering/model-compatibility/luna/report.json'
        receipt.parent.mkdir(parents=True)
        receipt.write_text(json.dumps({'passed': True}))
        self.asset = self.root/'assets.tar.gz'
        self.asset.write_bytes(b'fixture verified only by hash; no simulator is launched')
        self.config = load_configuration(host='slurm')
        self.submission = self.root/'submission'
        self.local = self.root/'scratch/job'
        self.local.parent.mkdir()

    def prepare(self):
        with patch('robofrontier.batch.handoff.ensure_asset_archive', return_value=self.asset):
            return slurm.submit(self.config, self.submission, root=self.repo)

    def stage(self):
        self.prepare()
        with patch.object(slurm.platform, 'system', return_value='Linux'), \
                patch.object(slurm, '_local_storage', return_value='xfs'), \
                patch.dict(os.environ, {'SLURM_JOB_ID': '123'}):
            return slurm.stage(self.submission, self.local)

    def test_submission_freezes_source_without_credentials_or_model_calls(self):
        (self.repo/'.env').write_text('SECRET=must-not-travel\n')
        (self.repo/'auth.json').write_text('untracked login must not travel')
        report = self.prepare()
        self.assertFalse(report['queued'])
        self.assertEqual(report['model_calls_during_preparation'], 0)
        manifest, config = slurm._verify_submission(self.submission)
        self.assertEqual(config, self.config)
        with tarfile.open(self.submission/'source.tar') as archive:
            self.assertNotIn('.env', archive.getnames())
            self.assertNotIn('auth.json', archive.getnames())
        self.assertIn('launcher/robofrontier/__init__.py', manifest['sha256'])
        script = (self.submission/'job.sbatch').read_text()
        self.assertLess(script.index('srun '), script.index('stage-out '))
        self.assertIn('cd "$submission/launcher"', script)
        self.assertIn('--wait=120', script)
        subprocess.run(['bash', '-n', str(self.submission/'job.sbatch')], check=True)

    def test_dirty_tracked_source_is_rejected_before_snapshot(self):
        (self.repo/'robofrontier/__init__.py').write_text('changed')
        with patch('robofrontier.batch.handoff.ensure_asset_archive') as assets:
            with self.assertRaisesRegex(ValueError, 'Commit tracked changes'):
                slurm.submit(self.config, self.submission, root=self.repo)
            assets.assert_not_called()
        self.assertFalse(self.submission.exists())

    def test_changed_frozen_payload_is_rejected_before_node_creation(self):
        self.prepare()
        (self.submission/'policy-assets.tar.gz').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'submission changed'):
            slurm.stage(self.submission, self.local)
        self.assertFalse(self.local.exists())

    def test_stage_uses_node_local_cache_and_does_not_copy_login_state(self):
        report = self.stage()
        self.assertEqual(report['status'], 'staged')
        source = self.local/'source'
        self.assertTrue((source/'robofrontier/__init__.py').is_file())
        cache = source/'runs/asset-cache'/(slurm.checksum(self.asset)+'.tar.gz')
        self.assertEqual(cache.read_bytes(), self.asset.read_bytes())
        self.assertFalse((source/'.env').exists())
        self.assertFalse((source/'.codex').exists())
        self.assertTrue((source/'runs/engineering/model-compatibility/luna/report.json').is_file())
        with patch.object(slurm.platform, 'system', return_value='Linux'), \
                patch.dict(os.environ, {'SLURM_JOB_ID': '123'}):
            with self.assertRaisesRegex(ValueError, 'never restart'):
                slurm.stage(self.submission, self.local)

    def test_network_or_unknown_scratch_is_rejected(self):
        for kind in ('lustre', 'nfs', 'UNKNOWN'):
            with self.subTest(kind=kind), patch.object(slurm.subprocess, 'check_output', return_value=kind):
                with self.assertRaisesRegex(ValueError, 'Node-local scratch'):
                    slurm._local_storage(self.root)

    def test_live_world_lock_blocks_stage_out_before_copying(self):
        self.stage()
        lock_path = self.local/'source/runs/policy/batch/luna/case/private/state/world.lock'
        lock_path.parent.mkdir(parents=True)
        with lock_path.open('a+') as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(ValueError, 'Writer still live'):
                slurm.stage_out(self.local, self.submission, 0)
        self.assertFalse((self.submission/'results').exists())

    def test_a_fifo_named_like_a_lock_does_not_block_stage_out(self):
        import signal
        self.stage()
        run = self.local/'source/runs/policy/batch/luna/case'
        (run/'workspace').mkdir(parents=True)
        os.mkfifo(run/'workspace/world.lock')
        (run/'private/state/control').mkdir(parents=True)
        os.mkfifo(run/'private/state/control/world.lock')
        def timeout(*_): raise TimeoutError('stage-out blocked on a FIFO')
        previous = signal.signal(signal.SIGALRM, timeout)
        signal.alarm(10)
        try:
            report = slurm.stage_out(self.local, self.submission, 1)
        finally:
            signal.alarm(0); signal.signal(signal.SIGALRM, previous)
        self.assertTrue((self.submission/'results').is_dir())
        self.assertIn({'path': str((run/'private/state/control/world.lock').resolve()), 'issue': 'nonregular lock'}, report['issues'])
        self.assertIn('runs/policy/batch/luna/case/workspace/world.lock', [i['path'] for i in report['issues']])

    def test_failed_collection_returns_stopped_raw_motion_and_sessions_without_auth(self):
        self.stage()
        source = self.local/'source'
        files = {
            'runs/policy/batch/luna/case/private/state/runtime.sqlite': b'stopped SQLite fixture',
            'runs/policy/batch/luna/case/private/outputs/motion/frames.bin': b'exact motion',
            'runs/state-assets/abc': b'frozen asset',
            '.robofrontier/codex/task/sessions/session.jsonl': b'exact native session\n',
            '.robofrontier/codex/task/auth.json': b'PRIVATE AUTH',
            '.robofrontier/codex/task/state.sqlite': b'private CLI runtime state',
            'runs/policy/batch/haiku/case/private/claude-config/.credentials.json': b'PRIVATE CLAUDE AUTH',
            'runs/policy/batch/haiku/case/private/claude-config/projects/project/session.jsonl': b'Claude session',
        }
        for relative, content in files.items():
            path = source/relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        report = slurm.stage_out(self.local, self.submission, 1)
        self.assertTrue(report['raw_fallback'])
        self.assertEqual(report['status'], 'needs_review')
        output = self.submission/'results'
        self.assertEqual((output/'native-sessions/task/sessions/session.jsonl').read_bytes(), b'exact native session\n')
        self.assertFalse(any(p.name == 'auth.json' for p in output.rglob('*')))
        self.assertFalse(any(p.name == 'state.sqlite' for p in output.rglob('*')))
        self.assertFalse(any(p.name == '.credentials.json' for p in output.rglob('*')))
        self.assertTrue(any(p.name == 'session.jsonl' and 'claude-config' in str(p) for p in output.rglob('*')))
        for name, expected in report['sha256'].items():
            self.assertEqual(slurm.checksum(output/name), expected)
        self.assertTrue((source/'.robofrontier/codex/task/auth.json').exists())
        with self.assertRaisesRegex(ValueError, 'destination exists'):
            slurm.stage_out(self.local, self.submission, 1)

    def test_raw_fallback_with_a_workspace_symlink_still_stages_motion_and_records_the_link(self):
        self.stage()
        source = self.local/'source'
        run = source/'runs/policy/batch/luna/case'
        (run/'private/outputs/motion').mkdir(parents=True)
        (run/'private/outputs/motion/frames.bin').write_bytes(b'only copy')
        (run/'private/state').mkdir(parents=True)
        (run/'private/state/runtime.sqlite').write_bytes(b'stopped SQLite fixture')
        (run/'workspace/.tmp/venv/bin').mkdir(parents=True)
        (run/'workspace/.tmp/venv/bin/python').symlink_to('/etc/hosts')
        (run/'workspace/linked').symlink_to(self.root, target_is_directory=True)
        os.mkfifo(run/'workspace/pipe')
        unreadable = run/'workspace/locked.txt'
        unreadable.write_bytes(b'unreadable')
        unreadable.chmod(0)
        self.addCleanup(unreadable.chmod, 0o600)
        report = slurm.stage_out(self.local, self.submission, 1)
        output = self.submission/'results'
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual((output/'runs/policy/batch/luna/case/private/outputs/motion/frames.bin').read_bytes(), b'only copy')
        self.assertTrue((output/'runs/policy/batch/luna/case/private/state/runtime.sqlite').is_file())
        issues = {item['path']: item for item in report['issues']}
        base = 'runs/policy/batch/luna/case/workspace/'
        self.assertEqual(issues[base+'.tmp/venv/bin/python'], {'path': base+'.tmp/venv/bin/python', 'issue': 'symlink', 'link': '/etc/hosts'})
        self.assertEqual(issues[base+'linked']['issue'], 'symlink')
        self.assertEqual(issues[base+'pipe']['issue'], 'nonregular')
        if os.geteuid() != 0:
            self.assertEqual(issues[base+'locked.txt']['issue'], 'not copied')
        self.assertFalse(any(p.is_symlink() for p in output.rglob('*')))
        self.assertFalse((output/base/'.tmp/venv/bin/python').exists())
        self.assertFalse((output/base/'linked').exists())
        self.assertEqual(json.loads((output/'stage-out.json').read_text())['issues'], report['issues'])
        for name, expected in report['sha256'].items():
            self.assertEqual(slurm.checksum(output/name), expected)

    def test_codex_session_symlink_is_recorded_not_fatal(self):
        self.stage()
        sessions = self.local/'source/.robofrontier/codex/task/sessions'
        sessions.mkdir(parents=True)
        (sessions/'session.jsonl').write_bytes(b'exact native session\n')
        (sessions/'other.jsonl').symlink_to(self.local/'source/.robofrontier/codex/task/sessions/session.jsonl')
        report = slurm.stage_out(self.local, self.submission, 1)
        output = self.submission/'results'
        self.assertEqual((output/'native-sessions/task/sessions/session.jsonl').read_bytes(), b'exact native session\n')
        self.assertFalse((output/'native-sessions/task/sessions/other.jsonl').exists())
        self.assertEqual([i['issue'] for i in report['issues']], ['symlink'])
        self.assertEqual(report['status'], 'needs_review')

    def test_a_fence_failing_on_exit_keeps_the_collected_archive(self):
        from contextlib import contextmanager
        from robofrontier.batch.slurm_proxy import EgressError
        self.stage()
        source = (self.local/'source').resolve()
        archive = source/'runs/exports/collected.zip'
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('manifest.json', '{}')
        @contextmanager
        def fenced(config, local, *, on_failure):
            yield
            raise EgressError('route lost after the run sealed')
        result = {'archive': str(archive), 'status': 'closed', 'collection_complete': True}
        with patch.object(slurm, 'ROOT', source), patch.object(slurm, 'subscription_environment', fenced), \
                patch('robofrontier.cli.prepare'), patch('robofrontier.runtime.policy_env.apply_default'), \
                patch('robofrontier.cli.run', return_value=result):
            with self.assertRaises(EgressError):
                slurm.execute(self.local)
        written = json.loads((self.local/'execution-result.json').read_text())
        self.assertEqual(written, {**result, 'context_failure': 'EgressError'})
        report = slurm.stage_out(self.local, self.submission, 1)
        self.assertFalse(report['raw_fallback'])
        self.assertEqual(report['status'], 'needs_review')
        self.assertEqual(report['context_failure'], 'EgressError')
        self.assertEqual((self.submission/'results/evidence.zip').read_bytes(), archive.read_bytes())

    def test_a_stop_before_start_is_recorded(self):
        self.stage()
        source = (self.local/'source').resolve()
        (self.local/'STOP').touch()
        with patch.object(slurm, 'ROOT', source), patch('robofrontier.cli.prepare'), \
                patch('robofrontier.runtime.policy_env.apply_default'), \
                patch('robofrontier.cli.run') as run:
            self.assertEqual(slurm.execute(self.local), {'status': 'stopped_before_start'})
            run.assert_not_called()
        self.assertEqual(json.loads((self.local/'execution-result.json').read_text()), {'status': 'stopped_before_start'})

    def test_successful_collection_returns_only_one_evidence_zip(self):
        self.stage()
        archive = self.local/'source/runs/exports/collected.zip'
        archive.parent.mkdir(parents=True)
        with zipfile.ZipFile(archive, 'w') as output:
            output.writestr('manifest.json', '{}')
        (self.local/'execution-result.json').write_text(json.dumps({
            'archive': str(archive), 'status': 'closed', 'collection_complete': True}))
        report = slurm.stage_out(self.local, self.submission, 0)
        self.assertFalse(report['raw_fallback'])
        self.assertEqual(report['status'], 'collected')
        self.assertEqual((self.submission/'results/evidence.zip').read_bytes(), archive.read_bytes())
        self.assertFalse((self.submission/'results/native-sessions').exists())

    def test_stop_and_snapshot_use_json_without_opening_databases(self):
        self.stage()
        batch = self.local/'source/runs/policy/batch'
        run = batch/'luna/case'
        run.mkdir(parents=True)
        (batch/'batch.json').write_text(json.dumps({'status': 'running', 'jobs': [
            {'run_directory': str(run)}]}))
        with patch('sqlite3.connect', side_effect=AssertionError('must not open SQLite')):
            slurm.request_stop(self.local)
            status = slurm.snapshot(self.local, self.submission)
        self.assertTrue((run/'STOP').exists())
        self.assertEqual(status['status'], 'running')

    def test_queue_options_keep_task_and_allocation_clocks_distinct(self):
        command = slurm.queue_command(self.config['slurm'], self.submission)
        self.assertIn('--time=1500', command)
        self.assertIn('--signal=B:USR1@600', command)
        self.assertIn('--gpus=1', command)
        self.assertEqual(self.config['batch']['task_wall_limit_s'], 86400)

    def test_subscription_submission_is_one_allocation_serialized_by_credential_stream(self):
        from robofrontier.engines.codex.job_engine import fingerprint
        self.config = load_configuration(host='slurm', overrides={
            'policy': {'profile': 'luna_subscription'},
            'runtime': {'codex_home_scope': 'job', 'codex_tool_backend': 'landlock-v1'},
            'slurm': {'auth_mode': 'subscription', 'credential_store': str(self.root/'not-yet-provisioned')}})
        report = self.repo/'runs/engineering/model-compatibility/luna_subscription/report.json'
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({'passed': True, 'job_gateway_sha256': fingerprint()}))
        # Submission freezes a reference only. The credential directory does
        # not exist and no native process, login or scheduler call is needed.
        self.prepare()
        manifest, _ = slurm._verify_submission(self.submission)
        self.assertIsNone(manifest['credential_env'])
        command = slurm.queue_command(self.config['slurm'], self.submission)
        self.assertEqual(command.count('--nodes=1'), 1)
        self.assertEqual(command.count('--ntasks=1'), 1)
        self.assertEqual(command.count('--gpus=1'), 1)
        self.assertIn('--dependency=singleton', command)
        self.assertTrue(any(arg.startswith('--job-name=rf-auth-') for arg in command))
        self.assertFalse((self.root/'not-yet-provisioned').exists())

    def test_subscription_requires_fresh_gateway_qualification_and_private_store(self):
        self.config = load_configuration(host='slurm', overrides={
            'policy': {'profile': 'luna_subscription'},
            'runtime': {'codex_home_scope': 'job', 'codex_tool_backend': 'landlock-v1'},
            'slurm': {'auth_mode': 'subscription', 'credential_store': str(self.root/'credentials')}})
        report = self.repo/'runs/engineering/model-compatibility/luna_subscription/report.json'
        report.parent.mkdir(parents=True)
        report.write_text(json.dumps({'passed': True, 'job_gateway_sha256': 'stale'}))
        with self.assertRaisesRegex(ValueError, 'job-gateway subscription preflight'):
            self.prepare()
        self.config['slurm']['credential_store'] = str(self.repo/'private-auth')
        with self.assertRaisesRegex(ValueError, 'outside checkouts'):
            self.prepare()

    def test_claude_token_runs_through_the_mac_route_without_a_credential_store(self):
        relay = self.root/'egress'
        # The submission carries the profile's two precheck receipts, which the job checks again.
        receipts = {}
        for name in ('basic', 'blocked'):
            receipts[name] = self.root/(name+'-receipt.json'); receipts[name].write_text('{"passed": true}')
        ready = patch('robofrontier.engines.claude.claude_readiness.require_ready',
                      return_value={'basic_receipt': str(receipts['basic']), 'blocked_receipt': str(receipts['blocked'])})
        ready.start(); self.addCleanup(ready.stop)
        self.config = load_configuration(host='slurm', overrides={
            'schema_version': 8, 'policy': {'engine': 'claude', 'profile': 'haiku_subscription_token'},
            'slurm': {'egress_mode': 'mac-ssh', 'egress_root': str(relay), 'egress_pause_s': 120}})
        # The token must be in the checkout's .env (ignored by Git), never only in the shell.
        with self.assertRaisesRegex(ValueError, 'keep CLAUDE_CODE_OAUTH_TOKEN in'):
            with patch('robofrontier.batch.handoff.ensure_asset_archive', return_value=self.asset):
                slurm.submit(self.config, self.root/'without-env', root=self.repo)
        (self.repo/'.env').write_text('CLAUDE_CODE_OAUTH_TOKEN=fixture-not-a-token\n')
        with patch('robofrontier.batch.handoff.ensure_asset_archive', return_value=self.asset):
            slurm.submit(self.config, self.submission, root=self.repo)
        manifest, _ = slurm._verify_submission(self.submission)
        self.assertEqual((manifest['credential_env'], manifest['auth_mode']), ('CLAUDE_CODE_OAUTH_TOKEN', 'api'))
        self.assertEqual(manifest['credential_file'], str((self.repo/'.env').resolve()))
        self.assertEqual({name for name in manifest['sha256'] if name.startswith('claude-')},
                         {'claude-precheck.json', 'claude-blocked-precheck.json'})
        self.assertNotIn('fixture-not-a-token', ''.join(path.read_text(errors='ignore') for path in self.submission.rglob('*') if path.is_file()))
        self.assertNotIn('--dependency=singleton', slurm.queue_command(self.config['slurm'], self.submission))
        self.config['slurm']['egress_root'] = str(self.repo/'egress')
        with self.assertRaisesRegex(ValueError, 'egress state outside'):
            with patch('robofrontier.batch.handoff.ensure_asset_archive', return_value=self.asset):
                slurm.submit(self.config, self.root/'second', root=self.repo)
        # Only Claude carries a token this way; Codex keeps the job-scoped subscription store.
        with self.assertRaisesRegex(ValueError, 'Mac egress requires'):
            load_configuration(host='slurm', overrides={'schema_version': 8, 'slurm': {'egress_mode': 'mac-ssh', 'egress_root': str(relay)}})

    def test_claude_route_admits_egress_and_restores_the_environment(self):
        config = load_configuration(host='slurm', overrides={
            'schema_version': 8, 'policy': {'engine': 'claude', 'profile': 'haiku_subscription_token'},
            'slurm': {'egress_mode': 'mac-ssh', 'egress_root': str(self.root/'egress')}})
        self.local.mkdir()
        seen = {}
        from contextlib import contextmanager
        @contextmanager
        def route(cfg, *, on_failure):
            seen['private'] = os.environ['ROBOFRONTIER_JOB_PRIVATE_ROOT']; seen['failure'] = on_failure
            os.environ['HTTPS_PROXY'] = 'http://rf:x@127.0.0.1:1'
            yield
        stops = []
        with patch.object(slurm.platform, 'system', return_value='Linux'), \
                patch.dict(os.environ, {'SLURM_JOB_ID': '123'}), patch('robofrontier.batch.slurm_proxy.environment', route):
            before = dict(os.environ)
            with slurm.subscription_environment(config, self.local, on_failure=lambda: stops.append(1)):
                self.assertEqual(Path(seen['private']), (self.local/'engine').resolve())
                self.assertNotIn('CODEX_HOME', os.environ)
            self.assertEqual(dict(os.environ), before)
        seen['failure']()
        self.assertTrue((self.local/'engine/EGRESS_ERROR').exists()); self.assertEqual(stops, [1])

    def test_source_archive_link_or_path_escape_is_rejected_before_extraction(self):
        archive = self.root/'bad.tar'
        for name, link in (('../outside', False), ('safe-link', True)):
            with tarfile.open(archive, 'w') as output:
                entry = tarfile.TarInfo(name)
                if link:
                    entry.type = tarfile.SYMTYPE
                    entry.linkname = '/etc/passwd'
                    output.addfile(entry)
                else:
                    entry.size = 1
                    output.addfile(entry, io.BytesIO(b'x'))
            target = self.root/'extract'
            with self.assertRaisesRegex(ValueError, 'Unsafe source'):
                slurm._extract_source(archive, target)
            self.assertFalse(target.exists())


if __name__ == '__main__':
    unittest.main()
