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

    def test_the_score_records_how_fast_the_world_ran(self):
        import json, tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'private/outputs/cpu-performance.jsonl'; log.parent.mkdir(parents=True)
            # 20 minutes at real time, then 10 minutes at half speed.
            rows = [{'at': t, 'world_steps': int(t/.02)} for t in range(0, 1201, 5)]
            rows += [{'at': 1200+t, 'world_steps': int(1200/.02+t/.04)} for t in range(5, 601, 5)]
            log.write_text(''.join(json.dumps(r)+'\n' for r in rows))
            service = RuntimeService.__new__(RuntimeService); service.world = World(); service.directory = Path(folder)
            service.policy_budget = SimpleNamespace(active=20., stalls=2)
            speed = service.settled_evaluation()['speed']
        self.assertEqual((speed['sim_s'], speed['active_s'], speed['speed_ratio'], speed['active_time_stalls']), (10., 20., .5, 2))
        self.assertAlmostEqual(speed['slowest_10min_speed_ratio'], .5, places=2)


if __name__ == '__main__':
    unittest.main()
