"""Atomic steps, version 2.

- Transport: one step per handoff (a release followed, within `HANDOFF_RADIUS_M`, by a grasp
  from a different arm) plus one per goal's first delivery; in-place regrasps are not steps.
- Mosaic: unchanged from version 1 (`metrics.goals_atomic`), one step per cube first placed
  correctly.
- Relay: one step per arm that newly grips a timber in a qualified handover.
- Dial: one step per dial that settles, for at least `DIAL_DWELL_S`, at a 60-degree mark
  (within the evaluator's 4-degree band) different from its last settled mark.

Failure events, their exclusions and leftover failed attempts follow version 1; each failure
event marks at most one step.
"""

import bisect
import collections
import json
import math

import numpy as np

from . import extract
from . import motion as trial_motion
from . import metrics as M

DIAL_MARK_DEG = 60.0
DIAL_BAND_DEG = 4.0
DIAL_DWELL_S = 1.0
HANDOFF_RADIUS_M = 0.08


def dial_turns(lines, dwell_s=DIAL_DWELL_S):
    """[[sim_s, dial], ...] for each dial settling at a new mark, from suite-process lines."""
    rows = []
    for line in lines:
        if '"private_angles_deg"' not in line:
            continue
        try:
            x = json.loads(line)
        except ValueError:
            continue
        rows.append(x)
    return dial_turns_rows(rows, dwell_s)


class DialSettle:
    """The Dial turn rule over angle samples in trial order (log rows or motion frames).

    A dial is at a mark while its angle is within DIAL_BAND_DEG of a multiple of DIAL_MARK_DEG.
    It settles once samples at least `dwell_s` apart show it at the same mark with no sample
    between at another mark or between marks; a settle at a mark other than the dial's last
    settled one is a turn, timed when the dial reached that mark."""

    def __init__(self, dwell_s=DIAL_DWELL_S):
        self.dwell_s = dwell_s
        self.cur = None  # per dial: [mark or None, time reached, settled already]
        self.settled = None
        self.found = []  # [sim time the settle was seen, dial, time reached]

    def feed(self, times, degrees):
        """Samples `times` (n,) and angles `degrees` (n, dials), in time order."""
        times = np.asarray(times, dtype=float)
        A = np.asarray(degrees, dtype=float).reshape(len(times), -1)
        if not len(times):
            return
        if self.cur is None:
            self.cur = [[None, times[0], False] for _ in range(A.shape[1])]
            self.settled = [None] * A.shape[1]
        q = np.round(A / DIAL_MARK_DEG)
        at = np.abs(A - DIAL_MARK_DEG * q) <= DIAL_BAND_DEG
        code = np.where(at, q, np.nan)
        for k in range(A.shape[1]):
            c = code[:, k]
            same = (c[1:] == c[:-1]) | (np.isnan(c[1:]) & np.isnan(c[:-1]))
            cuts = np.flatnonzero(~same) + 1
            for s, e in zip(np.r_[0, cuts], np.r_[cuts, len(c)]):
                b = None if np.isnan(c[s]) else int(c[s])
                cur = self.cur[k]
                first = s
                if b != cur[0]:
                    cur[:] = [b, float(times[s]), False]
                    first = s + 1  # the sample that reached a mark only starts its dwell
                if b is None or cur[2]:
                    continue
                hit = np.flatnonzero(times[first:e] - cur[1] >= self.dwell_s)
                if len(hit):
                    cur[2] = True
                    if self.settled[k] is not None and b != self.settled[k]:
                        self.found.append([float(times[first + hit[0]]), k, cur[1]])
                    self.settled[k] = b

    def turns(self):
        """[[sim_s reached, dial], ...] in the order the settles were seen."""
        return [[t, k] for _, k, t in sorted(self.found, key=lambda x: (x[0], x[1]))]


def dial_turns_rows(rows, dwell_s=DIAL_DWELL_S):
    """As dial_turns, from parsed evaluator rows in trial order."""
    rule = DialSettle(dwell_s)
    for x in rows:
        A = (x.get('result') or {}).get('private_angles_deg')
        t = extract.row_sim(x)
        if A is None or t is None:
            continue
        rule.feed([t], [A])
    return rule.turns()


