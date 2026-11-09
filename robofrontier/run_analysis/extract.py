"""Extract one run's actions, evaluator timeline, tokens and activity spans into a compact JSON."""

import collections, contextlib, json, lzma, os, re, shutil, sqlite3, tempfile, datetime
from pathlib import Path

from . import motion as trial_motion
from .archive import Run


def num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


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


def epoch(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


@contextlib.contextmanager
def runtime_db(run):
    """The run's runtime database, copied out of the archive (with its WAL), or None."""
    names = [n for n in run.files if n.endswith('runtime.sqlite') and 'state/' in n] or [
        n for n in run.files if n.endswith('runtime.sqlite')
    ]
    if not names:
        yield None
        return
    n = names[0]
    T = tempfile.mkdtemp(prefix='rf-sq-', dir=os.environ.get('RF_TMP') or None)
    db = None
    try:
        p = Path(T) / 'r.sqlite'
        p.write_bytes(run.read(n))
        for suf in ('-wal', '-shm'):
            if run.has(n + suf):
                (Path(T) / ('r.sqlite' + suf)).write_bytes(run.read(n + suf))
        db = sqlite3.connect(str(p))
        yield db
    finally:
        if db is not None:
            db.close()
        shutil.rmtree(T, ignore_errors=True)


def tables(db):
    return {r[0] for r in db.execute("select name from sqlite_master where type='table'")}


CUTOFF_FILES = ('private/outputs/budget-cutoff.json', 'outputs/budget-cutoff.json')
_OPEN = object()


def compact_evaluation(ev):
    """Scalars of an evaluation, plus each Relay timber's terminal state and handover count."""
    out = {k: v for k, v in ev.items() if not isinstance(v, (dict, list))}
    if isinstance(ev.get('payloads'), dict):
        out['payloads'] = {
            p: dict(
                terminal=x.get('terminal_goal_met'),
                completed=x.get('completed'),
                nh=len(x.get('handovers') or []),
            )
            for p, x in ev['payloads'].items()
            if isinstance(x, dict)
        }
    return out


def trial_cutoff(run, db=_OPEN):
    """End of the trial under the 24 h rule, or None for a run that never reached it.

    The trial is scored at the wall-limit cutoff and nothing after it counts. The source is
    budget-cutoff.json (cutoff wall time, sim time and the evaluation at that moment); without
    it, the first POLICY_WALL_LIMIT event of the runtime database (no evaluation)."""
    n = run.find(*CUTOFF_FILES)
    if n:
        c = json.loads(run.read(n))
        unix, sim = num(c.get('cutoff_unix_s')), num(c.get('sim_time_s'))
        if unix is None:
            raise ValueError('budget-cutoff.json without cutoff_unix_s: ' + n)
        ev = c.get('evaluation')
        return dict(
            source='budget-cutoff.json',
            unix=unix,
            sim=sim,
            evaluation=compact_evaluation(ev) if isinstance(ev, dict) else None,
        )
    if db is _OPEN:
        with runtime_db(run) as opened:
            return trial_cutoff_event(opened)
    return trial_cutoff_event(db)


def trial_cutoff_event(db):
    if db is None or 'events' not in tables(db):
        return None
    row = db.execute(
        "select created, value from events where kind='POLICY_WALL_LIMIT' order by seq limit 1"
    ).fetchone()
    if not row:
        return None
    try:
        v = json.loads(row[1] or '{}')
    except ValueError:
        v = {}
    return dict(
        source='POLICY_WALL_LIMIT event',
        unix=float(row[0]),
        sim=num(v.get('sim_time_s')) if isinstance(v, dict) else None,
        evaluation=None,
    )


def actions(db, cutoff_unix=None):
    """Actions, run meta and message times; nothing that started after `cutoff_unix`."""
    if db is None:
        return None, None, None
    within = lambda t: cutoff_unix is None or t is None or t <= cutoff_unix
    A = []
    for actor, value in db.execute('select actor,value from actions'):
        v = json.loads(value)
        pm = v.get('parameters') or {}
        x = dict(
            actor=actor,
            arm=v.get('arm') or pm.get('robot'),
            type=v.get('type'),
            status=v.get('status'),
            reason=v.get('reason'),
            s=num(v.get('started_at')),
            e=num(v.get('finished_at')),
            ss=num(v.get('started_sim_s')),
            es=num(v.get('finished_sim_s')),
            target=pm.get('target_m'),
            mode=pm.get('mode'),
            width=pm.get('width_m'),
            batch=bool(v.get('batch_id')),
        )
        if within(x['s']):
            A.append(x)
    tabs = tables(db)
    msgT = [r[0] for r in db.execute('select created from messages')] if 'messages' in tabs else []
    msgT = [t for t in msgT if within(t)]
    ev = [r for r in db.execute('select created, kind from events')] if 'events' in tabs else []
    ev = [r for r in ev if r[0] is not None and within(r[0])]
    kinds = collections.Counter(k for _, k in ev)
    agents = db.execute('select count(*) from agents').fetchone()[0] if 'agents' in tabs else None
    return (
        A,
        dict(
            messages=len(msgT) if 'messages' in tabs else None,
            agents=agents,
            first=min((t for t, _ in ev), default=None),
            last=max((t for t, _ in ev), default=None),
            finish_proposed=kinds.get('TEAM_FINISH_PROPOSED', 0),
            delegations=kinds.get('DELEGATION_ACTIVATED', 0),
        ),
        msgT,
    )


SUITE_LOGS = (
    'private/outputs/suite-process.jsonl',
    'outputs/suite-process.jsonl',
    'suite-process.jsonl',
)
# Process-log formats whose rows are too sparse to recover object poses or dial turns:
# 'events-60s' writes poses only in the final row when the scene records motion.
LOW_RESOLUTION = ('events-60s',)
# Formats whose rows have object poses and dial angles only every 10 s (and at events):
# the motion recording is preferred, and without one the log still serves, at that sampling.
COARSE = ('events-10s',)
# Where object poses and dial angles come from: 'always' (the default) reads the 30 Hz motion
# recording of every run that has one, so every run is counted the same way; 'sparse' reads it
# only for runs whose process log is low resolution or coarse. They differ on events-1s logs
# only by the log's 1 s sampling (a few Dial turns; lost items agree).
MOTION_MODES = ('sparse', 'always')


def use_motion(formats, mode):
    if mode not in MOTION_MODES:
        raise ValueError('motion mode must be one of %s, not %r' % (MOTION_MODES, mode))
    return mode == 'always' or any(f in LOW_RESOLUTION + COARSE for f in formats)


def is_header(line):
    return '"result"' not in line[:200] and '"schema"' in line[:60]


def row_sim(d):
    """Sim time of an evaluator row, or None for anything else."""
    if not isinstance(d, dict) or not isinstance(d.get('result'), dict):
        return None
    t = num(d.get('sim_time_s'))
    return t if t is not None else num(d['result'].get('sim_time_s'))


def log_blocks(run, n):
    """One entry per block of the process log (each world process starts one with a header):
    its format and its first row's sim time (None for a block without rows)."""
    blocks = [dict(format=None, first=None, header=False)]
    for line in run.lines(n):
        if is_header(line):
            try:
                h = json.loads(line)
            except ValueError:
                h = {}
            blocks.append(dict(format=h.get('format'), first=None, header=True))
        elif blocks[-1]['first'] is None:
            try:
                blocks[-1]['first'] = row_sim(json.loads(line))
            except ValueError:
                pass
    return blocks


def trial_rows(run, n, cutoff_sim=None, blocks=None):
    """(block, sim_s, row) for the evaluator rows that belong to the trial.

    A continued run's log has one block per segment. Each block keeps its rows up to the
    first sim time of the next block, whose world was restored from an earlier frame, so
    later rows were never physically kept (as run_segments.relay_record/dial_record). Rows
    after `cutoff_sim`, and so every block that starts after it, are not part of the trial."""
    blocks = log_blocks(run, n) if blocks is None else blocks
    ends = []
    for i in range(len(blocks)):
        nxt = next((b['first'] for b in blocks[i + 1 :] if b['first'] is not None), None)
        if cutoff_sim is not None:
            nxt = cutoff_sim if nxt is None else min(nxt, cutoff_sim)
        ends.append(nxt)
    i = 0
    for line in run.lines(n):
        if is_header(line):
            i += 1
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        t = row_sim(d)
        if t is None or (ends[i] is not None and t > ends[i] + 1e-9):
            continue
        yield i, t, d


def suite(run, cutoff_sim=None, motion='always'):
    """Evaluator timeline of the trial from the process log.

    Lost items and the position of each goal's item when first assigned come from the motion
    recording when `use_motion` says so and the run has one (`objects_source`); a sparse log
    without a recording leaves them unknown (None, with `objects_unknown`)."""
    n = run.find(*SUITE_LOGS)
    if not n:
        return None
    blocks = log_blocks(run, n)
    formats = sorted({b['format'] for b in blocks if b['format']})
    low = any(f in LOW_RESOLUTION for f in formats)
    want_motion = use_motion(formats, motion)
    S = dict(
        fam=None,
        total=None,
        last={},
        seen_items={},
        goals={},
        regress=[],
        match=[],
        handovers={},
        drops=[],
        comp=[],
        trials=[],
        disp=[],
        viol={},
        lost={},
        custody={},
        z0={},
        segments=sum(b['header'] for b in blocks),
        blocks=0,
        formats=formats,
        cutoff_sim=cutoff_sim,
        lines=0,
        first_sim=None,
        last_sim=None,
        solved_at=None,
        done_at=None,
        final_payloads=None,
        valid_trials=None,
    )
    pend = set()
    prev_assign = {}
    prev_drops = {}
    seen_h = set()
    prev_comp = None
    prev_tr = None
    prev_disp = None
    prev_m = None
    # Dial trials over segments: each block adds its own (valid_trials - carried_valid_trials).
    blk = None
    base = 0
    blk_v = blk_carry = None
    obj_rows = 0
    last_obj = False
    goal_rows = False
    for i, t, d in trial_rows(run, n, cutoff_sim, blocks):
        if i != blk:
            if blk_v is not None:
                base += blk_v - blk_carry
            blk, blk_v, blk_carry = i, None, 0
            S['blocks'] += 1
        r = d['result']
        S['lines'] += 1
        S['first_sim'] = t if S['first_sim'] is None else S['first_sim']
        S['last_sim'] = t
        scal = {k: v for k, v in r.items() if not isinstance(v, (dict, list))}
        S['last'] = scal
        if r.get('task_success') and S['done_at'] is None:
            S['done_at'] = t
        objs = d.get('objects') or {}
        obj_rows += bool(objs)
        last_obj = bool(objs)
        if objs and pend:
            for g in list(pend):
                x = S['goals'].get(g)
                if x and x.get('pos') is None:
                    x['pos'] = (objs.get(x['item']) or {}).get('position_m')
                pend.discard(g)
        if 'assignments' in r:
            goal_rows = True
            a = r['assignments'] or {}
            m = num(r.get('matched_goals'))
            S['total'] = r.get('total_goals', S['total'])
            if a != prev_assign:
                for g, it in a.items():
                    if prev_assign.get(g) != it:
                        p = (objs.get(it) or {}).get('position_m')
                        if g not in S['goals']:
                            S['goals'][g] = dict(t=t, item=it, pos=p)
                            if p is None:
                                pend.add(g)
                        else:
                            S['goals'][g].setdefault('swaps', []).append([t, it])
                for g, it in prev_assign.items():
                    if g not in a:
                        S['regress'].append([t, g, it])
                prev_assign = dict(a)
            if m is not None and m != prev_m:
                S['match'].append([t, m])
                prev_m = m
            for it, o in objs.items():
                z = (o.get('position_m') or [0, 0, 0])[2]
                if it not in S['z0']:
                    S['z0'][it] = z
                elif z < S['z0'][it] - 0.2 and it not in S['lost']:
                    S['lost'][it] = t
        if 'payloads' in r:
            S['total'] = r.get('total_payloads', S['total'])
            fin = {}
            for p, x in (r['payloads'] or {}).items():
                for h in x.get('handovers') or []:
                    key = (p, round(num(h.get('sim_time_s')) or 0, 3))
                    if key not in seen_h:
                        seen_h.add(key)
                        S['handovers'].setdefault(p, []).append(
                            dict(
                                t=num(h.get('sim_time_s')),
                                senders=h.get('senders'),
                                receivers=h.get('receivers'),
                                protocol=h.get('protocol'),
                            )
                        )
                dr = x.get('drops') or 0
                if dr > prev_drops.get(p, 0):
                    S['drops'].append([t, p, dr - prev_drops.get(p, 0)])
                prev_drops[p] = dr
                c = S['custody'].setdefault(p, [])
                now = sorted(set((x.get('custody') or []) + (x.get('support') or [])))
                if now and (not c or c[-1][1] != now):
                    c.append([t, now])
                fin[p] = dict(
                    completed=x.get('completed'),
                    terminal=x.get('terminal_goal_met'),
                    airborne=x.get('airborne'),
                    nh=len(x.get('handovers') or []),
                    spill=x.get('spill'),
                    inside=x.get('timber_inside_fraction'),
                )
            S['final_payloads'] = fin
            c = num(r.get('completed_payloads'))
            if c != prev_comp:
                S['comp'].append([t, c, num(r.get('terminal_completed_payloads'))])
                prev_comp = c
        if 'valid_trials' in r:
            v = num(r.get('valid_trials'))
            if v is not None:
                blk_v, blk_carry = v, num(r.get('carried_valid_trials')) or 0
                v = base + v - blk_carry
                S['valid_trials'] = v
            if v != prev_tr:
                S['trials'].append([t, v])
                prev_tr = v
            dp = num(r.get('display'))
            if dp != prev_disp:
                S['disp'].append([t, dp])
                prev_disp = dp
            if r.get('solved') and S['solved_at'] is None:
                S['solved_at'] = t
        for v in r.get('violations') or []:
            k = (v.get('kind'), round(num(v.get('sim_time_s')) or 0, 3), v.get('key'))
            S['viol'][str(k)] = [v.get('kind'), num(v.get('sim_time_s')), v.get('key')]
    S['viol'] = list(S['viol'].values())
    S['goals_final'] = prev_assign
    S.pop('z0', None)
    S['object_rows'] = obj_rows
    S['objects_source'] = 'process log' if goal_rows else None
    if not goal_rows:
        return S
    rec = trial_motion.find(run, n, cutoff_sim) if want_motion else None
    if rec is not None:
        S['objects_source'] = 'motion'
        S['lost'] = trial_motion.lost_items(rec, [o['id'] for o in rec.task['objects']])
        pos = trial_motion.positions_at(rec, [(g, x['item'], x['t']) for g, x in S['goals'].items()])
        for g, x in S['goals'].items():
            x['pos'] = pos[g]
    elif low and obj_rows - last_obj <= 0:
        # Object poses only in the final row and no recording: lost items and the positions
        # of delivered goals are unknown, not zero.
        S['objects_source'] = None
        S['objects_unknown'] = (
            'process log %s has no object poses before its final row and the run has no motion recording'
            % '/'.join(formats)
        )
        S['lost'] = None
        for g in S['goals'].values():
            g['pos'] = None
    return S


TOK = lambda: dict(input=0, cached=0, write=0, output=0)


CLOSERS = ('cli_turn_completed', 'turn/completed', 'robot_tool_completed', 'robot_tool_failed')


def host(run, cutoff_unix=None):
    """Tokens, turns, tool spans, liveness cycles and errors from the host log.

    Nothing after `cutoff_unix` counts: later events are dropped, except that a turn or
    tool call open at the cutoff is kept up to it (its tokens, reported later, are not)."""
    n = run.find(
        'private/logs/host.jsonl',
        'logs/host.jsonl',
        'private/outputs/codex-host.jsonl',
        'outputs/codex-host.jsonl',
        'codex-host.jsonl',
        'host.jsonl',
    )
    if not n:
        return None
    H = dict(
        path=n,
        engine=None,
        first=None,
        last=None,
        tok=TOK(),
        bucket={},
        turns=[],
        tools=[],
        errors=[],
        cycles={},
        gapmark=[],
        rows=0,
        unfinished=0,
        reported_until={},
        session_actor={},
    )
    prev = {}
    sess = {}
    seen = set()
    started = {}
    opent = {}
    ct = {}
    lastat = None
    gaps = []

    def add(at, i, c, w, o):
        T = H['tok']
        T['input'] += i
        T['cached'] += c
        T['write'] += w
        T['output'] += o
        b = int(at // 60)
        x = H['bucket'].setdefault(b, [0, 0, 0, 0])
        x[0] += i
        x[1] += c
        x[2] += w
        x[3] += o

    for line in run.lines(n):
        try:
            e = json.loads(line)
        except ValueError:
            continue
        if not isinstance(e, dict):
            continue
        at = num(e.get('at'))
        ev = e.get('event')
        if at is None:
            continue
        late = cutoff_unix is not None and at > cutoff_unix
        if late and ev not in CLOSERS:
            continue
        end = cutoff_unix if late else at
        if not late:
            H['first'] = at if H['first'] is None else min(H['first'], at)
            H['last'] = at if H['last'] is None else max(H['last'], at)
            if lastat is not None and at - lastat >= 60:
                gaps.append([lastat, at])
            lastat = at if lastat is None else max(lastat, at)
        if ev == 'cycle':
            b = int(at // 60)
            H['cycles'][b] = H['cycles'].get(b, 0) + 1
            continue
        if ev == 'thread/tokenUsage/updated':
            H['engine'] = 'codex'
            t = e.get('thread_id')
            v = e.get('token_usage') or {}
            tot = v.get('total')
            last = v.get('last')
            if not t or not isinstance(tot, dict) or not isinstance(last, dict):
                continue
            nn = tuple(
                num(tot.get(a)) or 0
                for a in (
                    'inputTokens',
                    'cachedInputTokens',
                    'cacheWriteInputTokens',
                    'outputTokens',
                )
            )
            if 'inputTokens' not in tot:
                nn = tuple(
                    num(tot.get(a)) or 0
                    for a in (
                        'input_tokens',
                        'cached_input_tokens',
                        'cache_write_input_tokens',
                        'output_tokens',
                    )
                )
            old = prev.get(t)
            if old == nn:
                continue
            if old is None:
                ll = tuple(
                    num(last.get(a)) or 0
                    for a in (
                        'inputTokens',
                        'cachedInputTokens',
                        'cacheWriteInputTokens',
                        'outputTokens',
                    )
                )
                if 'inputTokens' not in last:
                    ll = tuple(
                        num(last.get(a)) or 0
                        for a in (
                            'input_tokens',
                            'cached_input_tokens',
                            'cache_write_input_tokens',
                            'output_tokens',
                        )
                    )
                d = ll
            else:
                d = tuple(max(a - b, 0) for a, b in zip(nn, old))
            prev[t] = nn
            H['rows'] += 1
            add(at, *d)
        elif ev == 'cli_turn_started':
            H['engine'] = 'claude'
            started[e.get('events_name')] = (at, e.get('actor'))
        elif ev == 'cli_turn_completed':
            H['engine'] = 'claude'
            k = e.get('events_name')
            if k and k in seen:
                continue
            seen.add(k)
            dur = num(e.get('duration_s'))
            st = started.pop(k, (at - (dur or 0), e.get('actor')))
            if st[0] < end or not late:
                H['turns'].append([e.get('actor'), st[0], end])
            if late:
                continue
            s = e.get('session_id')
            if s and (e.get('model_usage') or e.get('usage')):
                # A result arrived, so this session's requests are reported up to here.
                H['reported_until'][s] = max(H['reported_until'].get(s, 0), at)
                H['session_actor'][s] = e.get('actor')
            mu = e.get('model_usage')
            if isinstance(mu, dict) and mu:
                vals = list(mu.values())
                cur = tuple(
                    sum(num(x.get(a)) or 0 for x in vals)
                    for a in (
                        'inputTokens',
                        'cacheReadInputTokens',
                        'cacheCreationInputTokens',
                        'outputTokens',
                    )
                )
                s = e.get('session_id')
                if s:
                    p = sess.get(s)
                    sess[s] = cur
                    if p is not None and all(a >= b for a, b in zip(cur, p)):
                        cur = tuple(a - b for a, b in zip(cur, p))
            else:
                u = e.get('usage') or {}
                cur = tuple(
                    num(u.get(a)) or 0
                    for a in (
                        'input_tokens',
                        'cache_read_input_tokens',
                        'cache_creation_input_tokens',
                        'output_tokens',
                    )
                )
            H['rows'] += 1
            add(at, cur[0] + cur[1] + cur[2], cur[1], cur[2], cur[3])
        elif ev == 'turn/started':
            opent[(e.get('thread_id'), e.get('turn_id'))] = (at, e.get('actor'))
        elif ev == 'turn/completed':
            x = opent.pop((e.get('thread_id'), e.get('turn_id')), None)
            dur = num(e.get('duration_s'))
            st = x[0] if x else (at - dur if dur else None)
            if st and (st < end or not late):
                H['turns'].append([e.get('actor') or (x[1] if x else None), st, end])
        elif ev == 'robot_tool_started':
            ct[e.get('call_id')] = (at, e.get('actor'), e.get('op'))
        elif ev in ('robot_tool_completed', 'robot_tool_failed'):
            x = ct.pop(e.get('call_id'), None)
            dur = num(e.get('duration_s'))
            st = x[0] if x else (at - dur if dur else None)
            if st and (st < end or not late):
                H['tools'].append([e.get('actor'), st, end])
        elif ev == 'error':
            er = e.get('error')
            m = (er.get('message', '') if isinstance(er, dict) else str(er or '')).lower()
            k = (
                'usage_limit'
                if 'usage limit' in m
                else 'rate_limit'
                if 'rate limit' in m
                else 'capacity'
                if 'capacity' in m
                else 'disconnect'
                if ('reconnecting' in m or 'disconnect' in m or 'connection closed' in m)
                else 'other'
            )
            H['errors'].append([at, k])
        elif ev in ('capacity_wait', 'capacity_retry', 'capacity_recovery_exhausted'):
            H['errors'].append([at, 'capacity'])
    H['unfinished'] = len(started)
    H['open_turns'] = [[v[1], v[0]] for v in opent.values()]
    H['gaps'] = gaps
    H['threads'] = len(prev) or len(sess)
    return H


CID = re.compile(r'"call_id":"([^"]+)"')


def call_id(line):
    """The call_id of a Codex rollout tool call or output. Rollouts write it after the
    arguments, so it can be anywhere in a long line."""
    try:
        c = (json.loads(line).get('payload') or {}).get('call_id')
        if isinstance(c, str):
            return c
    except (ValueError, AttributeError):
        pass
    m = CID.search(line)
    return m.group(1) if m else None


def claude_late_usage(run, H, cutoff_unix=None):
    """Claude requests that no reported result covers, from the run's native transcripts.

    Same rule as run_metrics._claude_usage_after_results (a background task can wake an idle
    CLI after the host stopped reading results; fork copies keep message ids, so a copy counts
    only if every session holding it with a known result ended earlier). Requests after
    `cutoff_unix` are outside the trial. Returns (input, cached, write, output) totals and the
    number of requests counted."""
    names = {}
    for n in run.files:
        if '/projects/' in n and (n.endswith('.jsonl') or n.endswith('.jsonl.xz')):
            stem = n[: -len('.xz')] if n.endswith('.xz') else n
            if stem not in names or n == stem:
                names[stem] = n
    until = H.get('reported_until') or {}
    entries = {}
    for n in sorted(names.values()):
        if n.endswith('.xz'):
            text = lzma.decompress(run.read(n)).decode(errors='replace').splitlines()
        else:
            text = run.lines(n)
        stem = os.path.basename(n).split('.jsonl')[0]
        for line in text:
            if '"usage"' not in line:
                continue
            try:
                r = json.loads(line)
                at = epoch(r['timestamp'])
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            msg = r.get('message') if isinstance(r.get('message'), dict) else {}
            if not (isinstance(msg.get('usage'), dict) and msg.get('id')):
                continue
            x = entries.setdefault(msg['id'], dict(holders=set(), at=at, usage=None))
            x['holders'].add(r.get('sessionId') or stem)
            x['at'] = max(x['at'], at)
            x['usage'] = msg['usage']  # repeated per content block; the last is final
    tot = [0, 0, 0, 0]
    count = 0
    for x in entries.values():
        if cutoff_unix is not None and x['at'] > cutoff_unix:
            continue
        known = {h: until[h] for h in x['holders'] if h in until}
        if known and not any(x['at'] > u for u in known.values()):
            continue
        u = x['usage']
        i, c, w, o = (
            num(u.get(k)) or 0
            for k in ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')
        )
        tot = [tot[0] + i + c + w, tot[1] + c, tot[2] + w, tot[3] + o]
        count += 1
    return tot, count


def transcripts(run, cutoff_unix=None):
    """Model-busy spans per actor from Codex transcripts or Claude native sessions, up to `cutoff_unix`."""
    spans, src = _transcripts(run)
    if cutoff_unix is not None:
        spans = [[a, s, min(e, cutoff_unix)] for a, s, e in spans if s < cutoff_unix]
    return spans, src


def _transcripts(run):
    spans = []
    src = None
    idx = run.find('private/engine/transcripts/index.json', 'engine/transcripts/index.json')
    if idx:
        src = 'codex-transcript'
        TS = re.compile(r'"timestamp":"([^"]+)"')
        base = idx.rsplit('/transcripts/', 1)[0] + '/transcripts/'
        I = json.loads(run.read(idx)).get('threads') or []
        for th in I:
            if str(th.get('actor', '')).startswith('snapshot'):
                continue
            f = None
            for n in (th.get('file', ''), base + os.path.basename(th.get('file', ''))):
                if n and run.has(n):
                    f = n
                    break
            if not f:
                continue
            state = None
            since = None
            opened = {}
            for line in run.lines(f):
                h = line[:260]
                m = TS.search(h)
                if not m:
                    continue
                t = epoch(m.group(1))
                if '"task_started"' in h:
                    state = 'model'
                    since = t
                    opened = {}
                elif '"task_complete"' in h or '"turn_aborted"' in h:
                    if state == 'model' and since:
                        spans.append([th['actor'], since, t])
                    state = None
                    opened = {}
                elif '"type":"function_call"' in h or '"type":"custom_tool_call"' in h:
                    c = call_id(line)
                    if state == 'model' and since:
                        spans.append([th['actor'], since, t])
                        state = 'tool'
                    if c:
                        opened[c] = 1
                elif '"function_call_output"' in h or '"custom_tool_call_output"' in h:
                    c = call_id(line)
                    if c and c in opened:
                        opened.pop(c)
                        if not opened and state == 'tool':
                            state = 'model'
                            since = t
        return spans, src
    names = [
        n for n in run.files if '/projects/' in n and n.endswith('.jsonl') and 'subagents/' not in n
    ]
    if names:
        src = 'claude-native'
        for n in names:
            prev = None
            for line in run.lines(n):
                if '"timestamp"' not in line:
                    continue
                try:
                    d = json.loads(line)
                except ValueError:
                    continue
                ts = d.get('timestamp')
                ty = d.get('type')
                if not ts or ty not in ('user', 'assistant'):
                    continue
                t = epoch(ts)
                if ty == 'assistant':
                    if prev is not None and t - prev < 7200:
                        spans.append([n.rsplit('/', 1)[-1][:12], prev, t])
                    prev = t
                else:
                    prev = t
    return spans, src


def extract_run(sel, root, cache_dir=None, motion='always'):
    """Compact record of one run. `sel` needs `id` and the archive key `k`; it is stored as is.

    Everything is cut at the trial cutoff (`cutoff`, see trial_cutoff): post-cutoff work
    never counts toward outcome, steps, time or tokens. `motion` chooses where object poses
    come from (see MOTION_MODES)."""
    run = Run(sel['k'], root, cache_dir)
    try:
        O = dict(sel=sel, kind=run.kind, nfiles=len(run.files), parse_errors=[])
        with runtime_db(run) as db:
            cut = trial_cutoff(run, db)
            A, M, msgT = actions(db, cut and cut['unix'])
        O['cutoff'] = cut
        O['actions'] = A
        O['meta'] = M
        O['msgT'] = msgT
        O['suite'] = suite(run, cut and cut['sim'], motion)
        O['host'] = H = host(run, cut and cut['unix'])
        if H and H['engine'] == 'claude':
            late, count = claude_late_usage(run, H, cut and cut['unix'])
            H['tok_after_results'] = dict(zip(('input', 'cached', 'write', 'output'), late), requests=count)
            for k, v in zip(('input', 'cached', 'write', 'output'), late):
                H['tok'][k] += v
        sp, src = transcripts(run, cut and cut['unix'])
        O['spans'] = sp
        O['span_src'] = src
        for b in ('evaluation.json', 'interruption-evaluation.json', 'runtime.json'):
            n = run.find('private/outputs/' + b, 'outputs/' + b)
            if n:
                try:
                    O[b] = json.loads(run.read(n))
                except Exception as e:
                    O[b] = {'error': repr(e)[:100]}
                    O['parse_errors'].append(n)
        ev = O.get('evaluation.json')
        if ev:
            O['evaluation.json'] = {
                k: v for k, v in ev.items() if not isinstance(v, (dict, list)) or k in ('evaluation',)
            }
        return O
    finally:
        run.close()
