"""Per-run metrics from one extracted JSON. Definitions follow the paper; every rule is stated here."""

import bisect, collections, math
import numpy as np

# Agent choices and host events are not task failures.
EXCLUDE_REASON = (
    'stopped_by_agent',
    'withdrawn_by_participant',
    'Interrupted',
    'Engineering inputs changed',
    'Execution owner ended',
    'Stop did not settle',
)
REGRESS_MIN_S = 5.0  # a goal lost for less than this is evaluator flicker, not a misplaced item
OBJECT_REASON = ('grasp', 'opening')


def merge(x):
    out = []
    for a, b in sorted(x):
        if b <= a:
            continue
        if out and a <= out[-1][1]:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def total(x):
    return sum(b - a for a, b in x)


def clip(x, off):
    out = []
    for a, b in x:
        parts = [(a, b)]
        for lo, hi in off:
            new = []
            for s, e in parts:
                if hi <= s or lo >= e:
                    new.append((s, e))
                    continue
                if s < lo:
                    new.append((s, lo))
                if hi < e:
                    new.append((hi, e))
            parts = new
        out += parts
    return out


def fast_clip(u, off):
    """Both lists sorted and disjoint."""
    out = []
    j = 0
    for a, b in u:
        cur = a
        while j < len(off) and off[j][1] <= cur:
            j += 1
        k = j
        while k < len(off) and off[k][0] < b:
            if off[k][0] > cur:
                out.append([cur, off[k][0]])
            cur = max(cur, off[k][1])
            k += 1
        if cur < b:
            out.append([cur, b])
    return out


def intersect(x, y):
    out = []
    i = j = 0
    while i < len(x) and j < len(y):
        a = max(x[i][0], y[j][0])
        b = min(x[i][1], y[j][1])
        if b > a:
            out.append([a, b])
        if x[i][1] < y[j][1]:
            i += 1
        else:
            j += 1
    return out


def host_model_spans(H):
    """Turn time minus robot-tool time per actor. Non-robot tools stay inside; used only without transcripts."""
    by = collections.defaultdict(list)
    for a, s, e in H.get('tools') or []:
        by[a].append([s, e])
    out = []
    for a, s, e in H.get('turns') or []:
        t = merge(by.get(a, []))
        out += fast_clip([[s, e]], t)
    return merge(out)


def cutoff_unix(d):
    """Wall time at which the trial was scored (24 h rule), or None."""
    c = d.get('cutoff') or {}
    return c.get('unix')


def until(t, d):
    """The earlier of `t` and the trial cutoff; either may be None."""
    c = cutoff_unix(d)
    return c if t is None else t if c is None else min(t, c)


def upto(x, end):
    """Intervals clipped to end at `end`."""
    return [[a, min(b, end)] for a, b in x if a < end]