def run_dial_turns(run, dwell_s=DIAL_DWELL_S, motion='always'):
    """Dial turns of an `archive.Run` within the trial: {'turns': [...], 'unknown': None, ...}.

    The evaluator log is found as extract.suite finds it; a run without one raises
    FileNotFoundError. The trial is cut per segment and at the trial cutoff (extract.trial_rows).
    Angles come from the motion recording, every 30 Hz frame, when extract.use_motion says so
    (always for a sparse 'events-60s' log, which has angles only every 60 s) and the run has
    one; otherwise from the log rows. A sparse log without a recording cannot show turns, so
    `turns` is None and `unknown` says why. `source` names where the angles came from."""
    n = run.find(*extract.SUITE_LOGS)
    if not n:
        raise FileNotFoundError('No evaluator log (suite-process.jsonl) in run ' + run.k)
    cut = extract.trial_cutoff(run)
    sim = cut and cut['sim']
    blocks = extract.log_blocks(run, n)
    formats = sorted({b['format'] for b in blocks if b['format']})
    low = [f for f in formats if f in extract.LOW_RESOLUTION]
    out = dict(turns=None, unknown=None, formats=formats, cutoff_sim=sim, source=None)
    rec = trial_motion.find(run, n, sim) if extract.use_motion(formats, motion) else None
    if rec is not None:
        rule = DialSettle(dwell_s)
        for t, A in trial_motion.dial_angles(rec):
            rule.feed(t, A)
        out.update(turns=rule.turns(), source='motion')
        return out
    if low:
        out['unknown'] = (
            'process log %s records dial angles only every 60 s and the run has no motion recording'
            % '/'.join(low)
        )
        return out
    rows = (d for _, _, d in extract.trial_rows(run, n, sim, blocks))
    out.update(turns=dial_turns_rows(rows, dwell_s), source='process log')
    return out


def turn_list(turns):
    """Turns from a run_dial_turns result (or an older plain list); None when unknown."""
    return turns.get('turns') if isinstance(turns, dict) else turns


def result(steps, extra, obj_extra):
    N = len(steps) + len(extra)
    fa = sum(bool(s['failed']) for s in steps) + len(extra)
    fo = (
        sum('object' in s['failed'] for s in steps)
        + sum('object' in v for v in extra.values())
        + obj_extra
    )
    return dict(
        atomic_total=N,
        atomic_failed=fa,
        atomic_failed_object=fo,
        delivered=len(steps),
        trailing=len(extra),
        timeline=sorted([s['t'], bool(s['failed'])] for s in steps),
    )


def goal_arms(S, A, clk):
    """Arm credited with each goal, as in metrics.goals_atomic."""
    opens = collections.defaultdict(list)
    moves = collections.defaultdict(list)
    for x in sorted(A, key=lambda x: x['s']):
        if x['type'] == 'gripper' and x['status'] == 'completed' and x.get('mode') != 'grasp':
            opens[x['arm']].append(x['e'])
        if x['type'] == 'move' and x.get('target'):
            moves[x['arm']].append((x['e'], x['target']))
    out = {}
    for g, i in S['goals'].items():
        t = clk.wall(i['t'])
        p = i.get('pos')
        best = None
        for arm, o in opens.items():
            j = bisect.bisect_right(o, t + 2) - 1
            if j < 0 or o[j] < t - 180:
                continue
            mv = moves.get(arm) or []
            k = bisect.bisect_right([m[0] for m in mv], o[j]) - 1
            dist = math.hypot(mv[k][1][0] - p[0], mv[k][1][1] - p[1]) if k >= 0 and p else 9.0
            sc = (round(dist, 2) if dist > 0.12 else 0, t - o[j])
            if best is None or sc < best[0]:
                best = (sc, arm)
        out[g] = (t, best[1] if best else None, i['item'])
    return out


