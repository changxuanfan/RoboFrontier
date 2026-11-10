"""Derived host metrics with explicit missing values; never evaluator feedback."""
from collections import Counter
from datetime import datetime
import json
import lzma
import math
import os
from pathlib import Path
import re
import stat
import time

from ..runtime import layout as run_layout

# Native sub-agent tools: Codex's collaboration namespace and Claude's Agent/Task.
# They bypass robot delegate (no runtime record, likely uncollected usage).
NATIVE_SUBAGENT_TOOLS = frozenset({'spawn_agent', 'followup_task', 'send_message', 'interrupt_agent',
                                   'wait_agent', 'list_agents', 'Agent', 'Task'})
# A run-skills heading: "## [type] conclusion — role — tags: a, b"; each later revision
# of that entry is appended under "### rev N — role — what changed".
ENTRY = re.compile(r'^## \[([^\]]+)\]\s*(.*?)\s+—\s+(.+?)\s+—\s+tags:\s*(.*?)\s*$')
REVISION = re.compile(r'^### rev\s+(\d+)\s+—\s+(.+?)\s+—\s+(.*?)\s*$')


def open_session(path):
    """Open a native session transcript, plain or archived (`.jsonl.xz`), as text."""
    return lzma.open(path, 'rt') if str(path).endswith('.xz') else Path(path).open()


def session_stem(path):
    """A transcript's path without `.jsonl` or `.jsonl.xz`: its session-linked folder."""
    path = Path(path)
    for suffix in ('.jsonl.xz', '.jsonl'):
        if path.name.endswith(suffix): return path.with_name(path.name[:-len(suffix)])
    raise ValueError('Not a session transcript: '+str(path))


def session_glob(folder, pattern):
    """Transcripts under `folder` matching `pattern` (a `*.jsonl` glob), plain or archived.

    A transcript present in both forms counts once, as its plain file."""
    found = {}
    for path in Path(folder).rglob(pattern+'.xz'): found[session_stem(path)] = path
    for path in Path(folder).rglob(pattern): found[session_stem(path)] = path
    return sorted(found.values())


def codex_run_transcripts(run, thread):
    """The run's own copies of a Codex thread (run-v6 private/engine/transcripts/)."""
    try: folder = run_layout.path(run, 'engine_transcripts')
    except KeyError: return []
    return session_glob(folder, '*'+thread+'*.jsonl') if thread and folder.is_dir() else []


def run_skills(run_dir):
    """The run's shared lessons file: one item per entry heading, with its revisions.

    The policy writes this file, so it is opened without following a link and only as
    a regular file inside the run; anything else is reported as an issue and not read."""
    run_dir = Path(run_dir)
    unread = 'skills file is a link or not a regular file; not read'
    try:
        lessons = run_layout.path(run_dir, 'skills_file')
    except KeyError:
        return []
    except run_layout.LayoutError:
        # A link that leaves the run.
        return [{'path': _recorded_skills_path(run_dir), 'issue': unread, 'entries': []}]
    if not os.path.lexists(lessons):
        return []
    data = _read_regular(run_dir, lessons)
    if data is None:
        return [{'path': str(lessons.relative_to(run_dir)), 'issue': unread, 'entries': []}]
    entries = []
    for line in data.decode(errors='replace').splitlines():
        if line.startswith('### ') and entries:
            match = REVISION.match(line)
            entries[-1]['revisions'].append({'rev': int(match.group(1)), 'role': match.group(2), 'change': match.group(3)}
                                            if match else {'rev': None, 'role': None, 'change': line[4:].strip()})
            continue
        if not line.startswith('## '):
            continue
        match = ENTRY.match(line)
        entries.append({'type': match.group(1), 'title': match.group(2), 'role': match.group(3),
                        'tags': [t.strip() for t in match.group(4).split(',') if t.strip()], 'revisions': []}
                       if match else {'type': None, 'title': line[3:].strip(), 'role': None, 'tags': [], 'revisions': []})
    return [{'path': str(lessons.relative_to(run_dir)), 'bytes': len(data), 'entries': entries}]


