"""Summarize recorded multi-role communication without inferring model intent."""
import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sqlite3
import statistics
from robofrontier import run_layout


def report_run(run):
    run = Path(run)
    db = run / 'private/state/runtime.sqlite'
    with sqlite3.connect(f'file:{db}?mode=ro', uri=True) as conn:
        agents = {name: json.loads(value) for name, value in conn.execute('select id,value from agents')}
        rows = [(created, kind, actor, json.loads(value or '{}')) for created, kind, actor, value in
                conn.execute('select created,kind,actor,value from events order by seq')]
    messages = Counter()
    wakes = Counter()
    deliveries = defaultdict(list)
    waits = defaultdict(list)
    actions = []
    for at, kind, actor, value in rows:
        if kind == 'MESSAGE_PERSISTED':
            messages[actor] += 1
        elif kind == 'WAKE_SENT':
            wakes[value.get('actor', actor)] += 1
        elif kind == 'DELIVERY_PREPARED':
            for msg in value.get('messages', []):
                if 'created_at' in msg:
                    deliveries[actor].append(max(0.0, at - msg['created_at']))
        elif kind == 'ACTION_FINISHED':
            if isinstance(value.get('started_at'), (int, float)) and isinstance(value.get('finished_at'), (int, float)):
                actions.append((value['started_at'], value['finished_at'], value.get('arm')))
    # The run's own manifest names its engine (legacy run-v3 host logs are engine-specific).
    host = run_layout.path(run, 'host_log')
    found = host.exists()
    latest_usage, updates = {}, defaultdict(list)
    ids = {value.get('thread_id'): name for name, value in agents.items() if value.get('thread_id')}
    if found:
        with host.open() as stream:
            for line in stream:
                try:
                    e = json.loads(line)
                except json.JSONDecodeError:
                    continue
                name = e.get('actor') or ids.get(e.get('thread_id'))
                if e.get('event') == 'thread/tokenUsage/updated' and name:
                    usage = e.get('token_usage') or {}
                    latest_usage[name] = usage.get('total', {})
                    updates[name].append({'at': e.get('at'), 'last': usage.get('last', {})})
                if e.get('event') == 'robot_tool_completed' and e.get('op') == 'wait_events' and name:
                    waits[name].append(e.get('duration_s'))
    overlap = sum(max(0., min(a[1], b[1]) - max(a[0], b[0])) for i, a in enumerate(actions)
                  for b in actions[i + 1:] if a[2] != b[2])
    def summary(values):
        return {'count': len(values), 'mean_s': statistics.mean(values) if values else None,
                'max_s': max(values) if values else None}
    # Without a host log, waits and token updates are unknown (None), not zero.
    return {'run': str(run), 'host_log': str(host), 'host_log_found': found,
            'roles': {name: {'kind': a.get('kind'), 'thread_id': a.get('thread_id'),
            'messages_sent': messages[name], 'wake_sent': wakes[name], 'delivery_delay': summary(deliveries[name]),
            'wait_events_tool_duration': summary([x for x in waits[name] if isinstance(x, (int, float))]) if found else None,
            'latest_recorded_token_total': latest_usage.get(name), 'token_usage_updates': updates[name] if found else None}
            for name, a in agents.items() if a.get('kind') != 'manager'},
            'finished_action_count': len(actions), 'pairwise_action_overlap_s': overlap,
            'notes': ['Delivery latency ends when a delivery batch is prepared, not when the model understood it.',
                      'Pairwise overlap counts overlapping action pairs and can exceed elapsed wall time; unfinished actions are excluded.',
                      'Token updates are provider/host records, not a bill or guaranteed one update per turn.',
                      'wait_events duration is tool duration, not all model or physical waiting.']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    batch = json.loads((args.batch / 'batch.json').read_text())
    # A Claude draft's batch.json keeps its static preparation status; the supervisor's
    # snapshot holds the live one.
    snapshot = run_layout.batch_path(args.batch, 'engineering_status')
    status = json.loads(snapshot.read_text()).get('status', batch['status']) if snapshot.is_file() else batch['status']
    data = {'batch': str(args.batch.resolve()), 'status': status,
            'runs': [report_run(job['run_directory']) for job in batch['jobs']]}
    text = json.dumps(data, indent=2, ensure_ascii=False) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text)
    else:
        print(text, end='')


if __name__ == '__main__':
    main()
