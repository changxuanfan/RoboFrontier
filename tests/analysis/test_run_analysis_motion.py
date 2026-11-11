"""Object poses and Dial angles from the motion recording when the process log is events-60s.

Synthetic runs only: an events-60s log as Monitor.log_sample writes it for a scene that records
motion (poses only in the final row, angles only every 60 s) beside a 30 Hz recording written in
the robofrontier.motion.v1 layout (2 s chunks of XOR deltas over float32 qpos).
"""

import hashlib
import json
import tarfile
import tempfile
import unittest

import numpy as np

from robofrontier.analysis import atomic, extract, motion
from robofrontier.analysis import metrics as M
from robofrontier.analysis.archive import Run
from analysis.test_run_analysis_segments import BASE, Fixture, action, header, snap

HZ = 30


def write_motion(folder, task, joints, times, states, chunk_frames=60, listed=None):
    """A recording as MotionWriter leaves it; `listed` chunks in stream.json (default all)."""
    folder.mkdir(parents=True)
    (folder / 'source').mkdir()
    (folder / 'source/task.json').write_text(json.dumps(task))
    (folder / 'source/workstation.json').write_text(json.dumps({'joints': joints}))
    q = np.asarray(states, dtype='<f4')
    times = np.asarray(times, dtype='<f8')
    prev = q[0].view('<u4').copy()
    chunks = []
    for n, s in enumerate(range(0, len(q), chunk_frames)):
        bits = q[s : s + chunk_frames].view('<u4')
        delta = np.bitwise_xor(bits, np.vstack((prev[None, :], bits[:-1])))
        name = 'chunk-%06d.npz' % n
        with open(folder / name, 'wb') as f:
            np.savez_compressed(f, base=prev, xor=delta, time_s=times[s : s + chunk_frames],
                                wall_monotonic_s=times[s : s + chunk_frames])
        chunks.append(dict(file=name, sha256=hashlib.sha256((folder / name).read_bytes()).hexdigest(),
                           frames=len(bits), start_sim_s=float(times[s]),
                           end_sim_s=float(times[min(s + chunk_frames, len(q)) - 1])))
        prev = bits[-1].copy()
    meta = dict(schema='robofrontier.motion.v1', nq=q.shape[1], sample_hz=HZ,
                status='complete' if listed is None else 'recording', chunks=chunks[:listed])
    (folder / 'stream.json').write_text(json.dumps(meta))


def free_joints(names):
    return [dict(id=n + '_free', body=n, type=0, qpos_address=7 * k) for k, n in enumerate(names)]


ITEMS = ['A_item1', 'A_item2']
TRANSPORT_TASK = {'objects': [{'id': i} for i in ITEMS]}


def transport_states(times, fall_at=None, fall_in_segment_tail=None):
    """Both items rest at z=0.8; A_item2 drops to z=-0.5 from `fall_at`; A_item1 moves to
    (0.3, 0.1) at t=29 s and rests there (its goal is assigned at t=30 s)."""
    S = np.zeros((len(times), 14))
    S[:, 2] = S[:, 9] = 0.8
    S[:, 3] = S[:, 10] = 1.0
    S[times >= 29, 0:2] = [0.3, 0.1]
    if fall_at is not None:
        S[times >= fall_at, 9] = -0.5
    return S


def transport_log(end=120, objects_final=True):
    """events-60s: snapshots every 60 s without objects, events when assignments change,
    objects only in the final row."""
    rows = [header('events-60s')]
    obj = {'A_item1': {'position_m': [0.3, 0.1, 0.8]}, 'A_item2': {'position_m': [0.0, 0.0, 0.8]}}
    for t in sorted({0, 30, 60, end}):
        a = {'g1': 'A_item1'} if t >= 30 else {}
        final = t == end
        rows.append(snap(float(t), obj if final and objects_final else None, assignments=a,
                         matched_goals=len(a), total_goals=2))
    return rows


def frames(t0, t1):
    n = int(round((t1 - t0) * HZ))
    return t0 + np.arange(n + 1) / HZ


class TransportFromMotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def run_with(self, name, log, recordings, events=()):
        f = Fixture(self.tmp, name)
        f.log(log)
        f.db([action('A', 0, 5), action('A', 25, 29, kind='gripper', mode='release'), action('A', 100, 110)],
             [(BASE, 'START', {})] + list(events))
        for sub, times, states in recordings:
            write_motion(f.dir / 'private/outputs' / sub, TRANSPORT_TASK, free_joints(ITEMS), times, states)
        return f

    def test_lost_items_and_goal_positions_come_from_motion_for_an_events_60s_log(self):
        t = frames(0, 120)
        f = self.run_with('t60', transport_log(), [('motion', t, transport_states(t, fall_at=75.4))])
        S = f.extract('transport')['suite']
        self.assertEqual(S['objects_source'], 'motion')
        self.assertIsNone(S.get('objects_unknown'))
        self.assertEqual(list(S['lost']), ['A_item2'])
        self.assertAlmostEqual(S['lost']['A_item2'], 75.4, places=6)  # exact frame, between snapshots
        np.testing.assert_allclose(S['goals']['g1']['pos'], [0.3, 0.1, 0.8], atol=1e-6)
        d = f.extract('transport')
        self.assertEqual(M.compute(d)['atomic']['lost'], 1)
        self.assertIsNone(atomic.compute(d)['objects_unknown'])

    def test_without_a_recording_a_sparse_log_still_leaves_objects_unknown(self):
        f = self.run_with('t60-bare', transport_log(), [])
        S = f.extract('transport')['suite']
        self.assertIsNone(S['lost'])
        self.assertIsNone(S['objects_source'])
        self.assertIn('no motion recording', S['objects_unknown'])

    def test_a_fall_after_the_next_segments_restore_frame_or_the_cutoff_is_not_lost(self):
        # Segment 0 recorded on to 110 s and its item fell at 105 s, but segment 1 restored the
        # world at 100 s and the item stayed; a later fall at 150 s is after the 140 s cutoff.
        t0, t1 = frames(0, 110), frames(100, 160)
        f = self.run_with('t60-seg', transport_log(160),
                          [('motion', t0, transport_states(t0, fall_at=105)),
                           ('segments/1/motion', t1, transport_states(t1, fall_at=150))],
                          [(BASE + 140, 'POLICY_WALL_LIMIT', {'sim_time_s': 140.0})])
        S = f.extract('transport')['suite']
        self.assertEqual(S['objects_source'], 'motion')
        self.assertEqual(S['lost'], {})
        # Without the cutoff the 150 s fall in segment 1 counts.
        g = self.run_with('t60-seg-nocut', transport_log(160),
                          [('motion', t0, transport_states(t0, fall_at=105)),
                           ('segments/1/motion', t1, transport_states(t1, fall_at=150))])
        self.assertAlmostEqual(g.extract('transport')['suite']['lost']['A_item2'], 150.0, places=6)

    def test_the_strided_search_finds_the_same_frame_as_a_full_scan(self):
        t = frames(0, 600)
        f = self.run_with('t60-long', transport_log(600), [('motion', t, transport_states(t, fall_at=333.3))])
        run = Run('t60-long', f.root)
        m = motion.find(run, run.find(*extract.SUITE_LOGS))
        self.assertGreater(len(m), 3 * motion.LOST_STRIDE_CHUNKS)
        full = motion.lost_items(m, ITEMS, stride=1)
        self.assertEqual(motion.lost_items(m, ITEMS), full)
        self.assertAlmostEqual(full['A_item2'], 333.3, places=6)

    def test_every_run_with_a_recording_is_read_from_motion_unless_sparse_is_asked_for(self):
        t = frames(0, 120)
        rows = [header('events-1s')]
        for s in range(0, 121):
            a = {'g1': 'A_item1'} if s >= 30 else {}
            z2 = -0.5 if s >= 76 else 0.8
            obj = {'A_item1': {'position_m': [0.3, 0.1, 0.8] if s >= 29 else [0, 0, 0.8]},
                   'A_item2': {'position_m': [0, 0, z2]}}
            rows.append(snap(float(s), obj, assignments=a, matched_goals=len(a), total_goals=2))
        f = self.run_with('t1', rows, [('motion', t, transport_states(t, fall_at=75.4))])
        S = f.extract('transport')['suite']
        self.assertEqual(S['objects_source'], 'motion')
        self.assertAlmostEqual(S['lost']['A_item2'], 75.4, places=6)
        run = Run('t1', f.root)
        S = extract.suite(run, motion='sparse')
        self.assertEqual((S['objects_source'], S['lost']), ('process log', {'A_item2': 76.0}))

    def test_events_10s_logs_prefer_the_recording_and_fall_back_to_their_poses(self):
        t = frames(0, 120)
        rows = [header('events-10s')]
        for s in sorted(set(range(0, 121, 10)) | {30, 120}):
            a = {'g1': 'A_item1'} if s >= 30 else {}
            obj = {'A_item1': {'position_m': [0.3, 0.1, 0.8]}, 'A_item2': {'position_m': [0, 0, -0.5 if s >= 80 else 0.8]}}
            rows.append(snap(float(s), obj, assignments=a, matched_goals=len(a), total_goals=2))
        f = self.run_with('t10', rows, [('motion', t, transport_states(t, fall_at=75.4))])
        S = f.extract('transport')['suite']
        self.assertEqual(S['objects_source'], 'motion')
        self.assertAlmostEqual(S['lost']['A_item2'], 75.4, places=6)
        g = self.run_with('t10-bare', rows, [])
        S = g.extract('transport')['suite']
        self.assertEqual((S['objects_source'], S['lost'], S.get('objects_unknown')),
                         ('process log', {'A_item2': 80.0}, None))

    def test_chunks_missing_from_an_unclosed_index_are_read(self):
        t = frames(0, 120)
        f = Fixture(self.tmp, 'open')
        f.log(transport_log())
        f.db([action('A', 0, 5)], [(BASE, 'START', {})])
        write_motion(f.dir / 'private/outputs/motion', TRANSPORT_TASK, free_joints(ITEMS), t,
                     transport_states(t, fall_at=110), listed=40)
        self.assertAlmostEqual(f.extract('transport')['suite']['lost']['A_item2'], 110.0, places=6)

    def test_a_recording_inside_a_tar_is_read_in_place(self):
        t = frames(0, 120)
        f = self.run_with('t60-tar', transport_log(), [('motion', t, transport_states(t, fall_at=75.4))])
        with tarfile.open(f.root / 'pack.tar', 'w') as tar:
            tar.add(f.dir, arcname='t60-tar')
        run = Run('pack.tar//t60-tar', f.root, f.root / 'cache')
        try:
            self.assertAlmostEqual(extract.suite(run)['lost']['A_item2'], 75.4, places=6)
        finally:
            run.close()


