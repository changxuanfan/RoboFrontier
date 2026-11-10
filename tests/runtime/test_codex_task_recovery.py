import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier.engines.codex import recover_task as recovery
from robofrontier.engines.common import recovery as common_recovery
from robofrontier.engines.codex.job_engine import task_id
from robofrontier.runtime.layout import path as run_path
from robofrontier.runtime.setup import write_json
from robofrontier.runtime.store import RuntimeStore
from robofrontier.tasks.config import ROOT
from engines.test_engine_parity import prepared


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(); self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.run = prepared(self.root, 'codex').resolve()
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite'); self.addCleanup(self.store.close)
        for key, value in {'lifecycle': 'interrupted', 'physics_state': 'stopped', 'dispatch_paused': True,
                           'integrity_valid': True, 'start_at': time.time()-30}.items(): self.store.put(key, value)
        self.store.update_agent('Controller', thread_id='original-controller')
        self.store.begin_call('already-executed', 'Controller', 'move', {'robot': 'A'})
        self.store.finish_call('already-executed', {'execution_status': 'completed'})
        self.store.event('RUN_SEALED', 'Meta', {'owner_was_live': True, 'report_ref': str(self.run/'private/outputs/seal.json')})
        write_json(self.run/'private/outputs/seal.json', {'sealed': True, 'fresh_observation': True, 'unresolved_action_ids': []})
        write_json(run_path(self.run, 'host_process', 'codex'), {'pid': 99999999})
        run_path(self.run, 'host_log', 'codex').write_text(json.dumps({'at': time.time()-5, 'event': 'model_host_exited', 'signal': 'gateway-lost'})+'\n')
        self.identity = task_id(self.run)
        self.manifest = {'endpoint': '/not-used', 'recovery_directory': str(self.root/'grants'),
                         'tasks': [{'id': self.identity, 'run': str(self.run)}]}
        (self.root/'grants').mkdir(mode=0o700)
        self.scratch = self.run/'private/engine/recovery-scratch'; self.scratch.mkdir(mode=0o700)
        pose = np.array([.25], dtype=np.float32)
        reader = SimpleNamespace(meta={'case_id': 'fixture', 'source_scene_sha256': 'fixture'},
                                 selected_frames=lambda indices: iter([(0, 1., pose)]))
        self.frame = (reader, 0, 1., pose)
        self.motion = patch('robofrontier.runtime.segments._last_frame', return_value=self.frame); self.motion.start(); self.addCleanup(self.motion.stop)

    def control(self, endpoint, method, params=None):
        if method == 'gateway/capabilities': return {'singleTaskRecovery': 1}
        self.assertEqual(params, {'taskId': self.identity})
        return {'state': 'closed', 'pendingTools': 0, 'inflight': 0, 'recoveryUsed': False, 'threads': ['original-controller']}

    def test_readonly_plan_retains_original_ledger(self):
        before = recovery._ledger(self.store.db)
        events = self.store.db.execute('SELECT count(*) FROM events').fetchone()[0]
        with patch.object(recovery, 'gateway_call', side_effect=self.control):
            plan = recovery.inspect(self.run, self.manifest, ROOT)
        self.assertEqual(plan['threads'], ['original-controller'])
        self.assertEqual(plan['ledger_sha256'], before)
        self.assertEqual(recovery._ledger(self.store.db), before)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM events').fetchone()[0], events)
        # A live seal after a lost task channel is an unexpected stop (run_segments.STOP_REASONS).
        self.assertEqual(recovery.run_segments.stop_reason(self.run, self.store), 'unexpected')

    def test_old_gateway_is_refused_without_preparing_a_segment_or_dispatching(self):
        before = recovery._ledger(self.store.db)
        with patch.object(recovery, 'gateway_call', return_value={'singleTaskRecovery': 0}), \
                patch.object(recovery.subprocess, 'Popen') as start:
            with self.assertRaisesRegex(recovery.RecoveryBlocked, 'lacks single-task'):
                recovery.execute(self.run, self.manifest, ROOT, os.sys.executable, self.scratch, allocation_end=time.time()+100000)
        start.assert_not_called()
        self.assertEqual(self.store.get('lifecycle'), 'interrupted')
        self.assertEqual(self.store.get('segment', 0), 0)
        self.assertEqual(recovery._ledger(self.store.db), before)
        self.assertFalse((self.run/'private/inputs/segments').exists())

    def test_unsettled_call_or_stale_grasp_blocks_before_gateway_admission(self):
        self.store.begin_call('uncertain-original', 'Controller', 'move', {'robot': 'B'})
        with patch.object(recovery, 'gateway_call') as control:
            with self.assertRaisesRegex(recovery.RecoveryBlocked, 'unsettled'):
                recovery.inspect(self.run, self.manifest, ROOT)
            control.assert_not_called()
        self.store.finish_call('uncertain-original', {'execution_status': 'failed'})
        self.store.put('arm_holds', {'B': {'sim_s': -100.}})
        with self.assertRaisesRegex(recovery.RecoveryBlocked, 'too old'):
            recovery.inspect(self.run, self.manifest, ROOT)

    def test_preparation_retains_completed_receipts_and_launches_only_the_original_host(self):
        before = recovery._ledger(self.store.db)
        store = self.store
        class Host:
            pid = 99999998
            def wait(self):
                store.put('segments', [{'index': 0}, {'index': 1}]); store.put('lifecycle', 'ended')
                return 0
        with patch.object(recovery, 'gateway_call', side_effect=self.control), \
                patch.object(recovery, 'validate_physical_restore', return_value={'verified': True, 'physics_steps': 0}), \
                patch.object(recovery.subprocess, 'Popen', return_value=Host()) as start:
            result = recovery.execute(self.run, self.manifest, ROOT, Path(os.sys.executable), self.scratch, allocation_end=time.time()+100000)
        self.assertEqual(result['phase'], 'closed')
        self.assertEqual(recovery._ledger(self.store.db), before)
        self.assertEqual(self.store.get('segment'), 1)
        self.assertEqual(self.store.get('pending_segment')['interrupted'], {})
        arguments, options = start.call_args
        self.assertEqual(arguments[0][1], str(ROOT/'robofrontier/engines/codex/codex_policy_host.js'))
        self.assertEqual(arguments[0][2], str(self.run))
        self.assertEqual(options['env']['ROBOFRONTIER_CODEX_TASK'], self.identity)
        self.assertIn('ROBOFRONTIER_CODEX_RECOVERY_NONCE', options['env'])
        self.assertLess(self.store.get('pending_segment')['previous_ended_at'], result['at'])


