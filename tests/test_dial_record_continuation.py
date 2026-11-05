"""A continued segment's Dial evaluator takes over trials and BEST (docs/running/run-segments.md)."""
import math
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier.suite.dial_feedback import DialFeedback
from robofrontier.suite.evaluate import CountFeedback, Monitor


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


if __name__ == '__main__': unittest.main()