def _recorded_skills_path(run_dir):
    try:
        manifest = json.loads((Path(run_dir)/'private/inputs/manifest.json').read_text())
        return manifest['layout_paths']['skills_file']
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _read_regular(run_dir, path):
    """Bytes of a regular file reached without any link below the run, else None."""
    relative = Path(path).relative_to(run_dir)
    current = Path(run_dir)
    for part in relative.parts[:-1]:
        current = current/part
        if current.is_symlink() or not current.is_dir():
            return None
    try:
        descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    except OSError:
        return None
    with os.fdopen(descriptor, 'rb') as stream:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            return None
        return stream.read()


def native_subagent_calls(paths):
    """Count native sub-agent tool calls in Codex rollouts or Claude transcripts."""
    counts = Counter()
    for path in paths:
        with open_session(path) as stream:
            for line in stream:
                # A cheap prefilter keeps image payloads and ordinary turns undecoded.
                if not any(name in line for name in NATIVE_SUBAGENT_TOOLS): continue
                try: record = json.loads(line)
                except ValueError: continue
                payload, names = record.get('payload') or {}, []
                if record.get('type') == 'response_item' and payload.get('type') in ('function_call', 'custom_tool_call'):
                    names.append(payload.get('name') or '')
                message = record.get('message') or {}
                if record.get('type') == 'assistant' and isinstance(message, dict) and isinstance(message.get('content'), list):
                    names += [b.get('name') or '' for b in message['content'] if isinstance(b, dict) and b.get('type') == 'tool_use']
                for name in names:
                    short = re.split(r'[./]|__', name)[-1]
                    if short in NATIVE_SUBAGENT_TOOLS: counts[short] += 1
    return dict(counts)


def host_event(run, event, **fields):
    # Telemetry is derived evidence. Its failure must not hide a robot result
    # or turn a settled action into an apparently unsubmitted request.
    try:
        path = run_layout.path(run, 'host_log', 'claude')
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (json.dumps({'schema': 'robofrontier.host-event.v1', 'at': time.time(),
                           'event': event, **fields}, ensure_ascii=False, allow_nan=False)+'\n').encode()
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try: return os.write(fd, raw) == len(raw)
        finally: os.close(fd)
    except (OSError, ValueError, TypeError):
        return False


AFTER_LAST_RESULT = 'after_last_result'


def number(value):
    return value if type(value) in (int, float) and math.isfinite(value) and value >= 0 else None


def usage(engine, raw, model_usage=None):
    raw = raw if isinstance(raw, dict) else {}
    if engine == 'claude':
        # modelUsage is the session's running total, including requests the turn's
        # usage leaves out. Never add the two; export_metrics takes per-turn differences.
        if isinstance(model_usage, dict) and model_usage:
            aliases = {'input_tokens':'inputTokens', 'cache_read_input_tokens':'cacheReadInputTokens',
                       'cache_creation_input_tokens':'cacheCreationInputTokens', 'output_tokens':'outputTokens'}
            entries = list(model_usage.values())
            raw = {key: sum(item[name] for item in entries)
                   if all(isinstance(item, dict) and number(item.get(name)) is not None for item in entries) else None
                   for key, name in aliases.items()}
        uncached = number(raw.get('input_tokens'))
        cached = number(raw.get('cache_read_input_tokens'))
        written = number(raw.get('cache_creation_input_tokens'))
        total = uncached+cached+written if None not in (uncached, cached, written) else None
    else:
        total = number(raw.get('input_tokens', raw.get('inputTokens')))
        cached = number(raw.get('cached_input_tokens', raw.get('cachedInputTokens')))
        uncached = total-cached if total is not None and cached is not None and total >= cached else None
        written = None  # Codex does not separately report cache writes here.
    # Same definition for both engines: every input token not read from cache.
    # Claude's uncached_input_tokens excludes cache writes, so it is not comparable.
    miss = total-cached if total is not None and cached is not None and total >= cached else None
    return {'input_tokens': total, 'uncached_input_tokens': uncached, 'cache_miss_input_tokens': miss,
            'cached_input_tokens': cached, 'cache_write_input_tokens': written,
            'output_tokens': number(raw.get('output_tokens', raw.get('outputTokens')))}


def _counter_delta(current, previous):
    return {k: v-previous[k] if v is not None and previous.get(k) is not None and v >= previous[k] else None
            for k, v in current.items()}


