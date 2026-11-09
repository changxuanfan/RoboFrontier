"""Extract one run's actions, evaluator timeline, tokens and activity spans into a compact JSON."""

import collections, json, os, re, shutil, sqlite3, tempfile, datetime
from pathlib import Path

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


def actions(run):
    names = [n for n in run.files if n.endswith('runtime.sqlite') and 'state/' in n] or [
        n for n in run.files if n.endswith('runtime.sqlite')
    ]
    if not names:
        return None, None, None, None
    n = names[0]
    T = tempfile.mkdtemp(prefix='rf-sq-', dir=os.environ.get('RF_TMP') or None)
    try:
        p = Path(T) / 'r.sqlite'
        p.write_bytes(run.read(n))
        for suf in ('-wal', '-shm'):
            if run.has(n + suf):
                (Path(T) / ('r.sqlite' + suf)).write_bytes(run.read(n + suf))
        db = sqlite3.connect(str(p))
        A = []
        for actor, value in db.execute('select actor,value from actions'):
            v = json.loads(value)
            pm = v.get('parameters') or {}
            A.append(
                dict(
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
            )
        tabs = {r[0] for r in db.execute("select name from sqlite_master where type='table'")}
        msg = (
            db.execute('select count(*) from messages').fetchone()[0]
            if 'messages' in tabs
            else None
        )
        msgT = (
            [r[0] for r in db.execute('select created from messages')] if 'messages' in tabs else []
        )
        ev = (
            db.execute('select min(created),max(created) from events').fetchone()
            if 'events' in tabs
            else (None, None)
        )
        kinds = (
            collections.Counter(r[0] for r in db.execute('select kind from events'))
            if 'events' in tabs
            else {}
        )
        agents = (
            db.execute('select count(*) from agents').fetchone()[0] if 'agents' in tabs else None
        )
        return (
            A,
            dict(
                messages=msg,
                agents=agents,
                first=ev[0],
                last=ev[1],
                finish_proposed=kinds.get('TEAM_FINISH_PROPOSED', 0),
                delegations=kinds.get('DELEGATION_ACTIVATED', 0),
            ),
            msgT,
            None,
        )
    finally:
        shutil.rmtree(T, ignore_errors=True)


def suite(run):
    n = run.find(
        'private/outputs/suite-process.jsonl', 'outputs/suite-process.jsonl', 'suite-process.jsonl'
    )
    if not n:
        return None
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
        segments=0,
        lines=0,
        first_sim=None,
        last_sim=None,
        solved_at=None,
        done_at=None,
        final_payloads=None,
    )
    pend = set()
    prev_assign = {}
    prev_drops = {}
    seen_h = set()
    prev_comp = None
    prev_tr = None
    prev_disp = None
    prev_m = None
    for line in run.lines(n):
        if '"result"' not in line[:200] and '"schema"' in line[:60]:
            S['segments'] += 1
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        r = d.get('result')
        if not isinstance(r, dict):
            continue
        t = num(d.get('sim_time_s'))
        t = t if t is not None else num(r.get('sim_time_s'))
        if t is None:
            continue
        S['lines'] += 1
        S['first_sim'] = t if S['first_sim'] is None else S['first_sim']
        S['last_sim'] = t
        scal = {k: v for k, v in r.items() if not isinstance(v, (dict, list))}
        S['last'] = scal
        if r.get('task_success') and S['done_at'] is None:
            S['done_at'] = t
        objs = d.get('objects') or {}
        if objs and pend:
            for g in list(pend):
                x = S['goals'].get(g)
                if x and x.get('pos') is None:
                    x['pos'] = (objs.get(x['item']) or {}).get('position_m')
                pend.discard(g)
        if 'assignments' in r:
            a = r['assignments'] or {}
            m = num(r.get('matched_goals'))
            S['total'] = r.get('total_goals', S['total'])
            if a != prev_assign:
                for g, i in a.items():
                    if prev_assign.get(g) != i:
                        p = (objs.get(i) or {}).get('position_m')
                        if g not in S['goals']:
                            S['goals'][g] = dict(t=t, item=i, pos=p)
                            if p is None:
                                pend.add(g)
                        else:
                            S['goals'][g].setdefault('swaps', []).append([t, i])
                for g, i in prev_assign.items():
                    if g not in a:
                        S['regress'].append([t, g, i])
                prev_assign = dict(a)
            if m is not None and m != prev_m:
                S['match'].append([t, m])
                prev_m = m
            for i, o in objs.items():
                z = (o.get('position_m') or [0, 0, 0])[2]
                if i not in S['z0']:
                    S['z0'][i] = z
                elif z < S['z0'][i] - 0.2 and i not in S['lost']:
                    S['lost'][i] = t
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
    return S


TOK = lambda: dict(input=0, cached=0, write=0, output=0)


def host(run):
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
            H['turns'].append([e.get('actor'), st[0], at])
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
            if st:
                H['turns'].append([e.get('actor') or (x[1] if x else None), st, at])
        elif ev == 'robot_tool_started':
            ct[e.get('call_id')] = (at, e.get('actor'), e.get('op'))
        elif ev in ('robot_tool_completed', 'robot_tool_failed'):
            x = ct.pop(e.get('call_id'), None)
            dur = num(e.get('duration_s'))
            st = x[0] if x else (at - dur if dur else None)
            if st:
                H['tools'].append([e.get('actor'), st, at])
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


def transcripts(run):
    """Model-busy spans per actor from Codex transcripts or Claude native sessions."""
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


def extract_run(sel, root, cache_dir=None):
    """Compact record of one run. `sel` needs `id` and the archive key `k`; it is stored as is."""
    run = Run(sel['k'], root, cache_dir)
    O = dict(sel=sel, kind=run.kind, nfiles=len(run.files))
    A, M, msgT, _ = actions(run)
    O['actions'] = A
    O['meta'] = M
    O['msgT'] = msgT
    O['suite'] = suite(run)
    O['host'] = host(run)
    sp, src = transcripts(run)
    O['spans'] = sp
    O['span_src'] = src
    for b in ('evaluation.json', 'interruption-evaluation.json', 'runtime.json'):
        n = run.find('private/outputs/' + b, 'outputs/' + b)
        if n:
            try:
                O[b] = json.loads(run.read(n))
            except Exception as e:
                O[b] = {'error': repr(e)[:100]}
    ev = O.get('evaluation.json')
    if ev:
        O['evaluation.json'] = {
            k: v for k, v in ev.items() if not isinstance(v, (dict, list)) or k in ('evaluation',)
        }
    return O
