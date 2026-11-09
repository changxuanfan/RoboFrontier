"""A continued segment's Dial evaluator takes over trials and BEST (docs/running/run-segments.md)."""
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier.suite.dial_feedback import DialFeedback
from robofrontier.suite.evaluate import CountFeedback, Monitor, SupportQualification


def held(symbols, step=60.):
    return np.radians([s*step for s in symbols])


class ContinuationTests(unittest.TestCase):
    def monitor(self, game, angles, record):
        stub = SimpleNamespace(w=SimpleNamespace(directory='run'), d=SimpleNamespace(qpos=np.array(angles), time=40.),
                               qids=list(range(len(angles))), game=game, carried_trials=0)
        with patch('robofrontier.run_segments.current_restore', lambda run: ({'evaluator': record}, None)):
            Monitor.continue_dial_record(stub)
        return stub

    def play(self, game, t, angles, seconds=.4):
        for k in range(int(seconds/.02)+1):
            game.update(t+k*.02, angles, [0.]*len(angles), True)
        return game

    def test_best_and_trials_continue_and_a_held_input_is_not_counted_again(self):
        secret = (1, 2, 3, 4, 5, 1, 2, 3)
        guess = (1, 2, 3, 4, 5, 5, 5, 5)
        game = DialFeedback(secret)
        stub = self.monitor(game, held(guess), {'valid_trials': 65, 'best': 6, 'solved': False, 'input_ready': True})
        self.assertEqual((game.queries, game.best, game.display, stub.carried_trials), (65, 6, 6, 65))
        self.play(game, 40., held(guess))
        self.assertEqual((game.queries, game.display, game.ready), (65, 6, True))
        self.play(game, 41., held((1, 2, 3, 4, 5, 1, 2, 5)))
        self.assertEqual((game.queries, game.best), (66, 7))
        self.assertEqual(game.trials[-1]['index'], 66)

    def test_an_input_not_held_at_the_restore_frame_counts_as_a_new_trial(self):
        game = DialFeedback((1, 1, 1, 1))
        self.monitor(game, held((2, 2, 2, 2)), {'valid_trials': 3, 'best': 2, 'solved': False, 'input_ready': False})
        self.play(game, 40., held((2, 2, 2, 2)))
        self.assertEqual((game.queries, game.display), (4, 2))

    def test_without_a_carried_record_the_evaluator_starts_empty(self):
        game = DialFeedback((1, 1, 1, 1))
        stub = SimpleNamespace(w=SimpleNamespace(directory='run'), game=game, carried_trials=0)
        with patch('robofrontier.run_segments.current_restore', lambda run: None):
            Monitor.continue_dial_record(stub)
        self.assertEqual((game.queries, game.best, stub.carried_trials), (0, 0, 0))

    def test_count_feedback_continues_its_trials(self):
        game = CountFeedback((1, 2, 3, 1))
        self.monitor(game, held((1, 2, 3, 3), 90.), {'valid_trials': 5, 'best': None, 'solved': False, 'input_ready': True})
        self.play(game, 40., held((1, 2, 3, 3), 90.))
        self.assertEqual(game.queries, 5)
        self.play(game, 41., held((1, 2, 3, 2), 90.))
        self.assertEqual(game.queries, 6)