def _claude_turn_usage(event, totals):
    """One completed turn's share of a session's running modelUsage total.

    A lower counter means a new CLI process began counting again from zero."""
    current = usage('claude', event.get('usage'), event.get('model_usage'))
    session = event.get('session_id')
    if not event.get('model_usage') or not session: return current
    previous = totals.get(session)
    totals[session] = current
    if previous is None or any(v is not None and previous.get(k) is not None and v < previous[k]
                               for k, v in current.items()):
        return current
    return _counter_delta(current, previous)


def _claude_usage_after_results(run, reported_until, actors):
    """Requests no reported result covers, from the run's own transcripts, one row per session.

    A background task can wake an idle CLI after the host stopped reading its results.
    Fork copies keep their message ids and timestamps but take the child's session id, so
    a copy is reported only if every session holding it with a known result ended later."""
    try: folder = run_layout.path(run, 'engine_config', 'claude')/'projects'
    except KeyError: folder = None
    entries = {}
    for path in session_glob(folder, '*.jsonl') if folder is not None and folder.is_dir() else []:
        with open_session(path) as stream:
            for line in stream:
                if '"usage"' not in line and 'compact_boundary' not in line: continue
                try: record = json.loads(line)
                except ValueError: continue
                try: at = datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00')).timestamp()
                except (AttributeError, KeyError, ValueError): continue
                message = record.get('message') if isinstance(record.get('message'), dict) else {}
                if record.get('subtype') == 'compact_boundary':
                    key, used = ('compaction', record['timestamp']), None
                elif isinstance(message.get('usage'), dict) and message.get('id'):
                    key, used = message['id'], message['usage']  # Repeated per content block; the last is final.
                else: continue
                entry = entries.setdefault(key, {'holders': set(), 'at': at, 'usage': used, 'record': record})
                entry['holders'].add(record.get('sessionId') or session_stem(path).name)
                entry['at'] = max(entry['at'], at); entry['usage'] = used; entry['record'] = record
    fields = ('input_tokens', 'cache_read_input_tokens', 'cache_creation_input_tokens', 'output_tokens')
    by_session, sessions = {}, set()
    compactions = pre_tokens = 0
    for entry in entries.values():
        known = {h: reported_until[h] for h in entry['holders'] if h in reported_until}
        late = [h for h, until in known.items() if entry['at'] > until]
        if known and not late: continue
        session = min(late or entry['holders'])
        sessions.add(session)
        if entry['usage'] is None:
            compactions += 1
            pre_tokens += number((entry['record'].get('compactMetadata') or {}).get('preTokens')) or 0
        else:
            totals = by_session.setdefault(session, Counter())
            totals.update({k: number(entry['usage'].get(k)) or 0 for k in fields})
    rows = [{'actor': actors.get(session), 'session_id': session, 'phase': AFTER_LAST_RESULT,
             'usage': usage('claude', {k: totals[k] for k in fields}), 'usage_source': 'transcript',
             'reported_cost_usd': None, 'duration_s': None, 'ended_at': None}
            for session, totals in sorted(by_session.items())]
    return rows, {'sessions': len(sessions), 'compactions': compactions, 'compaction_pre_tokens': pre_tokens}


def _records(path):
    if not path.is_file(): return []
    records = []
    for line in path.read_text().splitlines():
        try:
            value = json.loads(line)
            if isinstance(value, dict): records.append(value)
        except ValueError:
            records.append({'event': 'malformed_evidence'})
    return records


def _union(intervals):
    total = 0.; end = None
    for low, high in sorted(intervals):
        total += max(0., high-max(low, end if end is not None else low))
        end = max(high, end if end is not None else high)
    return total


def claude_pricing():
    """List prices from the Claude section of configs/models.json, for estimates only."""
    from ..tasks.config import ROOT
    from ..configuration import model_catalog
    return model_catalog('claude').get('pricing') or {}