def timing(d):
    H = d.get('host') or {}
    M = d.get('meta') or {}
    A = [x for x in (d.get('actions') or []) if x['s'] and x['e']]
    first = M.get('first') or H.get('first')
    last = M.get('last') or H.get('last')
    if H.get('last') and last:
        last = max(last, H['last'])
    if first is None:
        return None
    last = until(last, d)
    rt = d.get('runtime.json') or {}
    segs = rt.get('segments') or []
    downs = []
    for x, y in zip(segs, segs[1:]):
        if x.get('ended_at') and y.get('started_at'):
            downs.append([float(x['ended_at']), float(y['started_at'])])
    spans = d.get('spans') or []
    src = d.get('span_src')
    if spans:
        model = merge([[a, b] for _, a, b in spans])
    elif H.get('turns'):
        model = host_model_spans(H)
        src = 'host-turns'
    else:
        model = []
        src = None
    model = upto(model, last)
    act = upto(merge([[x['s'], x['e']] for x in A]), last)
    turns = upto(merge([[a, b] for _, a, b in (H.get('turns') or [])]), last)
    tools = upto(merge([[a, b] for _, a, b in (H.get('tools') or [])]), last)
    downs = upto(downs, last)
    busy = merge(model + act + tools + turns + downs)
    gaps = []
    cur = first
    for a, b in busy:
        if a - cur >= 60:
            gaps.append([cur, a])
        cur = max(cur, b)
    if last - cur >= 60:
        gaps.append([cur, last])
    cyc = {int(k): v for k, v in (H.get('cycles') or {}).items()}
    errs = sorted(H.get('errors') or [])
    lim = [t for t, k in errs if k in ('usage_limit', 'rate_limit')]
    stops = []
    limits = []
    other = []
    # Only Codex hosts log liveness cycles; without them a quiet gap of 5 min or more is
    # taken as a host stop, so the two engines' active times are not measured alike.
    stop_src = 'cycles' if cyc else 'gap>=300s'
    for a, b in gaps:
        if cyc:
            n = sum(v for k, v in cyc.items() if a // 60 <= k <= b // 60)
            stopped = n < (b - a) / 60
        else:
            stopped = (b - a) >= 300
        if stopped:
            stops.append([a, b])
        elif bisect.bisect_right(lim, b) - bisect.bisect_left(lim, a - 300) > 0:
            limits.append([a, b])
        else:
            other.append([a, b])
    off = merge(downs + stops + limits)
    clock = last - first
    m2 = fast_clip(model, off)
    a2 = fast_clip(act, off)
    both = intersect(m2, a2)
    union = merge(m2 + a2)
    return dict(
        first=first,
        last=last,
        clock_h=clock / 3600,
        active_h=(clock - total(off)) / 3600,
        interrupt_h=total(off) / 3600,
        recorded_h=total(downs) / 3600,
        stops_h=total(stops) / 3600,
        limit_h=total(limits) / 3600,
        think_h=total(m2) / 3600 if model else None,
        action_h=total(a2) / 3600 if A else None,
        both_h=total(both) / 3600 if model and A else None,
        idle_h=(clock - total(off) - total(union)) / 3600 if model and A else None,
        think_src=src,
        stop_src=stop_src,
        cutoff=cutoff_unix(d),
        other_stall_h=total(other) / 3600,
        off=off,
        host_think_h=total(fast_clip(upto(host_model_spans(H), last), off)) / 3600
        if H.get('turns')
        else None,
    )


class Clock:
    def __init__(self, d):
        A = [
            x
            for x in (d.get('actions') or [])
            if x['s'] and x['e'] and x['ss'] is not None and x['es'] is not None
        ]
        P = sorted([(x['s'], x['ss']) for x in A] + [(x['e'], x['es']) for x in A])
        # Sim time keeps running after the last action, so anchor the end of the run too.
        S = d.get('suite') or {}
        H = d.get('host') or {}
        M = d.get('meta') or {}
        end = max([v for v in (H.get('last'), M.get('last')) if v] or [0])
        if P and S.get('last_sim') is not None and end > P[-1][0] and S['last_sim'] > P[-1][1]:
            P.append((end, S['last_sim']))
        w = []
        s = []
        mx = -1e18
        for a, b in P:
            if b >= mx:
                w.append(a)
                s.append(b)
                mx = b
        self.w = np.array(w)
        self.s = np.array(s)
        self.ok = len(w) > 1

    def wall(self, sim):
        return float(np.interp(sim, self.s, self.w)) if self.ok else None


def failures(A, ignore_after=None):
    out = []
    for x in A:
        if x['status'] not in ('failed', 'uncertain'):
            continue
        r = str(x.get('reason') or '')
        if any(k in r for k in EXCLUDE_REASON):
            continue
        if x['e'] is None:
            continue
        if ignore_after and x['e'] > ignore_after:
            continue
        kind = (
            'object'
            if x['type'] == 'gripper' and any(w in r for w in ('rasp', 'opening', 'aperture'))
            else 'other'
        )
        out.append(dict(t=x['e'], arm=x['arm'], kind=kind, reason=r[:50]))
    return sorted(out, key=lambda f: f['t'])


def goals_atomic(d, clk):
    S = d['suite']
    A = [x for x in d['actions'] if x['s'] and x['e']]
    goals = S['goals']
    done = until(clk.wall(S['done_at']) if S.get('done_at') is not None else None, d)
    opens = collections.defaultdict(list)
    moves = collections.defaultdict(list)
    for x in sorted(A, key=lambda x: x['s']):
        if x['type'] == 'gripper' and x['status'] == 'completed' and x.get('mode') != 'grasp':
            opens[x['arm']].append(x['e'])
        if x['type'] == 'move' and x.get('target'):
            moves[x['arm']].append((x['e'], x['target']))
    steps = []
    for g, i in goals.items():
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
                best = (sc, arm, dist)
        arm = best[1] if best else (i['item'].split('_')[0] if '_' in i['item'] else None)
        steps.append(
            dict(
                goal=g,
                item=i['item'],
                t=t,
                arm=arm,
                dist=best[2] if best else None,
                sim=i['t'],
                failed=set(),
            )
        )
    steps.sort(key=lambda s: s['t'])
    byarm = collections.defaultdict(list)
    for s in steps:
        byarm[s['arm']].append(s)
    F = failures(A, done)
    trail = collections.defaultdict(set)
    for f in F:
        L = byarm.get(f['arm'], [])
        ts = [s['t'] for s in L]
        j = bisect.bisect_left(ts, f['t'])
        if j < len(L):
            L[j]['failed'].add(f['kind'])
        else:
            trail[f['arm']].add(f['kind'])
    # A goal lost for at least REGRESS_MIN_S counts against that goal.
    byg = {s['goal']: s for s in steps}
    reg = 0
    ev = collections.defaultdict(list)
    for t, g, i in S['regress']:
        ev[g].append(('lost', t))
    for g, i in goals.items():
        ev[g].append(('got', i['t']))
        for t, _ in i.get('swaps', []):
            ev[g].append(('got', t))
    for g, e in ev.items():
        e.sort(key=lambda x: x[1])
        for n, (k, t) in enumerate(e):
            if k != 'lost':
                continue
            if done and clk.wall(t) > done:
                continue
            nxt = next((x[1] for x in e[n + 1 :] if x[0] == 'got'), S['last_sim'])
            if nxt - t >= REGRESS_MIN_S:
                byg[g]['failed'].add('object')
                reg += 1
    # None: the process log cannot show lost items (see extract.suite); counted as unknown.
    lost = None if S['lost'] is None else [i for i, t in S['lost'].items()]
    unknown = lost is None
    lost = lost or []
    delivered_items = {s['item'] for s in steps}
    lost_extra = [i for i in lost if i not in delivered_items]
    for s in steps:
        if s['item'] in lost:
            s['failed'].add('object')
    N = len(steps) + len(trail) + len(lost_extra)
    f_all = sum(bool(s['failed']) for s in steps) + len(trail) + len(lost_extra)
    f_obj = (
        sum('object' in s['failed'] for s in steps)
        + sum('object' in v for v in trail.values())
        + len(lost_extra)
    )
    amb = sum(1 for s in steps if s['dist'] is None or s['dist'] > 0.12)
    return dict(
        atomic_total=N,
        atomic_failed=f_all,
        atomic_failed_object=f_obj,
        delivered=len(steps),
        trailing=len(trail),
        regressions=reg,
        lost=None if unknown else len(lost),
        objects_unknown=S.get('objects_unknown'),
        attrib_far=amb,
        failed_actions=len(F),
        timeline=[[s['t'], bool(s['failed'])] for s in steps],
    )


def relay_atomic(d, clk):
    S = d['suite']
    A = [x for x in d['actions'] if x['s'] and x['e']]
    steps = []
    done = until(clk.wall(S['done_at']) if S.get('done_at') is not None else None, d)
    for p, hs in S['handovers'].items():
        for h in hs:
            steps.append(
                dict(
                    p=p,
                    t=clk.wall(h['t']),
                    arms=set((h.get('senders') or []) + (h.get('receivers') or [])),
                    failed=set(),
                    protocol=h.get('protocol'),
                )
            )
    steps.sort(key=lambda s: s['t'])
    F = failures(A, done)
    units = collections.defaultdict(set)
    cust = S['custody']

    def owner(arm, t):
        best = None
        for p, c in cust.items():
            for tt, arms in c:
                w = clk.wall(tt)
                if arm in arms and w <= t and (best is None or w > best[0]):
                    best = (w, p)
        return best[1] if best else 'arm:' + str(arm)

    for f in F:
        c = [s for s in steps if f['arm'] in s['arms'] and s['t'] >= f['t']]
        if c:
            min(c, key=lambda s: s['t'])['failed'].add(f['kind'])
        else:
            p = owner(f['arm'], f['t'])
            done_on = [s for s in steps if s['p'] == p]
            if done_on:
                done_on[-1]['failed'].add(
                    f['kind']
                )  # carrying to the goal belongs to the last transfer
            elif p.startswith('arm:'):
                later = [s for s in steps if s['t'] >= f['t']]
                if later:
                    later[0]['failed'].add(f['kind'])
                else:
                    units['unassigned'].add(f['kind'])
            else:
                units[p].add(f['kind'])
    for t, p, n in S['drops']:
        w = clk.wall(t)
        c = [s for s in steps if s['p'] == p and s['t'] >= w]
        on = [s for s in steps if s['p'] == p]
        if c:
            min(c, key=lambda s: s['t'])['failed'].add('object')
        elif on:
            on[-1]['failed'].add('object')
        else:
            units[p].add('object')
    N = len(steps) + len(units)
    f_all = sum(bool(s['failed']) for s in steps) + len(units)
    f_obj = sum('object' in s['failed'] for s in steps) + sum('object' in v for v in units.values())
    return dict(
        atomic_total=N,
        atomic_failed=f_all,
        atomic_failed_object=f_obj,
        delivered=len(steps),
        trailing=len(units),
        drops=sum(n for _, _, n in S['drops']),
        failed_actions=len(F),
        protocols=sorted({str(s['protocol']) for s in steps}),
        timeline=[[s['t'], bool(s['failed'])] for s in steps],
    )


def dial_atomic(d, clk):
    S = d['suite']
    A = [x for x in d['actions'] if x['s'] and x['e']]
    T = []
    last = 0
    for t, v in S['trials']:
        v = v or 0
        for _ in range(int(v - last)):
            T.append(dict(t=clk.wall(t), failed=set()))
        last = max(last, v)
    done = until(clk.wall(S['solved_at']) if S.get('solved_at') is not None else None, d)
    F = failures(A, done)
    ts = [s['t'] for s in T]
    trail = set()
    PHYS = ('support',)
    ev = [(f['t'], f['kind']) for f in F]
    for k, t, key in S['viol']:
        if k and any(w in k for w in PHYS) and t is not None:
            w = clk.wall(t)
            if not done or w <= done:
                ev.append((w, 'object'))
    for t, k in ev:
        j = bisect.bisect_left(ts, t)
        if j < len(T):
            T[j]['failed'].add(k)
        else:
            trail.add(k)
    N = len(T) + bool(trail)
    f_all = sum(bool(s['failed']) for s in T) + bool(trail)
    f_obj = sum('object' in s['failed'] for s in T) + ('object' in trail)
    return dict(
        atomic_total=N,
        atomic_failed=f_all,
        atomic_failed_object=f_obj,
        delivered=len(T),
        trailing=int(bool(trail)),
        failed_actions=len(F),
        support_violations=sum(1 for k, _, _ in S['viol'] if k and 'support' in k),
        timeline=[[s['t'], bool(s['failed'])] for s in T],
    )


def outcome(d):
    """Final state under the paper's rule. Relay requires a qualified handover for every timber."""
    s = d['sel']
    S = d.get('suite')
    fam = s['family']
    if not S or not S.get('lines'):
        return None
    L = S['last']
    # Scored at the trial cutoff when the run reached it: its evaluation, else the last row
    # before it (extract.suite already dropped later rows).
    E = (d.get('cutoff') or {}).get('evaluation')
    if fam == 'relay':
        fp = (E.get('payloads') if E else None) or S.get('final_payloads') or {}
        tot = (E or {}).get('total_payloads') or S.get('total') or len(fp)
        ok = [p for p, x in fp.items() if x.get('terminal') and (x.get('nh') or S['handovers'].get(p))]
        return dict(
            success=len(ok) == tot and tot > 0,
            done=len(ok),
            total=tot,
            label=f'{len(ok)}/{tot}',
            handover_timbers=sum(1 for p in fp if S['handovers'].get(p)),
            evaluator_completed=(E or L).get('completed_payloads'),
        )
    if fam == 'dial':
        solved = S.get('solved_at') is not None or bool(E and E.get('solved'))
        tr = S.get('valid_trials')
        tr = (L.get('valid_trials') or 0) if tr is None else tr
        disp = max([v or 0 for _, v in S['disp']] or [0])
        return dict(success=solved, done=disp, total=None, label=f'best {disp}', trials=tr)
    L = E or L
    m = L.get('matched_goals') or 0
    tot = L.get('total_goals') or S.get('total') or 0
    return dict(
        success=bool(L.get('all_goals_met') or (tot and m == tot)),
        done=m,
        total=tot,
        label=f'{m}/{tot}',
    )


def excluded(d):
    """Why a run's result is not counted, or None.

    wall_backstop: the 48 h wall backstop stopped it before its 24 h active-time cutoff
    (policy_probe.BudgetGuard); it needs review, whatever its outcome."""
    if (d.get('cutoff') or {}).get('wall_backstop') or (d.get('evaluation.json') or {}).get('wall_backstop') is True:
        return 'wall_backstop'
    return None


def compute(d):
    s = d['sel']
    T = timing(d)
    O = dict(
        id=s['id'],
        cutoff=d.get('cutoff'),
        model=s.get('model'),
        case=s.get('case'),
        level=s.get('level'),
        family=s['family'],
        batch=s.get('batch'),
        mode=s.get('mode'),
        use=s.get('use'),
        alternatives=s.get('alternatives'),
        kind=d['kind'],
        meta=d.get('meta'),
        timing=T,
        outcome=outcome(d),
        excluded=excluded(d),
    )
    O['needs_review'] = O['excluded'] is not None
    H = d.get('host')
    O['tokens'] = H['tok'] if H else None
    O['engine'] = H['engine'] if H else None
    O['messages'] = (d.get('meta') or {}).get('messages')
    S = d.get('suite')
    clk = Clock(d)
    O['has_suite'] = bool(S and S.get('lines'))
    O['has_actions'] = bool(d.get('actions'))
    O['clock_ok'] = clk.ok
    if O['has_suite'] and clk.ok:
        fam = s['family']
        O['atomic'] = (
            relay_atomic if fam == 'relay' else dial_atomic if fam == 'dial' else goals_atomic
        )(d, clk)
    A = d.get('actions') or []
    O['actions'] = len(A)
    O['failed_actions_all'] = sum(1 for x in A if x['status'] not in ('completed', None))
    O['reasons'] = collections.Counter(
        str(x.get('reason'))[:45] for x in A if x['status'] not in ('completed', None)
    ).most_common(8)
    return O
