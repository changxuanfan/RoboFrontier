"""Joint target references follow the segment that geometry checks sample."""

import unittest

import numpy as np

from roboteam.tasks.config import load_run_settings
from sim.test_motion_check import robot_fixture


class JointCoordinationTests(unittest.TestCase):
    def test_unequal_joint_travels_share_progress_and_respect_acceleration(self):
        w = robot_fixture()
        w.task = {}
        arm = w.arms['A']
        start = arm.qref.copy()
        delta = np.array([0.5, 0.08, -0.15, -0.12, 0.10, -0.13, 0.35])
        target = start + delta
        command = arm.validate(
            'move',
            dict(joint_rad=target.tolist(), joint_speed_rad_s=0.5, joint_acceleration_rad_s2=2.0),
            load_run_settings(),
            np.full(3, -3.0),
            np.full(3, 3.0),
        )
        arm.start('segment', command, w.time)
        previous = arm.velocity.copy()
        observed = 0
        for _ in range(160):
            w.step()
            progress = (arm.qref - start) / delta
            self.assertLessEqual(max(abs(arm.velocity)), 0.5 + 1e-8)
            self.assertLessEqual(max(abs(arm.velocity - previous)), 2.0 * 0.02 + 1e-8)
            previous = arm.velocity.copy()
            if 0.05 < max(progress) < 0.90:
                self.assertLess(np.ptp(progress), 0.003)
                observed += 1
                self.assertLess(max(abs(w.data.qpos[arm.qids] - arm.qref)), 0.012)
            if max(progress) > 0.98:
                break
        self.assertGreater(observed, 5)


if __name__ == '__main__':
    unittest.main()
