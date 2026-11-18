import unittest

from roboteam.tasks.provenance import environment_logic_manifest


class EnvironmentLogicFingerprintTests(unittest.TestCase):
    def test_the_evaluator_and_the_dial_game_are_fingerprinted(self):
        evaluator, game = 'roboteam/tasks/evaluate.py', 'roboteam/tasks/dial.py'
        before = environment_logic_manifest({evaluator: 'before', game: 'same'})
        after = environment_logic_manifest({evaluator: 'after', game: 'same'})
        self.assertNotEqual(before['sha256'], after['sha256'])
        self.assertEqual(before['schema'], 'roboteam.environment-logic.v2')
        self.assertEqual(before, environment_logic_manifest({evaluator: 'before', 'unrelated.py': 'ignored'}))
        dial = {'family': 'dial'}
        self.assertNotEqual(
            environment_logic_manifest({evaluator: 'x', game: 'a'}, dial)['sha256'],
            environment_logic_manifest({evaluator: 'x', game: 'b'}, dial)['sha256'],
        )


if __name__ == '__main__':
    unittest.main()