def claude_transcript_cost(run, pricing=None):
    """A list-price estimate of every Claude request in the run's own transcripts.

    The CLI reports cost only when a turn completes, so a turn cut off by the wall limit
    or a stop has none. Each assistant message's usage is priced once (transcripts repeat
    it per content block), main sessions and their sub-agent transcripts alike."""
    pricing = claude_pricing() if pricing is None else pricing
    try: folder = run_layout.path(run, 'engine_config', 'claude')/'projects'
    except KeyError: return None
    if not folder.is_dir(): return None
    messages = {}
    for path in session_glob(folder, '*.jsonl'):
        with open_session(path) as stream:
            for line in stream:
                if '"usage"' not in line: continue
                try: message = json.loads(line).get('message') or {}
                except ValueError: continue
                if isinstance(message.get('usage'), dict) and message.get('id'):
                    messages[message['id']] = (message.get('model'), message['usage'])
    total, unpriced, tokens = 0., set(), Counter()
    for model, used in messages.values():
        rates = (pricing.get('models') or {}).get(model)
        reads = used.get('cache_read_input_tokens') or 0
        writes = used.get('cache_creation') or {}
        w5 = writes.get('ephemeral_5m_input_tokens', used.get('cache_creation_input_tokens') or 0) or 0
        w1 = writes.get('ephemeral_1h_input_tokens') or 0
        fresh, out = used.get('input_tokens') or 0, used.get('output_tokens') or 0
        tokens.update(input_tokens=fresh, cache_read_input_tokens=reads, cache_write_5m_input_tokens=w5,
                      cache_write_1h_input_tokens=w1, output_tokens=out)
        if not rates:
            unpriced.add(model); continue
        prompt = fresh+reads+w5+w1
        long = prompt > rates.get('long_prompt_threshold_tokens', float('inf'))
        scale = rates['long_prompt_input']/rates['input'] if long else 1.
        base = rates['long_prompt_input'] if long else rates['input']
        output = rates['long_prompt_output'] if long else rates['output']
        total += (fresh*base + reads*rates['cache_read']*scale + w5*base*pricing.get('cache_write_5m_multiplier', 1.25)
                  + w1*base*pricing.get('cache_write_1h_multiplier', 2.) + out*output)/1e6
    return {'estimated_cost_usd': round(total, 6) if not unpriced else None, 'priced_requests': len(messages),
            'tokens': dict(tokens), 'unpriced_models': sorted(m for m in unpriced if m) or [],
            'basis': 'Transcript token usage at list price ('+pricing.get('source', 'no price source')+'); an estimate, not a provider bill'}


SPEED_WINDOW_S = 600.


def simulation_speed(run, sim_s, active_s=None, stalls=None):
    """How fast the world ran: simulation time over active time, and the slowest 10 minutes.

    The windows come from the world's performance log (one cumulative step count every 5 s
    of wall time), so a window that held an outage pause also counts as slow. Recorded for
    comparing hosts; a slow run is never stopped for it."""
    rows = []
    for path in sorted(Path(run).glob('private/outputs/**/cpu-performance.jsonl')):
        for line in path.read_text(errors='replace').splitlines():
            try: row = json.loads(line)
            except ValueError: continue
            if isinstance(row, dict) and isinstance(row.get('at'), (int, float)) and isinstance(row.get('world_steps'), int):
                rows.append((row['at'], row['world_steps'], str(path)))
    worst = None
    for name in sorted({r[2] for r in rows}):
        series = [(at, steps) for at, steps, source in rows if source == name]
        j = 0
        for i in range(len(series)):
            while j < len(series) and series[j][0]-series[i][0] < SPEED_WINDOW_S: j += 1
            if j < len(series):
                ratio = (series[j][1]-series[i][1])*.02/(series[j][0]-series[i][0])
                worst = ratio if worst is None else min(worst, ratio)
    return {'sim_s': round(float(sim_s), 3), 'active_s': None if active_s is None else round(float(active_s), 3),
            'speed_ratio': round(float(sim_s)/active_s, 4) if active_s else None,
            'active_time_stalls': stalls, 'slowest_10min_speed_ratio': None if worst is None else round(worst, 4)}


