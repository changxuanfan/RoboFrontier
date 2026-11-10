"""Object positions and dial angles of a run's trial, read from its motion recording.

Every world process records qpos at 30 Hz (`robofrontier.media.motion_recording`): the first in
`outputs/motion`, each continuation segment in `outputs/segments/<n>/motion`. The files are read
through `archive.Run`, so recordings inside a tar or zip are read in place.

The trial's motion follows the process-log rules (extract.trial_rows): a recording is kept up
to the first frame of the next one, whose world was restored at that frame, and nothing after
the trial cutoff counts.

Chunks (2 s each) are the decoding unit: a frame is the XOR of every delta before it in its
chunk, so reading one frame costs as much as reading the whole chunk. Only the needed columns
are reconstructed.
"""

import hashlib
import io
import json
import re

import numpy as np

# An item lower than its starting height by more than this has left the table (extract.suite).
LOST_DROP_M = 0.2
# Lost items are searched in one chunk of every LOST_STRIDE_CHUNKS (a 2 s block per 60 s), and
# the frame where an item first fell is then found in the chunks since the previous searched one.
# A drop of 0.2 m takes an item off the table to the floor, which no arm reaches, so it does not
# come back: on recorded runs with lost items the strided search gave the same items and frames
# as a frame-by-frame scan, no fallen item rose again, and it read 1/30 of the chunks (decoding
# a chunk costs the same for one frame as for all of them).
LOST_STRIDE_CHUNKS = 30
_CHUNK = re.compile(r'chunk-(\d{6})\.npz')


class Recording:
    """One motion folder of a run, read through `archive.Run`."""

    def __init__(self, run, prefix):
        self.run = run
        self.prefix = prefix
        self.meta = json.loads(run.read(prefix + 'stream.json'))
        if self.meta.get('schema') != 'robofrontier.motion.v1':
            raise ValueError('Unsupported motion recording ' + prefix)
        self.nq = int(self.meta['nq'])
        listed = [dict(c) for c in self.meta.get('chunks') or []]
        # A recording that stopped without closing may hold flushed chunks its index does not
        # list yet (as MotionReader.recover); they follow the listed ones by number.
        names = sorted(
            int(m.group(1))
            for n in run.files
            if n.startswith(prefix) and (m := _CHUNK.fullmatch(n[len(prefix) :]))
        )
        for k in names[len(listed) :]:
            if k != len(listed):
                raise ValueError('Motion recording %s has a missing chunk before %06d' % (prefix, k))
            listed.append(dict(file='chunk-%06d.npz' % k, sha256=None))
        self.chunks = listed

    def source(self, name):
        return json.loads(self.run.read(self.prefix + 'source/' + name))

    def decode(self, i, cols):
        """(times, values) of chunk `i` for qpos columns `cols` (float64), checksum-verified."""
        c = self.chunks[i]
        raw = self.run.read(self.prefix + c['file'])
        if c.get('sha256') and hashlib.sha256(raw).hexdigest() != c['sha256']:
            raise ValueError('Motion chunk checksum mismatch: ' + self.prefix + c['file'])
        with np.load(io.BytesIO(raw), allow_pickle=False) as z:
            xor, base, times = z['xor'], z['base'], z['time_s']
            if xor.ndim != 2 or xor.shape[1] != self.nq or len(times) != len(xor):
                raise ValueError('Invalid motion chunk shape: ' + self.prefix + c['file'])
            bits = np.bitwise_xor(np.bitwise_xor.accumulate(xor[:, cols], axis=0), base[cols])
        return np.asarray(times, dtype=float), bits.view('<f4').astype(float)

    def first_time(self):
        c = self.chunks[0] if self.chunks else None
        if c is None:
            return None
        if c.get('start_sim_s') is not None:
            return float(c['start_sim_s'])
        return float(self.decode(0, [0])[0][0])


def recordings(run, outputs):
    """Recordings of a run whose outputs folder is `outputs` ('' or ending in '/'), in order."""
    found = []
    if outputs + 'motion/stream.json' in run.files:
        found.append((0, outputs + 'motion/'))
    pat = re.compile(re.escape(outputs) + r'segments/(\d+)/motion/stream\.json')
    for n in run.files:
        m = pat.fullmatch(n)
        if m:
            found.append((int(m.group(1)), n[: -len('stream.json')]))
    return [Recording(run, p) for _, p in sorted(found)]


