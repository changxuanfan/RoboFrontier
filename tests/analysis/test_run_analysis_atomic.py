"""Atomic-step rules (version 2) on small synthetic runs; no recorded run data."""

import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from robofrontier.analysis import atomic
from robofrontier.analysis import metrics as M
from robofrontier.analysis.archive import Run

BASE = 1_000_000.0


def act(arm, kind, t0, t1, status='completed', mode=None, target=None, reason=None):
    """One runtime action; wall time is BASE + simulated seconds."""
    return dict(
        actor=arm,
        arm=arm,
        type=kind,
        status=status,
        reason=reason,
        s=BASE + t0,
        e=BASE + t1,
        ss=t0,
        es=t1,
        target=target,
        mode=mode,
        width=None,
        batch=False,
    )


def record(family, actions, **suite_kw):
    suite = dict(
        lines=10,
        goals={},
        regress=[],
        lost={},
        handovers={},
        drops=[],
        custody={},
        viol=[],
        last_sim=1000.0,
        done_at=None,
        solved_at=None,
    )
    suite.update(suite_kw)
    return dict(sel=dict(id='synthetic', family=family), actions=actions, suite=suite)


def angle_lines(samples):
    return [
        json.dumps(dict(result=dict(sim_time_s=t, private_angles_deg=list(a)))) for t, a in samples
    ]


class AtomicStepTests(unittest.TestCase):
    def test_transport_counts_handoffs_and_deliveries_but_not_regrasps(self):
        actions = [
            # Arm A fails one grasp, then carries the item from (0, 0) and releases it at (0.5, 0).
            act('A', 'move', 0, 5, target=[0.0, 0.0, 0.8]),
            act('A', 'gripper', 5, 6, status='failed', mode='grasp', reason='grasp missed'),
            act('A', 'gripper', 7, 8, mode='grasp'),
            act('A', 'move', 8, 15, target=[0.5, 0.0, 0.8]),
            act('A', 'gripper', 15, 16),
            # Arm B picks it up there (a handoff), regrasps in place once, then delivers at (1, 0).
            act('B', 'move', 16, 20, target=[0.52, 0.0, 0.8]),
            act('B', 'gripper', 20, 21, mode='grasp'),
            act('B', 'gripper', 22, 23),
            act('B', 'gripper', 24, 25, mode='grasp'),
            act('B', 'move', 25, 30, target=[1.0, 0.0, 0.8]),
            act('B', 'gripper', 30, 31),
        ]
        goal = dict(t=31.0, item='A_item1', pos=[1.0, 0.0, 0.8])
        d = record('transport', actions, goals={'slot_1': goal})
        r = atomic.transport_atomic(d, M.Clock(d))
        self.assertEqual(r['handoffs'], 1)
        self.assertEqual(r['delivered'], 2)  # the in-place regrasp is not a step
        self.assertEqual(r['atomic_failed'], 1)  # A's failed grasp marks A's handoff
        self.assertEqual(r['atomic_total'], 2)

    def test_relay_counts_each_newly_gripping_arm(self):
        actions = [
            act('E', 'move', 0, 1, target=[0, 0, 1]),
            act('A', 'move', 1, 2, target=[0, 0, 1]),
        ]
        handovers = {
            'payload_01': [
                dict(t=10.0, senders=['A', 'H'], receivers=['B', 'I']),  # two arms join
                dict(t=20.0, senders=['B', 'I'], receivers=['B', 'J']),  # one arm joins
                dict(t=30.0, senders=['B', 'J', 'K'], receivers=['B', 'J']),  # release only
            ]
        }
        d = record('relay', actions, handovers=handovers, drops=[[25.0, 'payload_01', 1]])
        r = atomic.relay_atomic(d, M.Clock(d))
        self.assertEqual(r['delivered'], 3)
        self.assertEqual(r['atomic_failed'], 1)  # the drop marks the timber's last step
        self.assertEqual(r['atomic_total'], 3)

    def test_dial_turns_need_a_dwell_and_skip_pass_through_marks(self):
        samples = [(0.0, [0.0]), (1.0, [0.0]), (2.0, [30.0]), (3.0, [60.0]), (4.5, [60.0])]
        samples += [(5.0, [119.0]), (5.3, [150.0]), (6.0, [180.0]), (8.0, [180.0])]
        self.assertEqual(atomic.dial_turns(angle_lines(samples)), [[3.0, 0], [6.0, 0]])

    def test_dial_failures_go_to_the_next_turn(self):
        actions = [
            act('A', 'move', 0, 1, target=[0, 0, 1]),
            act('A', 'move', 2, 4, status='failed', reason='motion timeout'),
            act('A', 'move', 20, 21, target=[0, 0, 1]),
        ]
        d = record('dial', actions)
        r = atomic.dial_atomic(d, M.Clock(d), [[5.0, 0], [10.0, 1]])
        self.assertEqual((r['atomic_failed'], r['atomic_total'], r['delivered']), (1, 2, 2))

    def test_archive_reads_folders_and_tars(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        out = root / 'data' / 'batch' / 'run1' / 'private' / 'outputs'
        out.mkdir(parents=True)
        (out / 'suite-process.jsonl').write_text('a\nb\n')
        folder = Run('batch/run1', root / 'data', root / 'cache')
        self.assertEqual(list(folder.lines('private/outputs/suite-process.jsonl')), ['a\n', 'b\n'])
        with tarfile.open(root / 'data' / 'pack.tar', 'w') as tar:
            tar.add(root / 'data' / 'batch', arcname='batch')
        packed = Run('pack.tar//batch/run1', root / 'data', root / 'cache')
        self.assertEqual(packed.read('private/outputs/suite-process.jsonl'), b'a\nb\n')
        self.assertEqual(packed.find('suite-process.jsonl'), 'private/outputs/suite-process.jsonl')
        packed.close()


if __name__ == '__main__':
    unittest.main()