def transport_atomic(d, clk):
    """Transport steps: each handoff plus each goal's first delivery.

    A handoff is a completed release followed, within `HANDOFF_RADIUS_M`, by a completed grasp
    from a different arm; it is credited to the releasing arm. A delivery is credited as in
    version 1 (`goal_arms`). Each arm's failures go to its next step; goal regressions and lost
    items go to the goal's delivery step. In-place regrasps are not steps.
    """
    S = d['suite']
    A = [x for x in d['actions'] if x['s'] and x['e']]
    done = M.until(clk.wall(S['done_at']) if S.get('done_at') is not None else None, d)
    GA = goal_arms(S, A, clk)
    last = {}
    hold = {}
    grasps = []
    rels = []
    for x in sorted(A, key=lambda x: x['e']):
        if done and x['e'] > done:
            continue
        arm = x['arm']
        if x['type'] == 'move' and x['status'] == 'completed' and x.get('target'):
            last[arm] = x['target']
        if x['type'] == 'gripper' and x['status'] == 'completed':
            p = last.get(arm)
            if x.get('mode') == 'grasp':
                hold[arm] = True
                grasps.append((x['e'], arm, p))
            elif hold.pop(arm, None):
                rels.append((x['e'], arm, p))
    # The release that delivered a goal: the credited arm's last release up to the goal time + 2 s.
    deliveries = []
    for g, (t, arm, item) in GA.items():
        cand = [r for r in rels if r[1] == arm and r[0] <= t + 2]
        rt = cand[-1][0] if cand and cand[-1][0] >= t - 180 else None
        deliveries.append(dict(t=t, arm=arm, goal=g, item=item, rel=rt, failed=set()))
    used = {(x['arm'], x['rel']) for x in deliveries if x['rel'] is not None}
    steps = list(deliveries)
    for t, arm, p in rels:
        if (arm, t) in used or not p:
            continue
        nxt = [
            g for g in grasps if g[0] > t and g[2] and math.dist(g[2][:2], p[:2]) < HANDOFF_RADIUS_M
        ]
        if nxt and nxt[0][1] != arm:
            steps.append(dict(t=t, arm=arm, goal=None, item=None, rel=t, failed=set()))
    steps.sort(key=lambda s: s['t'])
    byarm = collections.defaultdict(list)
    for s in steps:
        byarm[s['arm']].append(s)
    extra = collections.defaultdict(set)
    for f in M.failures(A, done):
        L = byarm.get(f['arm'], [])
        j = bisect.bisect_left([s['t'] for s in L], f['t'])
        if j < len(L):
            L[j]['failed'].add(f['kind'])
        else:
            extra['arm:' + str(f['arm'])].add(f['kind'])
    byg = {s['goal']: s for s in deliveries}
    ev = collections.defaultdict(list)
    for t, g, i in S['regress']:
        ev[g].append(('lost', t))
    for g, i in S['goals'].items():
        ev[g].append(('got', i['t']))
        for t, _ in i.get('swaps', []):
            ev[g].append(('got', t))
    for g, e in ev.items():
        e.sort(key=lambda x: x[1])
        for n, (k, t) in enumerate(e):
            if k != 'lost' or (done and clk.wall(t) > done):
                continue
            nxt = next((x[1] for x in e[n + 1 :] if x[0] == 'got'), S['last_sim'])
            if nxt - t >= M.REGRESS_MIN_S and g in byg:
                byg[g]['failed'].add('object')
    item_goal = {v[2]: g for g, v in GA.items()}
    for i in S['lost'] or ():  # None: unknown from this log (see extract.suite)
        if i in item_goal:
            byg[item_goal[i]]['failed'].add('object')
        else:
            extra['item:' + str(i)].add('object')
    r = result(steps, extra, 0)
    r['handoffs'] = len(steps) - len(deliveries)
    r['objects_unknown'] = S.get('objects_unknown')
    return r


