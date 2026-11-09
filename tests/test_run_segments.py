"""When a run may continue in a new segment, and how downtime enters the deadline."""
import fcntl
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier import run_segments
from robofrontier.run_layout import path as run_path
from robofrontier.run_segments import MIN_REMAINING_S, deadline, process_summary, retry_eligibility
from robofrontier.runtime_store import RuntimeStore
from test_engine_parity import prepared


class EligibilityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run = prepared(Path(self.tmp.name).resolve(), 'codex').resolve()
        self.store = RuntimeStore(self.run / 'private/state/runtime.sqlite'); self.addCleanup(self.store.close)
        self.store.put('lifecycle', 'running'); self.store.put('start_at', time.time() - 30)

    def reason(self): return retry_eligibility(self.run, self.store)[1]

    def test_each_normal_or_unsafe_end_blocks_a_retry(self):
        self.assertEqual(self.reason(), 'no recorded motion frame')
        self.store.put('segment', 1); self.assertEqual(self.reason(), 'already continued once'); self.store.put('segment', 0)
        for lifecycle in ('prepared', 'ended', 'paused'):
            self.store.put('lifecycle', lifecycle)
            self.assertIn('ended normally or never started', self.reason())
        self.store.put('lifecycle', 'running')
        run_path(self.run, 'stop').parent.mkdir(parents=True, exist_ok=True); run_path(self.run, 'stop').write_text('x')
        self.assertEqual(self.reason(), 'stop requested'); run_path(self.run, 'stop').unlink()
        self.store.event('POLICY_WALL_LIMIT', 'Meta', {}); self.assertTrue(self.reason().startswith('run reached a normal end'))

    def test_a_finish_or_a_budget_close_never_continues(self):
        # Two Haiku runs were once continued after their wall limit; any normal-end record blocks it.
        for kind in ('TEAM_FINISH_PROPOSED', 'POLICY_BUDGET_CLOSED'):
            with self.subTest(kind=kind):
                self.store.db.execute("DELETE FROM events WHERE kind IN ('TEAM_FINISH_PROPOSED','POLICY_BUDGET_CLOSED')")
                self.store.event(kind, 'Meta', {})
                self.assertIn(kind, self.reason())

    def test_integrity_abort_and_changed_inputs_block_a_retry(self):
        self.store.put('integrity_valid', False); self.assertEqual(self.reason(), 'integrity abort')
        self.store.put('integrity_valid', True)
        (self.run / 'public/inputs/rules.md').write_text('changed')
        self.assertTrue(self.reason().startswith('frozen inputs changed'))

    def test_a_live_world_or_too_little_time_blocks_a_retry(self):
        with run_path(self.run, 'world_lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            self.assertEqual(self.reason(), 'a process still owns the physical world')
        limit = json.loads((self.run / 'private/inputs/task.json').read_text())['run_protocol']['total_wall_limit_s']
        # A new run counts active time (test_active_time covers the wall clock of frozen runs).
        self.store.put('start_at', time.time() - limit * 2)
        self.assertEqual(self.reason(), 'no recorded motion frame')
        self.store.put('active_s', limit - MIN_REMAINING_S / 2)
        self.assertIn('of the wall limit left', self.reason())
        self.store.put('active_s', limit - MIN_REMAINING_S * 2)
        self.assertEqual(self.reason(), 'no recorded motion frame')

    def test_only_a_seal_of_a_live_world_counts_as_a_normal_end(self):
        report = str(self.run / 'private/outputs/seal.json')
        # Under a symlinked root (macOS /var -> /private/var) the recorded path may be unresolved.
        if report.startswith('/private/var/') and Path('/var').is_symlink(): report = report[len('/private'):]
        self.store.event('RUN_SEALED', 'Meta', {'report_ref': report, 'owner_was_live': False})
        self.assertEqual(self.reason(), 'no recorded motion frame')
        self.store.event('RUN_SEALED', 'Meta', {'report_ref': report, 'owner_was_live': True})
        self.assertEqual(self.reason(), 'run was sealed with its world alive')

    def test_process_statistics_combine_the_last_snapshot_of_each_segment(self):
        out = self.run / 'private/outputs'; header = {'schema': 'x', 'format': 'events-1s'}
        snap = lambda t, samples, contacts, peak, violations: {'type': 'snapshot', 'sim_time_s': t, 'result': {
            'samples': samples, 'inter_robot_contacts': contacts, 'peak_concurrent_actions': peak, 'violations': violations,
            'process_compliant': not violations, 'sim_time_s': t, 'robot_contact_episodes': {'inter_robot_episodes': contacts}}}
        rows = [header, snap(1, 50, 0, 1, []), snap(2, 100, 1, 2, []), header, snap(3, 40, 0, 1, [])]
        (out / 'suite-process.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        self.assertEqual(process_summary(self.run)['total']['samples'], 140)
        (out / 'evaluation.json').write_text(json.dumps({**snap(9, 300, 2, 3, ['late'])['result']}))
        summary = process_summary(self.run)
        self.assertEqual([s['samples'] for s in summary['segments']], [100, 300])
        total = summary['total']
        self.assertEqual((total['samples'], total['inter_robot_contacts'], total['peak_concurrent_actions']), (400, 3, 3))
        self.assertEqual(total['violations'], ['late']); self.assertFalse(total['process_compliant'])
        self.assertEqual(total['robot_contact_episodes']['inter_robot_episodes'], 3)
        (out / 'suite-process.jsonl').write_text(json.dumps(header) + '\n' + json.dumps(snap(1, 5, 0, 1, [])) + '\n')
        self.assertIsNone(process_summary(self.run))

    def test_dial_record_continues_over_segments_up_to_each_restore_frame(self):
        out = self.run / 'private/outputs'; header = {'schema': 'x', 'format': 'events-1s'}
        row = lambda t, trials, best, **extra: {'type': 'snapshot', 'sim_time_s': t, 'result': {
            'valid_trials': trials, 'display': best, 'feedback_mode': 'best_so_far', 'solved': False, **extra}}
        # Segment 0 reached BEST 6 after 65 trials; trial 66 came after the restore frame (t=40).
        # Segment 1 started before carry-over existed and counted from zero.
        rows = [header, row(10, 64, 5), row(30, 65, 6, input_ready=True), row(45, 66, 6),
                header, row(40, 0, 0), row(50, 2, 3)]
        (out / 'suite-process.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        self.assertEqual(run_segments.dial_record(self.run, 35.), {'valid_trials': 65, 'best': 6, 'solved': False,
                                                                   'input_ready': True, 'sim_time_s': 30})
        record = run_segments.dial_record(self.run)
        self.assertEqual((record['valid_trials'], record['best']), (67, 6))
        # A carried segment reports cumulative counts; only its own trials are added.
        rows[-2:] = [row(40, 65, 6, carried_valid_trials=65), row(50, 67, 7, carried_valid_trials=65)]
        (out / 'suite-process.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        self.assertEqual((run_segments.dial_record(self.run)['valid_trials'], run_segments.dial_record(self.run)['best']), (67, 7))
        self.assertEqual(process_summary(self.run)['total']['dial']['valid_trials'], 67)
        (out / 'suite-process.jsonl').write_text(json.dumps(header) + '\n' + json.dumps({'type': 'snapshot', 'sim_time_s': 1, 'result': {'samples': 1}}) + '\n')
        self.assertIsNone(run_segments.dial_record(self.run))

    def test_deadline_excludes_downtime(self):
        self.store.put('start_at', 1000.); self.store.put('downtime_s', 25.)
        self.assertEqual(deadline(self.store, 600), 1625.)

    def test_runs_without_segment_folders_never_continue(self):
        manifest = self.run / 'private/inputs/manifest.json'; value = json.loads(manifest.read_text())
        for key in ('segment_inputs', 'segment_outputs'): value['layout_paths'].pop(key)
        manifest.write_text(json.dumps(value))
        self.assertEqual(self.reason(), 'run layout has no segments')



class FakeReader:
    meta = {'case_id': 'transport-a04-d1', 'source_scene_sha256': 'scene'}
    def __init__(self, nq): self.nq = nq
    def selected_frames(self, indices):
        for i in indices: yield i, 12.5, np.arange(self.nq, dtype=float)


class PreparationTests(unittest.TestCase):
    """prepare_retry with a recorded last frame; the world itself is not started."""
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.run = prepared(Path(self.tmp.name).resolve(), 'codex').resolve()
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite'); self.addCleanup(self.store.close)
        self.store.put('lifecycle', 'running'); self.store.put('start_at', time.time()-30)
        self.store.put('physics_state', 'running')
        frame = (FakeReader(9), 41, 12.5, np.arange(9, dtype=float))
        patcher = patch.object(run_segments, '_last_frame', lambda run, segment: frame)
        patcher.start(); self.addCleanup(patcher.stop)
        self.robot = sorted(json.loads((self.run/'private/inputs/task.json').read_text())['arms'])[0]

    def running_action(self, call_id):
        self.store.begin_call(call_id, 'Controller', 'move', {'robot': self.robot})
        self.store.start_action(call_id, 'Controller', 'move', {'robot': self.robot}, 3.0)

    def test_an_interrupted_call_answers_its_original_id_with_a_definite_failure(self):
        self.running_action('Controller-call_1')
        note = run_segments.prepare_retry(self.run, self.store, 'host exit code 1')
        self.assertEqual((note['segment'], self.store.get('lifecycle')), (1, 'resuming'))
        result = self.store.call('Controller-call_1')['result']
        self.assertEqual((result['execution_status'], result['interrupted_by_segment']), ('failed', True))
        self.assertEqual(result['original_observed']['action_status'], 'running')
        self.assertEqual(result['reconciliation']['sim_time_s'], 12.5)
        self.assertEqual(self.store.get('pending_segment')['interrupted'], {'Controller': ['Controller-call_1']})
        self.assertEqual(retry_eligibility(self.run, self.store), (False, 'already continued once'))

    def test_a_preparation_stopped_part_way_completes_in_the_same_segment(self):
        self.running_action('Controller-call_1')
        real = run_segments.write_json
        def fail_once(path, value):
            if Path(path).name == 'restore-pose.json' and not getattr(fail_once, 'done', False):
                fail_once.done = True; raise OSError('disk full')
            return real(path, value)
        with patch.object(run_segments, 'write_json', fail_once):
            with self.assertRaises(OSError): run_segments.prepare_retry(self.run, self.store, 'host exit code 1')
        # The interruption is recorded once; the segment is not yet used.
        self.assertEqual((self.store.get('segment', 0), self.store.get('segment_journal')['segment']), (0, 1))
        self.assertTrue(retry_eligibility(self.run, self.store)[0])
        run_segments.prepare_retry(self.run, self.store, 'host exit code 1')
        self.assertEqual((self.store.get('segment'), self.store.get('segment_journal')), (1, None))
        self.assertEqual(self.store.get('pending_segment')['interrupted'], {'Controller': ['Controller-call_1']})
        self.assertEqual(len(self.store.get('segments')), 1)

    def test_the_restore_record_carries_the_dial_record_at_the_restore_frame(self):
        rows = [{'schema': 'x'}, {'type': 'event', 'sim_time_s': 12.0, 'result': {
                    'valid_trials': 65, 'display': 6, 'feedback_mode': 'best_so_far', 'solved': False, 'input_ready': True}},
                {'type': 'event', 'sim_time_s': 13.0, 'result': {
                    'valid_trials': 66, 'display': 7, 'feedback_mode': 'best_so_far', 'solved': False}}]
        (self.run/'private/outputs/suite-process.jsonl').write_text(''.join(json.dumps(r) + '\n' for r in rows))
        note = run_segments.prepare_retry(self.run, self.store, 'host exit code 1')
        self.assertEqual(note['evaluator'], {'valid_trials': 65, 'best': 6, 'solved': False, 'input_ready': True, 'sim_time_s': 12.0})
        self.assertEqual(run_segments.current_restore(self.run)[0]['evaluator']['valid_trials'], 65)
        self.assertEqual(run_segments.verify_inputs(self.run), [])

    def test_other_families_keep_their_restore_record(self):
        self.assertNotIn('evaluator', run_segments.prepare_retry(self.run, self.store, 'host exit code 1'))

    def test_a_delegation_still_being_created_fails_and_returns_its_arms(self):
        child = {'actor': 'Delegate_x', 'robots': [self.robot], 'goal': 'g', 'done_when': 'd', 'thread_id': None,
                 'verified': False, 'status': 'creating', 'start_status': 'pending'}
        self.store.put('delegations', {'d1': {'id': 'd1', 'parent': 'Controller', 'status': 'creating', 'claimed_by': 'meta-1',
                                              'children': [child]}})
        info = dict(self.store.agent('Controller'), kind='delegate', delegation_id='d1', delegation_state='creating')
        self.store.db.execute('INSERT INTO agents VALUES (?,?)', ('Delegate_x', json.dumps(info)))
        self.store.put('robot_owners', {**self.store.get('robot_owners', {}), self.robot: 'Delegate_x'})
        run_segments.prepare_retry(self.run, self.store, 'host exit code 1')
        batch = self.store.get('delegations')['d1']
        self.assertEqual((batch['status'], batch['outcome']), ('finished', 'failed'))
        self.assertEqual(self.store.get('robot_owners')[self.robot], 'Controller')
        self.assertEqual(self.store.agent('Delegate_x')['delegation_state'], 'finished')
        self.assertEqual(self.store.get('pending_segment')['interrupted'], {})


if __name__ == '__main__': unittest.main()