class Motion:
    """The motion of one trial: its recordings, each cut at the next one's first frame, and
    everything cut after `cutoff_sim`."""

    def __init__(self, run, outputs, cutoff_sim=None):
        recs = [r for r in recordings(run, outputs) if r.chunks]
        self.recs = recs
        self.cutoff_sim = cutoff_sim
        starts = [r.first_time() for r in recs]
        self.pieces = []  # (recording, chunk index, keep frames with t < end)
        for n, r in enumerate(recs):
            if cutoff_sim is not None and starts[n] > cutoff_sim + 1e-9:
                break
            end = starts[n + 1] if n + 1 < len(recs) else None
            for i, c in enumerate(r.chunks):
                s = c.get('start_sim_s')
                if s is not None and end is not None and s >= end:
                    break
                if s is not None and cutoff_sim is not None and s > cutoff_sim + 1e-9:
                    break
                self.pieces.append((r, i, end))
        self._index = None
        if recs:
            self.task = recs[0].source('task.json')
            self.joints = {j['id']: j for j in recs[0].source('workstation.json')['joints']}
            for r in recs[1:]:
                if r.meta.get('nq') != recs[0].meta.get('nq'):
                    raise ValueError('Motion recordings of one run disagree on the state layout')

    def __bool__(self):
        return bool(self.pieces)

    def __len__(self):
        return len(self.pieces)

    def chunk(self, k, cols):
        """(times, values) of trial chunk `k`, without frames outside the trial."""
        r, i, end = self.pieces[k]
        t, v = r.decode(i, cols)
        keep = np.ones(len(t), bool)
        if end is not None:
            keep &= t < end
        if self.cutoff_sim is not None:
            keep &= t <= self.cutoff_sim + 1e-9
        return t[keep], v[keep]

    def chunks(self, cols):
        for k in range(len(self.pieces)):
            yield self.chunk(k, cols)

    def starts(self):
        """First kept frame time of every trial chunk (decodes only chunks without an index entry)."""
        if self._index is None:
            out = []
            for k, (r, i, _) in enumerate(self.pieces):
                s = r.chunks[i].get('start_sim_s')
                out.append(float(s) if s is not None else float(r.decode(i, [0])[0][0]))
            self._index = out
        return self._index

    def at(self, t, cols):
        """Values of `cols` at the last trial frame at or before `t`, or None before the first."""
        S = self.starts()
        k = int(np.searchsorted(S, t + 1e-9, side='right')) - 1
        while k >= 0:
            ts, v = self.chunk(k, cols)
            j = int(np.searchsorted(ts, t + 1e-9, side='right')) - 1
            if j >= 0:
                return v[j]
            k -= 1
        return None

    def free_address(self, body):
        """qpos address of the free joint that moves `body` (its position is qpos[a:a+3])."""
        for j in self.joints.values():
            if j['type'] == 0 and j['body'] == body:
                return int(j['qpos_address'])
        raise KeyError('No free joint for body %s in the motion recording' % body)

    def hinge_address(self, joint):
        j = self.joints.get(joint)
        if j is None or j['type'] != 3:
            raise KeyError('No hinge joint %s in the motion recording' % joint)
        return int(j['qpos_address'])


def find(run, log_name, cutoff_sim=None):
    """The trial motion of the run whose process log is `log_name`, or None without a recording."""
    outputs = log_name[: -len('suite-process.jsonl')]
    m = Motion(run, outputs, cutoff_sim)
    return m if m else None


def lost_items(motion, items, drop_m=LOST_DROP_M, stride=LOST_STRIDE_CHUNKS):
    """{item: sim time of the first frame more than `drop_m` below its first height}.

    One chunk in `stride` is scanned; when an item is first seen below, the chunks since the
    previous scanned one are read to find the exact frame."""
    items = list(items)
    if not items:
        return {}
    cols = [motion.free_address(i) + 2 for i in items]
    t, z = motion.chunk(0, cols)
    if not len(z):
        raise ValueError('Motion recording starts without a frame in the trial')
    floor = z[0] - drop_m
    lost = {}
    n = len(motion)
    scan = list(range(0, n, max(1, stride)))
    if scan[-1] != n - 1:
        scan.append(n - 1)
    prev = -1
    for j in scan:
        t, z = motion.chunk(j, cols)
        hit = [c for c in range(len(items)) if items[c] not in lost and len(z) and (z[:, c] < floor[c]).any()]
        for k in range(prev + 1, j + 1) if hit else ():
            t, z = motion.chunk(k, cols)
            for c in hit:
                if items[c] in lost:
                    continue
                below = np.flatnonzero(z[:, c] < floor[c])
                if len(below):
                    lost[items[c]] = float(t[below[0]])
        prev = j
    return lost


def positions_at(motion, item_times):
    """{key: [x, y, z]} of each (key, item, sim time) at the last frame at or before that time."""
    out = {}
    for key, item, t in item_times:
        a = motion.free_address(item)
        v = motion.at(t, [a, a + 1, a + 2])
        out[key] = None if v is None else [float(x) for x in v]
    return out


def dial_angles(motion):
    """(times, degrees[frames, dials]) per trial chunk, dials in task order, every frame.

    No chunk is skipped: a 1 s settle is shorter than one chunk, so a skipped chunk could hide
    a whole turn, and keeping every frame of a decoded chunk costs nothing more."""
    cols = [motion.hinge_address(d['id'] + '_hinge') for d in motion.task['dials']]
    for t, q in motion.chunks(cols):
        if len(t):
            yield t, np.degrees(q)
