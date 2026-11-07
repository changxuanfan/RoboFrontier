"""Summarize a `.tar.gz` run package that holds only evaluation files, motion and Codex sessions."""

import datetime
import json
import re
import tarfile

TS = re.compile(r'"timestamp":"([^"]+)"')
CID = re.compile(r'"call_id":"([^"]+)"')


def epoch(s):
    return datetime.datetime.fromisoformat(s.replace('Z', '+00:00')).timestamp()


def summarize_session_archive(p):
    """Final evaluation, Relay payloads and model-busy spans (merged later) from one package."""
    O = dict(sessions=0, spans=[], first=None, last=None, calls=0)
    with tarfile.open(p, 'r:gz') as a:
        for m in a:
            a.members = []
            if m.name.endswith('/evaluation.json'):
                d = json.loads(a.extractfile(m).read())
                O['eval'] = {k: v for k, v in d.items() if not isinstance(v, (dict, list))}
                O['payloads'] = {
                    k: dict(
                        terminal=v.get('terminal_goal_met'),
                        completed=v.get('completed'),
                        nh=len(v.get('handovers') or []),
                    )
                    for k, v in (d.get('payloads') or {}).items()
                }
                O['violation_kinds'] = [v.get('kind') for v in d.get('violations') or []]
            elif '/sessions/' in m.name and m.name.endswith('.jsonl'):
                O['sessions'] += 1
                state = None
                since = None
                opened = {}
                for raw in a.extractfile(m):
                    h = raw[:300].decode(errors='ignore')
                    t = TS.search(h)
                    if not t:
                        continue
                    now = epoch(t.group(1))
                    O['first'] = now if O['first'] is None else min(O['first'], now)
                    O['last'] = now if O['last'] is None else max(O['last'], now)
                    if '"task_started"' in h:
                        state = 'model'
                        since = now
                        opened = {}
                    elif '"task_complete"' in h or '"turn_aborted"' in h:
                        if state == 'model' and since:
                            O['spans'].append([since, now])
                        state = None
                        opened = {}
                    elif '"type":"function_call"' in h or '"type":"custom_tool_call"' in h:
                        c = CID.search(raw[:900].decode(errors='ignore'))
                        O['calls'] += 1
                        if state == 'model' and since:
                            O['spans'].append([since, now])
                            state = 'tool'
                        if c:
                            opened[c.group(1)] = 1
                    elif '"function_call_output"' in h or '"custom_tool_call_output"' in h:
                        c = CID.search(raw[:400].decode(errors='ignore'))
                        if c and c.group(1) in opened:
                            opened.pop(c.group(1))
                            if not opened and state == 'tool':
                                state = 'model'
                                since = now
    return O