def export_metrics(run, engine):
    """Count actual host events, including setup; deduplicate terminal event identities."""
    events = _records(run_layout.path(run, 'host_log', engine))
    rows, seen = [], set()
    legacy = False
    after_results = None
    if engine == 'claude':
        session_totals, reported_until, actors = {}, {}, {}
        for e in events:
            if e.get('event') != 'cli_turn_completed': continue
            key = e.get('events_name')
            if not key or key in seen: continue
            seen.add(key)
            rows.append({'actor': e.get('actor'), 'session_id': e.get('session_id'),
                         'phase': e.get('phase', 'policy'),
                         'usage': _claude_turn_usage(e, session_totals),
                         'usage_source': 'model_usage' if e.get('model_usage') else 'usage',
                         'reported_cost_usd': number(e.get('reported_cost_usd')),
                         'duration_s': number(e.get('duration_s')), 'ended_at': number(e.get('at'))})
            session = e.get('session_id')
            if session:
                actors[session] = e.get('actor')
                if e.get('model_usage') or e.get('usage'):  # A result arrived, so its session's counter is known.
                    at = number(e.get('at'))
                    reported_until[session] = max(reported_until.get(session, 0), math.inf if at is None else at)
        if rows:
            late, after_results = _claude_usage_after_results(run, reported_until, actors)
            rows += late
        if not rows:
            legacy = True
            # Older runs remain readable. Setup usage may be absent, so this
            # fallback is explicitly partial rather than a full-run total.
            for p in sorted(run_layout.path(run, 'engine_turns', engine).glob('*-summary.json')):
                data = json.loads(p.read_text()); record = data.get('record') or {}
                summary = record.get('summary') or {}
                rows.append({'actor': data.get('actor'), 'session_id': data.get('session_id'),
                             'phase': 'policy', 'usage': usage(engine, summary.get('usage'), summary.get('model_usage')),
                             'usage_source': 'model_usage' if summary.get('model_usage') else 'usage',
                             'reported_cost_usd': number(summary.get('total_cost_usd')),
                             'duration_s': None, 'ended_at': None})
    else:
        previous = {}
        for e in events:
            if e.get('event') != 'thread/tokenUsage/updated': continue
            tid = e.get('thread_id'); value = e.get('token_usage') or {}
            total, last = value.get('total'), value.get('last')
            if not tid or not isinstance(total, dict) or not isinstance(last, dict): continue
            normalized = usage(engine, total)
            old = previous.get(tid)
            if old == normalized: continue
            delta = usage(engine, last) if old is None else _counter_delta(normalized, old)
            previous[tid] = normalized
            rows.append({'actor': e.get('actor'), 'session_id': tid, 'phase': 'policy',
                         'usage': delta, 'reported_cost_usd': None, 'duration_s': None, 'ended_at': None})
    fields = ('input_tokens', 'uncached_input_tokens', 'cache_miss_input_tokens', 'cached_input_tokens', 'cache_write_input_tokens', 'output_tokens')
    totals = {k: sum(r['usage'][k] for r in rows) if rows and all(r['usage'][k] is not None for r in rows) else None for k in fields}
    known_usage = {k: sum(r['usage'][k] for r in rows if r['usage'][k] is not None)
                   if any(r['usage'][k] is not None for r in rows) else None for k in fields}
    costs = [r['reported_cost_usd'] for r in rows if r['reported_cost_usd'] is not None]
    tools = [e for e in events if e.get('event') in ('robot_tool_completed', 'robot_tool_failed')]
    tool_seconds = [number(e.get('duration_s')) for e in tools]
    # A Claude delegate's fork is its first turn; runs prepared before that had separate
    # tool-free snapshot and fork turns.
    setup_seconds = ([r['duration_s'] for r in rows if r['phase'] in ('snapshot_setup', 'fork_setup')]
                     if engine == 'claude' else [])
    setup_seconds += [number(e.get('duration_s')) for e in events if e.get('event') in ('snapshot_created', 'fork_created')]
    intervals = [(r['ended_at']-r['duration_s'], r['ended_at']) for r in rows
                 if r['ended_at'] is not None and r['duration_s'] is not None]
    model_seconds = [r['duration_s'] for r in rows if r['phase'] != AFTER_LAST_RESULT]
    if engine == 'codex':
        completed = [e for e in events if e.get('event') == 'turn/completed']
        intervals = [(e['at']-e['duration_s'], e['at']) for e in completed
                     if number(e.get('at')) is not None and number(e.get('duration_s')) is not None]
        model_seconds = [number(e.get('duration_s')) for e in completed]
    by_actor = {}
    for actor in sorted({r['actor'] for r in rows if r['actor']}):
        selected = [r for r in rows if r['actor'] == actor]
        by_actor[actor] = {k: sum(r['usage'][k] for r in selected)
                          if all(r['usage'][k] is not None for r in selected) else None for k in fields}
    malformed = sum(e.get('event') == 'malformed_evidence' for e in events)
    started = {e.get('events_name') for e in events if e.get('event') == 'cli_turn_started'}
    unfinished = len(started-seen) if engine == 'claude' else None
    # A compaction's tokens appear only in a result's modelUsage, never in the transcript.
    complete = not legacy and not malformed and not unfinished and not (after_results or {}).get('compactions')
    reported = sum(costs) if costs else None
    estimate = claude_transcript_cost(run) if engine == 'claude' else None
    cost_complete = bool(rows) and len(costs) == len(rows) and complete
    return {'schema': 'robofrontier.run-metrics.v1', 'engine': engine, 'usage': totals,
            'known_usage_subtotals': known_usage,
            'by_actor': by_actor, 'evidence_scope': 'legacy_policy_only' if legacy else 'host_observed',
            'cache_hit_rate': totals['cached_input_tokens']/totals['input_tokens']
                if totals['input_tokens'] and totals['cached_input_tokens'] is not None else None,
            'reported_cost_usd': reported,
            'cost_complete': cost_complete,
            # Turns cut off by the wall limit or a stop report no cost; the transcripts still
            # record their tokens. The estimate covers every request, so the unreported part
            # is what it adds beyond the reported cost.
            'transcript_cost_estimate': estimate,
            'estimated_unreported_cost_usd': (max(0., round(estimate['estimated_cost_usd']-(reported or 0.), 6))
                                              if not cost_complete and estimate and estimate['estimated_cost_usd'] is not None else None),
            'usage_after_last_result': after_results,
            'rows': rows, 'phase_counts': {p: sum(r['phase'] == p for r in rows) for p in sorted({r['phase'] for r in rows})},
            'row_unit': 'cli_turn' if engine == 'claude' else 'token_usage_update',
            'unfinished_cli_turns': unfinished,
            'tool_call_count': len(tools),
            'tool_seconds_sum': sum(tool_seconds) if tool_seconds and None not in tool_seconds else None,
            'fork_setup_seconds_sum': sum(setup_seconds) if setup_seconds and None not in setup_seconds else None,
            'model_process_wall_seconds_union': _union(intervals) if intervals else None,
            'model_process_seconds_sum': sum(model_seconds) if model_seconds and None not in model_seconds else None,
            'usage_complete': bool(rows) and all(totals[k] is not None for k in ('input_tokens', 'cached_input_tokens', 'output_tokens')) and complete,
            'malformed_event_count': malformed,
            'interpretation': 'Reported usage/cost, not a provider bill. Missing values are null. '
                              'CLI wall time includes tool waits; overlapping durations are not additive wall-time shares. '
                              'Legacy summaries may omit setup; host-observed Codex counters are not native-transcript totals.'}


