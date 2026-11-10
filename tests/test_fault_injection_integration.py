"""An injected unsettled stop is recovered locally in a real world while other arms work.

The run's frozen fault makes the first move of one arm time out and stay unsettled for a
few seconds after stopping. The live action must report stopping with diagnostics, the
world keep running, `recover_action` decline until the arm is stable and then confirm
the stop with the action failed; another arm moves normally meanwhile. No model calls.
"""
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

from robofrontier.runtime.fault_injection import arm as arm_fault
from robofrontier.runtime.pipeline_client import client_call
from robofrontier.runtime.store import RuntimeStore
from test_engine_parity import prepared
from test_run_segments_integration import ROOT, owner_command, wait_until


class FaultInjectionTests(unittest.TestCase):
    def test_injected_unsettled_stop_is_recovered_with_the_original_id(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            run = prepared(Path(tmp).resolve(), 'codex').resolve()
            task = json.loads((run / 'private/inputs/task.json').read_text())
            first, second = sorted(task['arms'])[:2]
            spec = arm_fault(run, first, 1, timeout_sim_s=1., hold_unsettled_sim_s=4.)
            self.assertEqual(json.loads((run / 'private/inputs/manifest.json').read_text())['fault_injection'], spec)
            meta, controller = (run / 'private/state/connections' / n for n in ('Meta.json', 'Controller.json'))
            log = (run / 'owner-test.log').open('a'); self.addCleanup(log.close)
            owner = subprocess.Popen(owner_command(run), cwd=ROOT, stdout=log, stderr=log)
            try:
                def attached():
                    store = RuntimeStore(run / 'private/state/runtime.sqlite')
                    try: return json.loads(meta.read_text()).get('url') and store.get('execution_owner_attached')
                    finally: store.close()
                wait_until(attached, message='world')
                client_call(meta, 'bind', {'actor': 'Controller', 'thread_id': 'thread-1'}, 'bind-1')
                client_call(meta, 'start', {}, 'start-1')
                faulty = client_call(controller, 'move', {'robot': first, 'delta_m': [0, 0, .05], 'speed_m_s': .01,
                                                          'wait': True, 'cameras': []}, 'move-fault')
                self.assertEqual(faulty['execution_status'], 'running', faulty)
                self.assertEqual(faulty['execution']['phase'], 'stopping')
                self.assertTrue(faulty['execution']['local_recovery'])
                self.assertIn('unmet_conditions',faulty['stop_diagnostics'])
                checked=client_call(controller, 'job', {'call_id': 'move-fault'}, 'inspect-stop')
                self.assertEqual(checked['execution']['phase'],'stopping')
                self.assertIn('actual_joint_velocity_rad_s',checked['stop_diagnostics'])
                pending = client_call(controller, 'recover_action', {'call_id': 'move-fault'}, 'recover-1')
                self.assertFalse(pending['recovered'])
                # The world keeps running: the other arm acts while the first is unresolved.
                other = client_call(controller, 'move', {'robot': second, 'delta_m': [0, 0, .02], 'speed_m_s': .05,
                                                         'wait': True, 'cameras': []}, 'move-other')
                self.assertEqual(other['execution']['status'], 'completed')
                def recovered():
                    answer = client_call(controller, 'recover_action', {'call_id': 'move-fault'},
                                         'recover-%d' % time.monotonic_ns())
                    return answer if answer.get('recovered') else None
                done = wait_until(recovered, timeout=60, message='the stop to be confirmed')
                self.assertEqual(done['execution']['status'], 'failed')
                again = client_call(controller, 'move', {'robot': first, 'delta_m': [0, 0, .01], 'speed_m_s': .05,
                                                         'wait': True, 'cameras': []}, 'move-after')
                self.assertEqual(again['execution']['status'], 'completed')
            finally:
                owner.kill(); owner.wait()
            store = RuntimeStore(run / 'private/state/runtime.sqlite')
            try:
                kinds = [e['kind'] for e in store.events(500)]
                self.assertIn('ENGINEERING_FAULT_INJECTED', kinds)
                self.assertEqual(store.get('lifecycle'), 'running')
            finally: store.close()

    def test_a_fault_is_set_only_before_the_run_and_must_stay_frozen(self):
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            run = prepared(Path(tmp).resolve(), 'codex').resolve()
            arm = sorted(json.loads((run / 'private/inputs/task.json').read_text())['arms'])[0]
            with self.assertRaises(ValueError): arm_fault(run, 'Z', 1)
            self.assertEqual(arm_fault(run, '*', 2)['robot'], '*')
            with self.assertRaises(FileExistsError): arm_fault(run, arm, 3)
            from robofrontier.runtime.pipeline import World
            from types import SimpleNamespace
            world = SimpleNamespace(directory=run, arms={a: SimpleNamespace() for a in ('A', 'B')})
            inject = lambda robot, ident: World.inject_fault(world, robot, ident, 'move')
            self.assertIsNone(inject('A', 'first'))
            self.assertEqual(inject('B', 'second')['arm'], 'B')
            self.assertIsNone(inject('A', 'third'))
            path = run / 'private/inputs/fault-injection.json'; path.write_text(path.read_text().replace('"move"', '"gripper"'))
            from robofrontier.runtime.fault_injection import load
            with self.assertRaises(ValueError): load(run)


if __name__ == '__main__': unittest.main()
