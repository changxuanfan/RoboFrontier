import unittest

from roboteam.analysis.metrics import grasps


class GraspTests(unittest.TestCase):
    def test_counts_grasp_mode_actions_and_width_failures_only(self):
        width = 'Grasp stopped outside expected object-width tolerance'
        actions = [
            {'type': 'gripper', 'mode': 'grasp', 'status': 'completed', 'reason': None},
            {'type': 'gripper', 'mode': 'grasp', 'status': 'failed', 'reason': width},
            {'type': 'gripper', 'mode': 'grasp', 'status': 'failed', 'reason': 'stopped_by_agent'},
            {'type': 'gripper', 'mode': None, 'status': 'failed', 'reason': 'Requested opening not reached'},
            {'type': 'move', 'mode': None, 'status': 'failed', 'reason': width},
        ]
        self.assertEqual(grasps(actions), {'grasps': 3, 'failed': 1})
        self.assertEqual(grasps([]), {'grasps': 0, 'failed': 0})


if __name__ == '__main__':
    unittest.main()