def native_codex_sessions(run, thread, codex_home=None):
    """Resolve an explicit home, collected mapping, batch marker, then environment.

    A known batch home which is unavailable never falls back to unrelated users'
    default sessions. This function reads neither credentials nor live databases.
    """
    if not thread: return []
    run = Path(run).resolve()
    own = codex_run_transcripts(run, thread)
    if own and codex_home is None: return own
    if codex_home is not None:
        home = Path(codex_home).expanduser().resolve()
    else:
        home = None
        for parent in (run, *run.parents):
            collection = parent/'collection.json'
            if collection.is_file():
                data = json.loads(collection.read_text())
                matches = []
                for job in data.get('jobs', []):
                    if (parent/job.get('run', '')).resolve() != run: continue
                    for role in job.get('roles', []):
                        if role.get('thread_id') == thread:
                            if not isinstance(role.get('session'), str): continue
                            path = (parent/role['session']).resolve()
                            if path.is_relative_to(parent) and path.is_file(): matches.append(path)
                return sorted(set(matches))
            if parent == run: marker = run_layout.path(run, 'codex_home_marker')
            elif (parent/'batch.json').is_file(): marker = run_layout.batch_path(parent, 'codex_home_marker')
            else: marker = parent/'codex-home.json'
            if home is None and marker.is_file():
                home = Path(json.loads(marker.read_text())['codex_home']).expanduser().resolve()
        if home is None: home = Path(os.environ.get('CODEX_HOME', Path.home()/'.codex')).expanduser().resolve()
    return session_glob(home/'sessions', '*'+thread+'*.jsonl')
