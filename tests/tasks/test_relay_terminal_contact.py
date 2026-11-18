"""Every released Relay task declares the same goal-contact and handover contract."""

import json
import unittest

from relay_contract import is_current
from roboteam.tasks.public import public_task
from roboteam.tasks.public import validate as validate_task
from roboteam.tasks.task_types import RELEASE, ROOT, read


class RelayTerminalContactTests(unittest.TestCase):
    def test_all_nine_public_tasks_declare_the_same_user_contact_contract(self):
        relay = read(ROOT / RELEASE)['families']['relay']['policy']
        self.assertEqual(len(relay), 9)
        for case in relay:
            task = json.loads((ROOT / case['directory'] / 'task.json').read_text())
            validate_task(task)
            self.assertTrue(is_current(task))
            policy = public_task(task)['completion']
            self.assertTrue(policy['allow_goal_payload_contact'])
            self.assertTrue(policy['arbitrary_goal_placement'])
            self.assertTrue(policy['required_airborne_handover'])


if __name__ == '__main__':
    unittest.main()
