"""Summarize a `.tar.gz` run package that holds only evaluation files, motion and Codex sessions."""

import datetime
import json
import re
import tarfile

from .extract import call_id

TS = re.compile(r'"timestamp":"([^"]+)"')


def epoch(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def summarize_session_archive(p):
    """Final evaluation, Relay payloads and model-busy spans (merged later) from one package."""
    summary = dict(sessions=0, spans=[], first=None, last=None, calls=0)
    with tarfile.open(p, 'r:gz') as a:
        for m in a:
            a.members = []
            if m.name.endswith('/evaluation.json'):
                d = json.loads(a.extractfile(m).read())
                summary['eval'] = {k: v for k, v in d.items() if not isinstance(v, (dict, list))}
                summary['payloads'] = {
                    k: dict(
                        terminal=v.get('terminal_goal_met'),
                        completed=v.get('completed'),
                        nh=len(v.get('handovers') or []),
                    )
                    for k, v in (d.get('payloads') or {}).items()
                }
                summary['violation_kinds'] = [v.get('kind') for v in d.get('violations') or []]
            elif '/sessions/' in m.name and m.name.endswith('.jsonl'):
                summary['sessions'] += 1
                state = None
                since = None
                opened = {}
                for raw in a.extractfile(m):
                    h = raw[:300].decode(errors='ignore')
                    t = TS.search(h)
                    if not t:
                        continue
                    now = epoch(t.group(1))
                    summary['first'] = now if summary['first'] is None else min(summary['first'], now)
                    summary['last'] = now if summary['last'] is None else max(summary['last'], now)
                    if '"task_started"' in h:
                        state = 'model'
                        since = now
                        opened = {}
                    elif '"task_complete"' in h or '"turn_aborted"' in h:
                        if state == 'model' and since:
                            summary['spans'].append([since, now])
                        state = None
                        opened = {}
                    elif '"type":"function_call"' in h or '"type":"custom_tool_call"' in h:
                        c = call_id(raw.decode(errors='ignore'))
                        summary['calls'] += 1
                        if state == 'model' and since:
                            summary['spans'].append([since, now])
                            state = 'tool'
                        if c:
                            opened[c] = 1
                    elif '"function_call_output"' in h or '"custom_tool_call_output"' in h:
                        c = call_id(raw.decode(errors='ignore'))
                        if c and c in opened:
                            opened.pop(c)
                            if not opened and state == 'tool':
                                state = 'model'
                                since = now
    return summary