class PhysicalRestoreTests(unittest.TestCase):
    def test_private_mosaic_clone_restores_pose_and_force_hold_without_stepping(self):
        from robofrontier.runtime.pipeline import World
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve(); run = prepared(root, 'codex', case='mosaic-a04-6x12-d1').resolve()
            task = json.loads((run/'private/inputs/task.json').read_text()); world = World(run, task)
            pose = world.data.qpos.copy(); arm = sorted(world.arms)[0]
            width = world.arms[arm].observe()['gripper_width_m']
            evidence = {'sim_s': 1., 'observed_width_m': width, 'force_n': 20., 'target_width_m': width,
                        'epsilon_inner_m': .005, 'epsilon_outer_m': .005}
            store = RuntimeStore(run/'private/state/runtime.sqlite')
            try: store.put('arm_holds', {arm: evidence})
            finally: store.close()
            snapshot = {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in run.rglob('*') if p.is_file() and p.name not in ('runtime.sqlite-wal', 'runtime.sqlite-shm')}
            frame = (SimpleNamespace(meta={}), 0, 1., pose)
            with patch('robofrontier.runtime.segments._last_frame', return_value=frame):
                result = recovery.validate_physical_restore(run, ROOT, os.sys.executable, root,
                                                           {'segment': 1, 'sim_s': 1.})
            self.assertTrue(result['verified']); self.assertEqual(result['physics_steps'], 0)
            self.assertEqual(result['held_arms'], [arm])
            after = {str(p.relative_to(run)): hashlib.sha256(p.read_bytes()).hexdigest()
                     for p in run.rglob('*') if p.is_file() and p.name not in ('runtime.sqlite-wal', 'runtime.sqlite-shm')}
            self.assertEqual(after, snapshot)


class SupervisorHandbackTests(unittest.TestCase):
    def test_batch_waits_for_the_recovered_world_even_if_its_recovery_supervisor_was_lost(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary).resolve()/'run'
            control = run/'private/state/control'; control.mkdir(parents=True)
            (control/'recovery.lock').touch()
            write_json(control/'recovery.json', {'phase': 'host_started', 'pid': 99999999})
            jobs = [{'run_directory': str(run), 'status': 'needs_review', 'host_exit_code': 1}]
            waits = []
            with patch.object(recovery.run_segments, 'owner_released', side_effect=[False, True]):
                common_recovery.wait_for_recoveries(jobs, sleep=waits.append)
            self.assertEqual(waits, [1])
            self.assertEqual(jobs[0]['status'], 'needs_review')

    def test_a_completed_recovery_hands_back_to_the_original_batch_collector(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary).resolve()/'run'
            control = run/'private/state/control'; control.mkdir(parents=True)
            (control/'recovery.lock').touch()
            write_json(control/'recovery.json', {'phase': 'closed', 'host_exit_code': 0})
            jobs = [{'run_directory': str(run), 'status': 'needs_review'}]
            with patch.object(recovery.run_segments, 'owner_released', return_value=True):
                common_recovery.wait_for_recoveries(jobs)
            self.assertEqual(jobs[0]['status'], 'closed')
            self.assertEqual(jobs[0]['recovery']['host_exit_code'], 0)
            self.assertEqual(jobs[0]['host_exit_code'], 0)


if __name__ == '__main__': unittest.main()
