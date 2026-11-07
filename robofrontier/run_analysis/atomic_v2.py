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

from . import metrics as M

DIAL_MARK_DEG = 60.0
DIAL_BAND_DEG = 4.0
DIAL_DWELL_S = 1.0
HANDOFF_RADIUS_M = 0.08
SUITE_LOGS = ('private/outputs/suite-process.jsonl', 'outputs/suite-process.jsonl')


def dial_turns(lines, dwell_s=DIAL_DWELL_S):
    """[[sim_s, dial], ...] for each dial settling at a new mark, from suite-process lines."""
    cur = settled = done = None
    steps = []
    for line in lines:
        if '"private_angles_deg"' not in line:
            continue
        try:
            x = json.loads(line)
        except ValueError:
            continue
        res = x.get('result') or {}
        A = res.get('private_angles_deg')
        t = res.get('sim_time_s')
        if A is None or t is None:
            continue
        if cur is None:
            cur = [(None, t)] * len(A)
            settled = [None] * len(A)
            done = [False] * len(A)
        for k, a in enumerate(A):
            q = round(a / DIAL_MARK_DEG)
            b = q if abs(a - DIAL_MARK_DEG * q) <= DIAL_BAND_DEG else None
            if b != cur[k][0]:
                cur[k] = (b, t)
                done[k] = False
            elif b is not None and not done[k] and t - cur[k][1] >= dwell_s:
                done[k] = True
                if settled[k] is not None and b != settled[k]:
                    steps.append([cur[k][1], k])
                settled[k] = b
    return steps


def run_dial_turns(run, dwell_s=DIAL_DWELL_S):
    """Dial turns of an `archive.Run`, or None when it has no evaluator log."""
    n = next((f for f in SUITE_LOGS if f in run.files), None)
    return dial_turns(run.lines(n), dwell_s) if n else None


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
    done = clk.wall(S['done_at']) if S.get('done_at') is not None else None
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
    for i in S['lost']:
        if i in item_goal:
            byg[item_goal[i]]['failed'].add('object')
        else:
            extra['item:' + str(i)].add('object')
    r = result(steps, extra, 0)
    r['handoffs'] = len(steps) - len(deliveries)
    return r


def relay_atomic(d, clk):
    S = d['suite']
    A = [x for x in d['actions'] if x['s'] and x['e']]
    done = clk.wall(S['done_at']) if S.get('done_at') is not None else None
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
    done = clk.wall(S['solved_at']) if S.get('solved_at') is not None else None
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
        return None if turns is None else dial_atomic(d, clk, turns)
    return None