class SampledContinuationTests(unittest.TestCase):
    """The path a continued world really takes: fresh Monitor state, then Monitor.sample_dial.

    R holds the red rotor and B the blue stem of one Level 2 BEST dial, with symbol 2 set.
    """
    def monitor(self, record, feedback=True, red=True):
        mon = Monitor.__new__(Monitor)
        spec = {'mode': 'best_so_far', 'symbol_count': 5, 'require_red_grasp': True, 'display_digits': 1}
        mon.task = {'level': 2, 'table_height_m': .4, 'dials': [{'id': 'd0'}],
                    'mechanism': {'feedback': spec} if feedback else {},
                    'run_protocol': {'evaluation_semantics': 'terminal_outcome_v2'}}
        mon.dials = mon.task['dials']; mon.robots = ['R', 'B']
        mon.m = SimpleNamespace(ngeom=6, geom=lambda name: SimpleNamespace(id=0), geom_rgba=np.zeros((6, 4)))
        step = 60. if feedback else 90.
        mon.d = SimpleNamespace(time=40., qpos=np.radians([2*step]), qvel=np.zeros(1))
        mon.w = SimpleNamespace(directory='run', arms={'R': SimpleNamespace(job=None, job_op=None, dofs=[0], grasp_force=30.),
                                                       'B': SimpleNamespace(job=None, job_op=None, dofs=[0], grasp_force=70.)})
        mon.geom_owner = np.array([-1, 0, 1, -1, -1, -1]); mon.red = {0: 0}; mon.blue = {3: 0}; mon.module_geoms = [[5]]
        mon.qids = [0]; mon.dofs = [0]
        self.red = red
        mon.bilateral = lambda geoms, positive_force=False: {'B'} if 3 in geoms else ({'R'} if self.red else set())
        mon.bottom = lambda geoms: .5
        mon.contacts = lambda: ((np.array([[1, 0], [2, 3]]), np.array([-1e-4, -1e-4])) if self.red
                                else (np.array([[2, 3]]), np.array([-1e-4])))
        mon.blue_qualification = [SupportQualification()]; mon.previous_red = set(); mon.unsupported_since = {}
        mon.holding_s = 0.; mon.minimum_clearance = np.full(1, math.inf); mon.violations = []; mon.carried_trials = 0
        mon.game = DialFeedback((1,)) if feedback else CountFeedback((1,))
        with patch('robofrontier.run_segments.current_restore', lambda run: ({'evaluator': record}, None)):
            mon.continue_dial_record()
        return mon

    def play(self, mon, seconds, symbol=None):
        if symbol is not None: mon.d.qpos = np.radians([symbol*(60. if mon.task['mechanism'] else 90.)])
        with patch('robofrontier.suite.dial_feedback.paint_display', lambda *args, **kwargs: None):
            for _ in range(int(round(seconds/.02))):
                mon.sample_dial(.02); mon.d.time += .02
        return mon.result_cache

    def test_an_input_and_red_grasp_held_at_the_restore_frame_stay_the_same_trial(self):
        mon = self.monitor({'valid_trials': 10, 'best': 0, 'solved': False, 'input_ready': True, 'support_ready': [True]})
        result = self.play(mon, 1.2)
        self.assertEqual((result['valid_trials'], result['carried_valid_trials']), (10, 10))
        self.assertEqual(mon.game.trials, [])
        self.assertEqual(mon.violations, [])
        self.assertTrue(result['input_ready'])

    def test_a_restore_record_without_support_flags_trusts_the_ready_input(self):
        mon = self.monitor({'valid_trials': 10, 'best': 0, 'solved': False, 'input_ready': True})
        self.assertEqual(self.play(mon, 1.2)['valid_trials'], 10)

    def test_a_new_input_after_the_restore_frame_is_one_new_trial(self):
        mon = self.monitor({'valid_trials': 10, 'best': 0, 'solved': False, 'input_ready': True, 'support_ready': [True]})
        self.play(mon, .4)
        self.assertEqual(self.play(mon, 1.2, symbol=3)['valid_trials'], 11)
        self.assertEqual(mon.violations, [])

    def test_a_red_grasp_made_after_the_restore_frame_without_support_is_still_premature(self):
        mon = self.monitor({'valid_trials': 10, 'best': 0, 'solved': False, 'input_ready': False, 'support_ready': [False]}, red=False)
        self.play(mon, .1)
        self.red = True
        self.play(mon, .1)
        self.assertEqual([v['kind'] for v in mon.violations], ['premature_red_contact'])

    def test_count_feedback_publishes_its_readiness_so_a_held_input_carries(self):
        mon = self.monitor({'valid_trials': 4, 'best': None, 'solved': False, 'input_ready': True, 'support_ready': [True]}, feedback=False)
        result = self.play(mon, 1.2)
        self.assertEqual(result['valid_trials'], 4)
        self.assertTrue(result['input_ready'])


class ProcessLogTests(unittest.TestCase):
    def test_an_unknown_log_format_leaves_an_existing_log_untouched(self):
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder)/'suite-process.jsonl'; log.write_text('kept\n')
            with self.assertRaises(ValueError): Monitor(None, log_path=log, log_format='bogus')
            self.assertEqual(log.read_text(), 'kept\n')


if __name__ == '__main__': unittest.main()
