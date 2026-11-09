"""Run analysis over continuation segments and the 24 h trial cutoff, on synthetic runs only.

A run folder here holds what extract reads: private/outputs/suite-process.jsonl (one header
per world process), private/state/runtime.sqlite, private/logs/host.jsonl and, for a run that
reached its wall limit, private/outputs/budget-cutoff.json.
"""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from robofrontier.run_analysis import atomic_v2, extract
from robofrontier.run_analysis import metrics as M
from robofrontier.run_analysis.archive import Run

BASE = 1_000_000.0  # wall time = BASE + sim time


def header(fmt='events-1s'):
    return {'schema': 'robofrontier.suite-process.v2', 'format': fmt}


def snap(t, objects=None, **result):
    row = {'type': 'snapshot', 'sim_time_s': t, 'result': {'sim_time_s': t, **result}}
    if objects is not None:
        row['objects'] = objects
    return row


def action(arm, t0, t1, status='completed', kind='move', mode=None, target=(0.0, 0.0, 0.8), reason=None):
    return {'arm': arm, 'type': kind, 'status': status, 'reason': reason, 'started_at': BASE + t0,
            'finished_at': BASE + t1, 'started_sim_s': t0, 'finished_sim_s': t1,
            'parameters': {'target_m': list(target), 'mode': mode}}


class Fixture:
    def __init__(self, root, name='run'):
        self.dir = Path(root) / name
        (self.dir / 'private/outputs').mkdir(parents=True)
        (self.dir / 'private/state').mkdir(parents=True)
        (self.dir / 'private/logs').mkdir(parents=True)
        self.root = Path(root)
        self.name = name

    def log(self, rows):
        text = ''.join(json.dumps(r) + '\n' for r in rows)
        (self.dir / 'private/outputs/suite-process.jsonl').write_text(text)

    def db(self, actions=(), events=(), messages=()):
        db = sqlite3.connect(self.dir / 'private/state/runtime.sqlite')
        db.executescript('''
            CREATE TABLE actions(id TEXT PRIMARY KEY, actor TEXT, status TEXT NOT NULL, value TEXT NOT NULL);
            CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, kind TEXT, actor TEXT, value TEXT);
            CREATE TABLE messages(seq INTEGER PRIMARY KEY AUTOINCREMENT, created REAL NOT NULL);
            CREATE TABLE agents(id TEXT PRIMARY KEY, value TEXT NOT NULL);''')
        for n, a in enumerate(actions):
            db.execute('INSERT INTO actions VALUES (?,?,?,?)', ('a%d' % n, a['arm'], a['status'], json.dumps(a)))
        for created, kind, value in events:
            db.execute('INSERT INTO events(created,kind,actor,value) VALUES (?,?,?,?)',
                       (created, kind, 'Meta', json.dumps(value)))
        for created in messages:
            db.execute('INSERT INTO messages(created) VALUES (?)', (created,))
        db.commit()
        db.close()

    def host(self, events):
        text = ''.join(json.dumps(e) + '\n' for e in events)
        (self.dir / 'private/logs/host.jsonl').write_text(text)

    def write(self, name, value):
        (self.dir / 'private/outputs' / name).write_text(json.dumps(value))

    def extract(self, family):
        return extract.extract_run(dict(id=self.name, k=self.name, family=family), self.root)


def tokens(t, total):
    return {'at': BASE + t, 'event': 'thread/tokenUsage/updated', 'thread_id': 'th1',
            'token_usage': {'total': {'inputTokens': total, 'cachedInputTokens': 0, 'outputTokens': 1},
                            'last': {'inputTokens': total, 'cachedInputTokens': 0, 'outputTokens': 1}}}


def item(z):
    return {'position_m': [0.0, 0.0, z]}