def relay_atomic(d, clk):
    S = d['suite']
    A = [x for x in d['actions'] if x['s'] and x['e']]
    done = M.until(clk.wall(S['done_at']) if S.get('done_at') is not None else None, d)
    recs = []
    steps = []
    for p, hs in S['handovers'].items():
        for h in hs:
            snd = set(h.get('senders') or [])
            rcv = list(h.get('receivers') or [])
            recs.append(
                dict(
                    p=p,
                    t=clk.wall(h['t']),
                    arms=snd | set(rcv),
                    joined=[a for a in rcv if a not in snd],
                )
            )
    recs.sort(key=lambda r: r['t'])
    for r in recs:
        r['steps'] = [dict(p=r['p'], t=r['t'], arm=a, failed=set()) for a in r['joined']]
        steps += r['steps']
    extra = collections.defaultdict(set)
    cust = S['custody']

    def owner(arm, t):
        best = None
        for p, c in cust.items():
            for tt, arms in c:
                w = clk.wall(tt)
                if arm in arms and w <= t and (best is None or w > best[0]):
                    best = (w, p)
        return best[1] if best else 'arm:' + str(arm)

    for f in M.failures(A, done):
        c = [r for r in recs if r['steps'] and f['arm'] in r['arms'] and r['t'] >= f['t']]
        if c:
            r = min(c, key=lambda r: r['t'])
            own = [s for s in r['steps'] if s['arm'] == f['arm']]
            (own[0] if own else r['steps'][0])['failed'].add(f['kind'])
            continue
        p = owner(f['arm'], f['t'])
        on = [s for s in steps if s['p'] == p]
        if on:
            on[-1]['failed'].add(f['kind'])
        elif p.startswith('arm:'):
            later = [s for s in steps if s['t'] >= f['t']]
            if later:
                later[0]['failed'].add(f['kind'])
            else:
                extra['unassigned'].add(f['kind'])
        else:
            extra[p].add(f['kind'])
    for t, p, n in S['drops']:
        w = clk.wall(t)
        c = [s for s in steps if s['p'] == p and s['t'] >= w]
        on = [s for s in steps if s['p'] == p]
        if c:
            min(c, key=lambda s: s['t'])['failed'].add('object')
        elif on:
            on[-1]['failed'].add('object')
        else:
            extra[p].add('object')
    return result(steps, extra, 0)


def dial_atomic(d, clk, turns):
    """turns: [[sim_s, dial_index], ...] from dial_steps.json."""
    S = d['suite']
    A = [x for x in d['actions'] if x['s'] and x['e']]
    done = M.until(clk.wall(S['solved_at']) if S.get('solved_at') is not None else None, d)
    steps = sorted(
        [dict(t=clk.wall(t), dial=k, failed=set()) for t, k in turns], key=lambda s: s['t']
    )
    if done:
        steps = [s for s in steps if s['t'] <= done + 1e-6]
    ts = [s['t'] for s in steps]
    extra = collections.defaultdict(set)
    ev = [(f['t'], f['kind']) for f in M.failures(A, done)]
    for k, t, key in S['viol']:
        if k and 'support' in k and t is not None:
            w = clk.wall(t)
            if not done or w <= done:
                ev.append((w, 'object'))
    for t, k in ev:
        j = bisect.bisect_left(ts, t)
        if j < len(steps):
            steps[j]['failed'].add(k)
        else:
            extra['leftover'].add(k)
    return result(steps, extra, 0)


def compute(d, v1_atomic=None, turns=None):
    """Version 2 atomic counts for an extracted record, or None without evaluator or clock data.

    Mosaic reuses `v1_atomic` (or recomputes it); Dial needs `turns` from `run_dial_turns`."""
    S = d.get('suite')
    clk = M.Clock(d)
    if not (S and S.get('lines') and clk.ok):
        return None
    fam = d['sel']['family']
    if fam == 'mosaic':
        a = v1_atomic or M.goals_atomic(d, clk)
        return {
            k: a[k]
            for k in (
                'atomic_total',
                'atomic_failed',
                'atomic_failed_object',
                'delivered',
                'trailing',
            )
        }
    if fam == 'transport':
        return transport_atomic(d, clk)
    if fam == 'relay':
        return relay_atomic(d, clk)
    if fam == 'dial':
        T = turn_list(turns)
        return None if T is None else dial_atomic(d, clk, T)
    return None