DIAL_TASK = {'dials': [{'id': 'D01'}, {'id': 'D02'}]}
DIAL_JOINTS = [dict(id='D01_hinge', body='D01_rotor', type=3, qpos_address=0),
               dict(id='D02_hinge', body='D02_rotor', type=3, qpos_address=1)]


def dial_states(times, path):
    """Dial 0 follows `path` [(from_s, degrees)], each step a 0.3 s ramp; dial 1 stays at 0."""
    a = np.full(len(times), path[0][1])
    for (s, deg), (_, prev) in zip(path[1:], path):
        a = np.where(times >= s, prev + (deg - prev) * np.clip((times - s) / 0.3, 0, 1), a)
    return np.radians(np.stack([a, np.zeros(len(times))], axis=1))


def dial_log(end, every=60):
    angles = lambda t: snap(float(t), valid_trials=0, display=0, solved=False)
    return [header('events-60s')] + [angles(t) for t in range(0, end + 1, every)]


class DialFromMotionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = self.enterContext(tempfile.TemporaryDirectory())

    def dial_run(self, name, recordings, events=(), end=60):
        f = Fixture(self.tmp, name)
        f.log(dial_log(end))
        f.db([action('A', 0, 5)], [(BASE, 'START', {})] + list(events))
        for sub, times, path in recordings:
            write_motion(f.dir / 'private/outputs' / sub, DIAL_TASK, DIAL_JOINTS, times, dial_states(times, path))
        return atomic.run_dial_turns(Run(name, f.root))

    def test_two_turns_between_60_s_rows_come_from_motion(self):
        # 0 -> 60 at 10 s, 60 -> 180 at 20 s passing 120 without dwelling, 180 -> 240 at 30.5 s
        # for 0.8 s only, then back to 180: two turns.
        t = frames(0, 60)
        r = self.dial_run('d60', [('motion', t, [(0, 0.0), (10, 60.0), (20, 180.0), (30.5, 240.0), (31.3, 180.0)])])
        self.assertEqual(r['source'], 'motion')
        self.assertIsNone(r['unknown'])
        self.assertEqual([k for _, k in r['turns']], [0, 0])
        np.testing.assert_allclose([s for s, _ in r['turns']], [10.3 - 4 / 60 * 0.3, 20.3 - 4 / 120 * 0.3], atol=1 / HZ)

    def test_without_a_recording_turns_stay_unknown(self):
        r = self.dial_run('d60-bare', [])
        self.assertIsNone(r['turns'])
        self.assertIn('no motion recording', r['unknown'])

    def test_turns_respect_segment_restores_and_the_cutoff(self):
        # Segment 0 turned dial 0 to 60 at 40 s, after segment 1's restore frame (35 s); segment 1
        # turned it to 120 at 50 s and to 180 at 70 s, after the 65 s cutoff: one turn counts.
        t0, t1 = frames(0, 45), frames(35, 80)
        r = self.dial_run('d60-seg', [('motion', t0, [(0, 0.0), (40, 60.0)]),
                                      ('segments/1/motion', t1, [(0, 0.0), (50, 120.0), (70, 180.0)])],
                          [(BASE + 65, 'POLICY_WALL_LIMIT', {'sim_time_s': 65.0})], end=80)
        self.assertEqual(len(r['turns']), 1)
        self.assertAlmostEqual(r['turns'][0][0], 50.3 - 4 / 120 * 0.3, delta=1 / HZ)

    def test_the_rule_gives_the_same_turns_frame_by_frame_or_by_chunk(self):
        t = frames(0, 60)
        A = np.degrees(dial_states(t, [(0, 0.0), (10, 60.0), (20, 180.0), (30.5, 240.0), (31.3, 180.0)]))
        whole = atomic.DialSettle()
        whole.feed(t, A)
        single = atomic.DialSettle()
        for k in range(len(t)):
            single.feed(t[k : k + 1], A[k : k + 1])
        self.assertEqual(whole.turns(), single.turns())
        self.assertEqual(len(whole.turns()), 2)


if __name__ == '__main__':
    unittest.main()
