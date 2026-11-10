"""Finish and the budget cutoff score only after the world has run 1.5 s with every arm still."""
import unittest
from types import SimpleNamespace

from robofrontier.runtime.service import SCORING_SETTLE_S, RuntimeService


class World:
    def __init__(self):
        self.time = 10.; self.stops = []; self.evaluated_at = None
        self.arms = {'A': SimpleNamespace(job='moving'), 'B': SimpleNamespace(job=None)}

    def request_stop(self, robot, call_id): self.stops.append((robot, call_id))
    def step(self): self.time += .02
    def evaluate(self): self.evaluated_at = self.time; return {'task_success': True}


class SettledScoringTests(unittest.TestCase):
    def test_moving_arms_stop_and_the_score_waits_for_the_settle(self):
        service = RuntimeService.__new__(RuntimeService); service.world = World()
        result = service.settled_evaluation()
        self.assertEqual(service.world.stops, [('A', 'moving')])
        self.assertAlmostEqual(service.world.evaluated_at, 10.+SCORING_SETTLE_S)
        self.assertEqual(result, {'task_success': True, 'scored_after_settle_sim_s': SCORING_SETTLE_S})


if __name__ == '__main__':
    unittest.main()