class TransportCutoffTests(unittest.TestCase):
    """Goals g1 (t=50) and g2 (t=150); the trial was cut at t=100 with 1/2 goals."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def make(self, with_cutoff_file):
        f = Fixture(self.tmp)
        objs = {'A_item1': item(0.8), 'A_item2': item(0.8)}
        rows = [header()]
        for t in range(10, 201, 10):
            a = {}
            if t >= 50:
                a['g1'] = 'A_item1'
            if t >= 150:
                a['g2'] = 'A_item2'
            done = len(a) == 2
            rows.append(snap(float(t), objs, assignments=a, matched_goals=len(a), total_goals=2,
                             all_goals_met=done, task_success=done))
        f.log(rows)
        acts = [action('A', 0, 5), action('A', 40, 49, kind='gripper', mode='release'),
                action('A', 60, 70, status='failed', reason='motion timeout'),
                action('A', 95, 105, status='failed', reason='motion timeout'),
                action('A', 140, 149, kind='gripper', mode='release'), action('A', 190, 199)]
        events = [(BASE, 'START', {}), (BASE + 100, 'POLICY_WALL_LIMIT', {'sim_time_s': 100.0}),
                  (BASE + 199, 'RUN_SEALED', {})]
        f.db(acts, events, messages=[BASE + 20, BASE + 160])
        f.host([tokens(30, 100), {'at': BASE + 90, 'event': 'turn/started', 'thread_id': 'th1', 'turn_id': 't'},
                {'at': BASE + 120, 'event': 'turn/completed', 'thread_id': 'th1', 'turn_id': 't'},
                tokens(150, 300)])
        if with_cutoff_file:
            f.write('budget-cutoff.json', {'cutoff_unix_s': BASE + 100, 'sim_time_s': 100.0, 'evaluation': {
                'matched_goals': 1, 'total_goals': 2, 'all_goals_met': False, 'task_success': False}})
        f.write('evaluation.json', {'matched_goals': 2, 'total_goals': 2, 'all_goals_met': True})
        return f

    def check(self, d, source):
        self.assertEqual((d['cutoff']['source'], d['cutoff']['unix'], d['cutoff']['sim']), (source, BASE + 100, 100.0))
        self.assertEqual(d['suite']['last_sim'], 100.0)
        o = M.compute(d)
        self.assertEqual(o['outcome']['label'], '1/2')
        self.assertFalse(o['outcome']['success'])
        self.assertLessEqual(o['timing']['last'], BASE + 100)
        self.assertAlmostEqual(o['timing']['clock_h'], 100 / 3600)
        self.assertEqual(o['atomic']['delivered'], 1)
        self.assertEqual(o['atomic']['failed_actions'], 1)  # the failure at t=105 is after the trial
        self.assertEqual(o['tokens']['input'], 100)  # the update at t=150 is after the trial
        self.assertEqual(d['host']['turns'], [[None, BASE + 90, BASE + 100]])
        self.assertEqual(o['messages'], 1)
        self.assertEqual(len(d['actions']), 4)  # the actions started at t=140 and t=190 are dropped
        v2 = atomic_v2.compute(d)
        self.assertEqual(v2['delivered'], 1)

    def test_scores_the_budget_cutoff_evaluation_not_the_last_row(self):
        self.check(self.make(True).extract('transport'), 'budget-cutoff.json')

    def test_without_the_cutoff_file_the_wall_limit_event_cuts_the_trial(self):
        self.check(self.make(False).extract('transport'), 'POLICY_WALL_LIMIT event')

    def test_a_run_that_never_reached_the_limit_is_not_cut(self):
        f = self.make(False)
        (f.dir / 'private/state/runtime.sqlite').unlink()
        f.db([action('A', 0, 5), action('A', 190, 199)], [(BASE, 'START', {})])
        d = f.extract('transport')
        self.assertIsNone(d['cutoff'])
        self.assertEqual(M.compute(d)['outcome']['label'], '2/2')


class SegmentTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def test_extract_drops_rows_after_the_next_segments_restore_frame(self):
        f = Fixture(self.tmp)
        h = lambda t, s, r: {'sim_time_s': t, 'senders': s, 'receivers': r, 'protocol': 'p'}
        first = h(50.0, ['A'], ['B'])
        tail = h(101.0, ['B'], ['C'])  # after segment 1's restore frame (t=100): never kept
        redo = h(103.0, ['B'], ['C'])
        pay = lambda hs, drops=0: {'payloads': {'p1': {'handovers': hs, 'drops': drops}},
                                   'total_payloads': 1, 'completed_payloads': 0}
        f.log([header(), snap(40.0, **pay([])), snap(60.0, **pay([first])),
               snap(101.0, **pay([first, tail], drops=1)),
               header(), snap(100.0, **pay([first])), snap(103.0, **pay([first, redo]))])
        f.db([action('A', 0, 5), action('B', 95, 110)], [(BASE, 'START', {})])
        d = f.extract('relay')
        self.assertEqual(d['suite']['segments'], 2)
        self.assertEqual([x['t'] for x in d['suite']['handovers']['p1']], [50.0, 103.0])
        self.assertEqual(d['suite']['drops'], [])

    def dial_rows(self, carried):
        row = lambda t, trials, best, **extra: snap(float(t), valid_trials=trials, display=best,
                                                    feedback_mode='best_so_far', solved=False, **extra)
        # Segment 0 reached 65 trials; trial 66 came after the restore frame (t=40).
        rows = [header(), row(10, 64, 5), row(30, 65, 6), row(45, 66, 6), header()]
        if carried:
            rows += [row(40, 65, 6, carried_valid_trials=65), row(50, 67, 7, carried_valid_trials=65)]
        else:  # a segment from before carry-over existed counted from zero
            rows += [row(40, 0, 0), row(50, 2, 3)]
        return rows

    def test_dial_trials_of_a_segment_that_restarted_from_zero_are_added(self):
        for carried in (False, True):
            with self.subTest(carried=carried):
                f = Fixture(self.tmp, 'dial%d' % carried)
                f.log(self.dial_rows(carried))
                f.db([action('A', 0, 5), action('A', 45, 55)], [(BASE, 'START', {})])
                d = f.extract('dial')
                o = M.compute(d)
                self.assertEqual(o['outcome']['trials'], 67)
                self.assertEqual(o['atomic']['delivered'], 67)

    def test_timing_excludes_segment_downtime_and_classifies_host_stops(self):
        host = {'first': BASE, 'last': BASE + 3600, 'turns': [['A', BASE, BASE + 600], ['A', BASE + 2400, BASE + 3600]]}
        d = dict(sel=dict(id='x', family='transport'), host=host, meta={},
                 actions=[], **{'runtime.json': {'segments': [
                     {'started_at': BASE, 'ended_at': BASE + 900}, {'started_at': BASE + 1500}]}})
        T = M.timing(d)
        # Downtime 900-1500 s is recorded; the quiet 600-900 and 1500-2400 s are host stops (no cycles).
        self.assertAlmostEqual(T['recorded_h'], 600 / 3600)
        self.assertAlmostEqual(T['stops_h'], 1200 / 3600)
        self.assertAlmostEqual(T['active_h'], 1800 / 3600)
        self.assertEqual(T['stop_src'], 'gap>=300s')
        # With liveness cycles in every minute the same quiet stretches are stalls inside active time.
        host['cycles'] = {str(int((BASE + s) // 60)): 1 for s in range(0, 3601, 30)}
        T = M.timing(d)
        self.assertEqual(T['stop_src'], 'cycles')
        self.assertAlmostEqual(T['active_h'], 3000 / 3600)
        self.assertAlmostEqual(T['other_stall_h'], 1200 / 3600)


class SparseLogTests(unittest.TestCase):
    """events-60s logs have object poses and dial angles only every 60 s or in the final row."""

    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def transport_log(self, fmt):
        rows = [header(fmt)]
        for t in range(0, 121):
            fell = t >= 75
            final = t == 120
            objs = {'A_item1': item(0.8), 'A_item2': item(-0.5 if fell else 0.8)}
            a = {'g1': 'A_item1'} if t >= 30 else {}
            # events-10s snapshots carry poses every 10 s; the rows at 30 s and 75 s are events.
            every = fmt == 'events-1s' or (fmt == 'events-10s' and t % 10 == 0)
            keep = every or final or t in (0, 60)
            if keep or t in (30, 75):
                with_objects = every or final
                rows.append(snap(float(t), objs if with_objects else None, assignments=a,
                                 matched_goals=len(a), total_goals=2))
        return rows

    def test_lost_items_are_unknown_not_zero_in_a_sparse_log(self):
        out = {}
        for fmt in ('events-1s', 'events-60s'):
            f = Fixture(self.tmp, fmt)
            f.log(self.transport_log(fmt))
            f.db([action('A', 0, 5), action('A', 100, 110)], [(BASE, 'START', {})])
            out[fmt] = f.extract('transport')
        self.assertEqual(out['events-1s']['suite']['lost'], {'A_item2': 75.0})
        self.assertIsNone(out['events-1s']['suite'].get('objects_unknown'))
        S = out['events-60s']['suite']
        self.assertIsNone(S['lost'])
        self.assertTrue(S['objects_unknown'])
        self.assertIsNone(S['goals']['g1']['pos'])
        a = M.compute(out['events-60s'])['atomic']
        self.assertIsNone(a['lost'])
        self.assertTrue(a['objects_unknown'])
        self.assertTrue(atomic_v2.compute(out['events-60s'])['objects_unknown'])

    def test_a_ten_second_log_without_a_recording_still_gives_lost_items_and_dial_turns(self):
        self.assertTrue(extract.use_motion(['events-10s'], 'sparse'))
        f = Fixture(self.tmp, 'transport-10s')
        f.log(self.transport_log('events-10s'))
        f.db([action('A', 0, 5), action('A', 100, 110)], [(BASE, 'START', {})])
        S = f.extract('transport')['suite']
        # The fall at 75 s shows in the next snapshot with poses.
        self.assertEqual(S['lost'], {'A_item2': 80.0})
        self.assertIsNone(S.get('objects_unknown'))
        self.assertEqual(S['objects_source'], 'process log')
        self.assertEqual(S['goals']['g1']['pos'], [0.0, 0.0, 0.8])
        angles = lambda t, a: snap(float(t), private_angles_deg=[a], valid_trials=0)
        f = Fixture(self.tmp, 'dial-10s')
        f.log([header('events-10s'), angles(0, 0.0), angles(10, 0.0), angles(20, 60.0), angles(30, 60.0)])
        f.db([action('A', 0, 5)], [(BASE, 'START', {})])
        r = atomic_v2.run_dial_turns(Run('dial-10s', f.root))
        self.assertEqual((r['turns'], r['unknown'], r['source']), ([[20.0, 0]], None, 'process log'))

    def test_dial_turns_are_unknown_in_a_sparse_log(self):
        angles = lambda t, a: snap(float(t), private_angles_deg=[a], valid_trials=0)
        for fmt, want in (('events-1s', [[3.0, 0]]), ('events-60s', None)):
            f = Fixture(self.tmp, fmt)
            f.log([header(fmt), angles(0, 0.0), angles(1, 0.0), angles(3, 60.0), angles(5, 60.0)])
            f.db([action('A', 0, 5)], [(BASE, 'START', {})])
            r = atomic_v2.run_dial_turns(Run(fmt, f.root))
            self.assertEqual(r['turns'], want)
            self.assertEqual(r['unknown'] is None, want is not None)

    def test_dial_turns_are_cut_at_the_trial_cutoff_and_found_like_extract_finds_the_log(self):
        angles = lambda t, a: snap(float(t), private_angles_deg=[a], valid_trials=0)
        f = Fixture(self.tmp, 'outer/run')
        f.log([header(), angles(0, 0.0), angles(1, 0.0), angles(3, 60.0), angles(5, 60.0),
               angles(10, 120.0), angles(12, 120.0)])
        f.db([action('A', 0, 5)], [(BASE, 'START', {}), (BASE + 8, 'POLICY_WALL_LIMIT', {'sim_time_s': 8.0})])
        self.assertEqual(atomic_v2.run_dial_turns(Run('outer/run', f.root))['turns'], [[3.0, 0]])
        # Keyed one level above the run folder, the log is still found.
        self.assertEqual(atomic_v2.run_dial_turns(Run('outer', f.root))['turns'], [[3.0, 0]])


if __name__ == '__main__':
    unittest.main()
