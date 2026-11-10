import fcntl
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier import run_layout
from robofrontier.claude import recover_task as recovery
from robofrontier.delegation import Delegations
from robofrontier.run_setup import write_json
from robofrontier.runtime_store import RuntimeStore
from robofrontier.task_config import ROOT
from robofrontier.task_families import prepare
from test_engine_parity import HARNESS


class ClaudeRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        harness = self.root/'harness.json'
        harness.write_text(json.dumps(dict(HARNESS, engine='claude', topology='adaptive', startup_protocol='direct_controller_v2')))
        self.batch = self.root/'batch'
        self.run = prepare('transport-a04-d1', self.batch/'opus_subscription'/'transport-a04-d1', harness).resolve()
        write_json(self.batch/'batch.json', {'schema': 'robofrontier.claude-draft.v1', 'jobs': [
            {'profile': 'opus_subscription', 'case_id': 'transport-a04-d1', 'run_directory': str(self.run)}]})
        write_json(run_layout.batch_path(self.batch, 'engineering_status'),
                   {'status': 'running', 'jobs': [{'case_id': 'transport-a04-d1', 'status': 'needs_review', 'reason': 'dispatch_paused'}]})
        write_json(run_layout.path(self.run, 'engineering_status', 'claude'), {'status': 'needs_review', 'reason': 'dispatch_paused'})
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite'); self.addCleanup(self.store.close)
        for key, value in {'lifecycle': 'running', 'physics_state': 'running', 'integrity_valid': True,
                           'start_at': time.time()-30, 'execution_owner_attached': True}.items(): self.store.put(key, value)
        self.store.update_agent('Controller', thread_id='original-controller')
        self.store.begin_call('already-executed', 'Controller', 'move', {'robot': 'A'})
        self.store.finish_call('already-executed', {'execution_status': 'completed'})
        # A delegation whose native setup deadline passed before its gate opened.
        delegations = Delegations(self.store)
        self.robots = sorted(delegations.owners())[:2]
        batch = delegations.create('Controller', 'late-fork', [{'robots': self.robots, 'goal': 'g', 'done_when': 'd'}])
        self.child = batch['children'][0]['actor']
        delegations.claim('late-fork', 'meta'); delegations.created('late-fork', self.child, 'unverified-fork', 'meta')
        delegations.uncertain('late-fork', 'Native setup deadline expired', 'meta')
        self.assertTrue(self.store.get('dispatch_paused'))
        self.scratch = self.run/'private/engine/recovery-scratch'; self.scratch.mkdir(mode=0o700)
        pose = np.array([.25], dtype=np.float32)
        reader = SimpleNamespace(meta={'case_id': 'fixture', 'source_scene_sha256': 'fixture'},
                                 selected_frames=lambda indices: iter([(0, 1., pose)]))
        motion = patch('robofrontier.run_segments._last_frame', return_value=(reader, 0, 1., pose))
        motion.start(); self.addCleanup(motion.stop)
        self.processes = patch.object(recovery, 'live_sessions', return_value=[]); self.processes.start(); self.addCleanup(self.processes.stop)
        # The paused world still holds its lock.
        self.world = run_layout.path(self.run, 'world_lock').open('a+'); fcntl.flock(self.world, fcntl.LOCK_EX)
        self.addCleanup(self.world.close)

    def seal(self, store, timeout):
        self.world.close()
        for name, op in (('view', 'observe'), ('shutdown', 'shutdown')):  # the seal's own calls, as run_seal makes them
            store.begin_call('seal-fixture-'+name, 'Meta', op, {}); store.finish_call('seal-fixture-'+name, {'ok': True})
        store.put('lifecycle', 'interrupted'); store.put('physics_state', 'stopped')
        report = self.run/'private/outputs/seal.json'
        write_json(report, {'sealed': True, 'fresh_observation': True, 'unresolved_action_ids': []})
        store.event('RUN_SEALED', 'Meta', {'owner_was_live': True, 'report_ref': str(report)})
        return {'sealed': True, 'unresolved_action_ids': []}

    def test_inspection_is_read_only_and_names_the_unstarted_delegation(self):
        before = recovery._ledger(self.store.db)
        events = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        plan = recovery.inspect(self.run, ROOT)
        self.assertTrue(plan['world_live'])
        self.assertEqual(plan['failed_setups'], ['late-fork'])
        self.assertEqual(plan['role_threads'], ['original-controller', 'unverified-fork'])
        self.assertEqual(recovery._ledger(self.store.db), before)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], events)
        self.assertEqual(self.store.get('robot_owners')[self.robots[0]], self.child)

    def test_unsafe_states_are_refused(self):
        self.processes.stop()
        with patch.object(recovery.subprocess, 'run', return_value=SimpleNamespace(stdout='4242 claude -p --resume original-controller\n')):
            with self.assertRaisesRegex(recovery.RecoveryBlocked, 'still live'): recovery.inspect(self.run, ROOT)
        self.processes.start()
        self.store.begin_call('uncertain-original', 'Controller', 'move', {'robot': 'B'})
        with self.assertRaisesRegex(recovery.RecoveryBlocked, 'unsettled'): recovery.inspect(self.run, ROOT)
        self.store.finish_call('uncertain-original', {'execution_status': 'failed'})
        batch = self.store.get('delegations'); batch['late-fork']['children'][0]['start_status'] = 'sent'
        self.store.put('delegations', batch)
        with self.assertRaisesRegex(recovery.RecoveryBlocked, 'started a child'): recovery.inspect(self.run, ROOT)
        batch['late-fork']['children'][0]['start_status'] = 'pending'; self.store.put('delegations', batch)
        write_json(run_layout.batch_path(self.batch, 'engineering_status'),
                   {'status': 'running', 'jobs': [{'case_id': 'transport-a04-d1', 'status': 'starting'}]})
        with self.assertRaisesRegex(recovery.RecoveryBlocked, 'not handed this task back'): recovery.inspect(self.run, ROOT)

    def test_execution_seals_returns_robots_prepares_a_segment_and_runs_the_original_runner(self):
        before = recovery._ledger(self.store.db)
        store, run = self.store, self.run
        class Host:
            pid = 99999998
            def wait(self):
                store.put('segments', [{'index': 0}, {'index': 1}]); store.put('lifecycle', 'ended')
                write_json(run_layout.path(run, 'engineering_status', 'claude'), {'status': 'finished', 'reason': 'world_ended'})
                return 0
        launched = []
        def launcher(arguments, **options):
            launched.append((arguments, options)); return Host()
        with patch.object(recovery, 'validate_physical_restore', return_value={'verified': True, 'physics_steps': 0}):
            result = recovery.execute(self.run, ROOT, Path(os.sys.executable), self.scratch, seal=self.seal, launcher=launcher)
        self.assertEqual(result['phase'], 'closed')
        self.assertEqual(result['failed_setups'], ['late-fork'])
        self.assertEqual(recovery._ledger(self.store.db), before)
        self.assertEqual(self.store.get('segment'), 1)
        self.assertEqual({r: self.store.get('robot_owners')[r] for r in self.robots}, {r: 'Controller' for r in self.robots})
        batch = self.store.get('delegations')['late-fork']
        self.assertEqual((batch['status'], batch['outcome'], batch['children'][0]['start_status']), ('finished', 'failed', 'not_started'))
        self.assertEqual(self.store.agent(self.child)['delegation_state'], 'finished')
        kinds = [k for (k,) in self.store.db.execute('SELECT kind FROM events ORDER BY seq')]
        self.assertLess(kinds.index('MANUAL_TASK_RECOVERY'), kinds.index('DELEGATION_FAILED'))
        self.assertLess(kinds.index('DELEGATION_FAILED'), kinds.index('SEGMENT_PREPARED'))
        (arguments, options), = launched
        self.assertEqual(arguments[1:3], ['-I', '-c'])
        self.assertEqual(arguments[3], recovery.RUNNER)
        self.assertEqual(arguments[4:], [str(ROOT), str(self.batch), str(self.run)])
        self.assertEqual(options['cwd'], ROOT)
        self.assertTrue(Path(result['backup']).is_file())
        with self.assertRaisesRegex(recovery.RecoveryBlocked, 'already recovered'): recovery.inspect(self.run, ROOT)

    def test_only_an_explicit_runtime_upgrade_continues_a_recovered_run_again(self):
        store, run = self.store, self.run
        def host(segment):
            class Host:
                pid = 99999996
                def wait(self):
                    store.put('segments', [{'index': i} for i in range(segment+1)]); store.put('lifecycle', 'ended')
                    write_json(run_layout.path(run, 'engineering_status', 'claude'), {'status': 'finished', 'reason': 'world_ended'})
                    return 0
            return lambda *a, **k: Host()
        with patch.object(recovery, 'validate_physical_restore', return_value={'verified': True, 'physics_steps': 0}):
            recovery.execute(self.run, ROOT, Path(os.sys.executable), self.scratch, seal=self.seal, launcher=host(1))
            # Segment 1 stops again on review, sealed by its runner.
            # The resumed world clears its pending segment, as request-resume does.
            for key, value in {'lifecycle': 'interrupted', 'physics_state': 'stopped', 'dispatch_paused': True,
                               'pending_segment': None}.items():
                store.put(key, value)
            write_json(run_layout.path(run, 'engineering_status', 'claude'), {'status': 'needs_review', 'reason': 'session_error'})
            sealed = recovery.run_segments.output_dir(run, 1); sealed.mkdir(parents=True, exist_ok=True)
            write_json(sealed/'seal.json', {'sealed': True, 'fresh_observation': True, 'unresolved_action_ids': []})
            store.event('RUN_SEALED', 'Meta', {'owner_was_live': True, 'report_ref': str(sealed/'seal.json')})
            self.assertTrue(json.loads((run/'private/state/control/recovery.json').read_text())['prepared'])
            with self.assertRaisesRegex(recovery.RecoveryBlocked, 'already recovered'): recovery.inspect(run, ROOT)
            with self.assertRaisesRegex(recovery.RecoveryBlocked, 'stated reason'):
                recovery.execute(run, ROOT, Path(os.sys.executable), self.scratch, launcher=host(2), upgrade_from=ROOT)
            before = recovery._ledger(store.db)
            result = recovery.execute(run, ROOT, Path(os.sys.executable), self.scratch, launcher=host(2),
                                      upgrade_from=ROOT, reason='fixture upgrade')
        self.assertEqual(result['phase'], 'closed')
        self.assertEqual(result['authorization'], 'private/inputs/runtime-upgrades/2/authorization.json')
        self.assertEqual(store.get('segment'), 2)
        self.assertEqual(recovery._ledger(store.db), before)
        kinds = [k for (k,) in store.db.execute('SELECT kind FROM events ORDER BY seq')]
        self.assertIn('RUNTIME_UPGRADE_AUTHORIZED', kinds)
        self.assertEqual([a['phase'] for a in result['earlier_attempts']], ['closed'])
        # The grant is consumed by the segment it authorized.
        from robofrontier import runtime_upgrade
        with self.assertRaises(ValueError): runtime_upgrade.validate_authorization(run, store, result['authorization'])

    def test_a_failed_check_leaves_no_segment(self):
        with patch.object(recovery, 'validate_physical_restore', side_effect=recovery.RecoveryBlocked('restore failed')):
            with self.assertRaises(recovery.RecoveryBlocked):
                recovery.execute(self.run, ROOT, Path(os.sys.executable), self.scratch, seal=self.seal, launcher=None)
        self.assertEqual(self.store.get('segment', 0), 0)
        self.assertEqual(self.store.get('delegations')['late-fork']['status'], 'needs_review')
        record = json.loads((self.run/'private/state/control/recovery.json').read_text())
        self.assertEqual(record['phase'], 'needs_review'); self.assertNotIn('prepared', record)
        # Nothing was changed but the seal, so a second attempt may start from the closed world.
        plan = recovery.inspect(self.run, ROOT)
        self.assertFalse(plan['world_live']); self.assertEqual(plan['failed_setups'], ['late-fork'])
        store, run = self.store, self.run
        class Host:
            pid = 99999997
            def wait(self):
                store.put('segments', [{'index': 0}, {'index': 1}]); store.put('lifecycle', 'ended')
                write_json(run_layout.path(run, 'engineering_status', 'claude'), {'status': 'finished', 'reason': 'world_ended'})
                return 0
        with patch.object(recovery, 'validate_physical_restore', return_value={'verified': True, 'physics_steps': 0}):
            result = recovery.execute(self.run, ROOT, Path(os.sys.executable), self.scratch, seal=None, launcher=lambda *a, **k: Host())
        self.assertEqual(result['phase'], 'closed')
        self.assertEqual([attempt['phase'] for attempt in result['earlier_attempts']], ['needs_review'])
        self.assertEqual(self.store.get('segment'), 1)


class HandbackTests(unittest.TestCase):
    def test_batch_waits_for_a_recovery_then_takes_its_outcome(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary).resolve()/'run'
            control = run/'private/state/control'; control.mkdir(parents=True)
            write_json(control/'recovery.json', {'phase': 'closed', 'segment': 1, 'host_exit_code': 0})
            jobs = [{'run_directory': str(run), 'status': 'needs_review'}]
            with patch.object(recovery.run_segments, 'owner_released', side_effect=[False, True]):
                waits = []
                recovery.wait_for_recoveries(jobs, sleep=waits.append)
            self.assertEqual(waits, [1])
            self.assertEqual(jobs[0]['status'], 'closed')


if __name__ == '__main__': unittest.main()
