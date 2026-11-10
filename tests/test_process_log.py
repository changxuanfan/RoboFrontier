import io
import json
import unittest

from robofrontier.tasks.evaluate import CONTINUOUS_FIELDS, PROCESS_LOG_FORMATS, Monitor, event_fields


class FakeData:
    time = 0.


def monitor(log_format, results):
    """A Monitor reduced to its process-log state; results are served in order."""
    m = object.__new__(Monitor)
    m.log = io.StringIO(); m.log_format = log_format; m.snapshot_interval = PROCESS_LOG_FORMATS[log_format]
    m.last_event = None; m.logged_trials = 0; m.final_logged = False; m.next_log = -1; m.names = (); m.d = FakeData()
    feed = iter(results); m.result = lambda: next(feed)
    return m


def records(m):
    return [json.loads(line) for line in m.log.getvalue().splitlines()]


class ProcessLogTests(unittest.TestCase):
    def test_event_fields_drop_only_clocks_seconds_and_continuous_measurements(self):
        result = {'sim_time_s': 1.0, 'samples': 5, 'robot_motion_s': 2.0, 'matched_goals': 3,
                  'violations': [{'kind': 'drop', 'sim_time_s': 0.4}],
                  'payloads': {'p1': {'timber_inside_fraction': 0.71, 'terminal_goal_met': True, 'drops': 1}},
                  'dials': [{'index': 0, 'held_s': 0.3, 'private_clearance_m': 0.01, 'ready': True}],
                  'private_angles_deg': [1, 2], 'display': 4}
        # Records inside lists lose the same continuous fields as records inside dicts.
        self.assertEqual(event_fields(result), {'matched_goals': 3, 'violations': [{'kind': 'drop'}],
                                                'payloads': {'p1': {'terminal_goal_met': True, 'drops': 1}},
                                                'dials': [{'index': 0, 'ready': True}], 'display': 4})
        self.assertIn('timber_inside_fraction', CONTINUOUS_FIELDS)

    def test_events_on_change_snapshots_each_second_and_a_final_snapshot(self):
        base = lambda t, goals, moving: {'sim_time_s': t, 'samples': int(t / .02), 'robot_motion_s': moving, 'matched_goals': goals}
        times = [0, .02, .04, .06, .5, 1.0, 1.02, 1.04]
        results = [base(0, 0, 0), base(.02, 0, .01), base(.04, 1, .02), base(.06, 1, .03), base(.5, 1, .2),
                   base(1.0, 1, .3), base(1.02, 2, .31), base(1.04, 2, .32), base(1.04, 2, .32)]
        m = monitor('events-1s', results)
        for t in times: m.log_sample(t)
        m.d.time = 1.04; m.finish()
        kinds = [(r['type'], r['sim_time_s']) for r in records(m)]
        self.assertEqual(kinds, [('snapshot', 0), ('event', .04), ('snapshot', 1.0), ('event', 1.02), ('snapshot', 1.04)])
        self.assertIn('objects', records(m)[0]); self.assertNotIn('objects', records(m)[1])
        m.close()  # the final snapshot is not written twice

    def test_sixty_second_format_leaves_recorded_poses_to_motion(self):
        results = [{'sim_time_s': t, 'samples': 0, 'matched_goals': goals} for t, goals in
                   ((0, 0), (.02, 1), (30, 1), (60, 1), (60, 1))]
        m = monitor('events-60s', results)
        m.motion_recorded = lambda: True
        for t in (0, .02, 30, 60): m.log_sample(t)
        m.d.time = 60; m.finish()
        rows = records(m)
        self.assertEqual([(r['type'], r['sim_time_s']) for r in rows],
                         [('snapshot', 0), ('event', .02), ('snapshot', 60), ('snapshot', 60)])
        self.assertEqual(['objects' in r for r in rows], [False, False, False, True])

    def test_sixty_second_format_keeps_poses_when_nothing_records_motion(self):
        m = monitor('events-60s', [{'sim_time_s': 0, 'samples': 0}])
        m.motion_recorded = lambda: False
        m.log_sample(0)
        self.assertIn('objects', records(m)[0])

    def test_sixty_second_format_records_each_trial_once(self):
        results = [{'sim_time_s': t, 'samples': 0, 'valid_trials': n} for t, n in ((0, 0), (1, 1), (2, 1))]
        m = monitor('events-60s', results)
        m.motion_recorded = lambda: True
        m.game = type('Game', (), {'trials': []})()
        m.log_sample(0)
        m.game.trials.append({'index': 1, 'input_symbols': [1, 2], 'correct_count': 1})
        m.log_sample(1); m.log_sample(2)
        rows = records(m)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[1]['trials'], [{'index': 1, 'input_symbols': [1, 2], 'correct_count': 1}])

    def test_ten_second_format_snapshots_every_ten_seconds_with_poses_and_events_at_once(self):
        times = [0, .02, 4.0, 9.98, 10.0, 10.02, 15.0, 20.0, 20.5]
        goals = {0: 0, .02: 1, 4.0: 1, 9.98: 1, 10.0: 1, 10.02: 2, 15.0: 2, 20.0: 2, 20.5: 3}
        results = [{'sim_time_s': t, 'samples': int(t / .02), 'matched_goals': goals[t]} for t in times] + \
                  [{'sim_time_s': 20.5, 'samples': 1025, 'matched_goals': 3}]
        m = monitor('events-10s', results)
        m.object_poses = lambda: {'cube': {'position_m': [0, 0, 0], 'quaternion_wxyz': [1, 0, 0, 0]}}
        # Poses are kept even though the scene records motion: the log is a backup of the recording.
        m.motion_recorded = lambda: True
        for t in times: m.log_sample(t)
        m.d.time = 20.5; m.finish()
        rows = records(m)
        self.assertEqual([(r['type'], r['sim_time_s']) for r in rows],
                         [('snapshot', 0), ('event', .02), ('snapshot', 10.0), ('event', 10.02),
                          ('snapshot', 20.0), ('event', 20.5), ('snapshot', 20.5)])
        self.assertEqual([r['type'] == 'snapshot' for r in rows], ['objects' in r for r in rows])
        self.assertTrue(all(r['objects']['cube']['position_m'] == [0, 0, 0] for r in rows if r['type'] == 'snapshot'))
        m.close()  # the final snapshot is not written twice

    def test_ten_second_format_records_each_trial_once(self):
        results = [{'sim_time_s': t, 'samples': 0, 'valid_trials': n} for t, n in ((0, 0), (1, 1), (2, 1))]
        m = monitor('events-10s', results)
        m.game = type('Game', (), {'trials': []})()
        m.log_sample(0)
        m.game.trials.append({'index': 1, 'input_symbols': [1, 2], 'correct_count': 1})
        m.log_sample(1); m.log_sample(2)
        rows = records(m)
        self.assertEqual([(r['type'], r['sim_time_s']) for r in rows], [('snapshot', 0), ('event', 1)])
        self.assertEqual(rows[1]['trials'], [{'index': 1, 'input_symbols': [1, 2], 'correct_count': 1}])

    def test_unknown_format_is_refused_before_the_log_opens(self):
        with self.assertRaisesRegex(ValueError, 'process log format'):
            Monitor(None, log_format='events-5s')

    def test_full_format_keeps_original_line_per_snapshot_records(self):
        results = [{'sim_time_s': t, 'matched_goals': 0} for t in (0, .05, .1, .15, .2)]
        m = monitor('full', results)
        for t in (0, .05, .1, .15, .2): m.log_sample(t)
        self.assertEqual([r['sim_time_s'] for r in records(m)], [0, .1, .2])
        self.assertTrue(all('type' not in r and 'objects' in r for r in records(m)))


if __name__ == '__main__': unittest.main()
