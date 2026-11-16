"""Live prompt-cache monitor for the Codex / Claude gateway's metadata log.

Reads the JSONL file written by `codex_claude_gateway.py --log` and reprints, per run and
overall: requests, cache-hit rate (cumulative and over a rolling window), cache-creation
share, token totals and an estimated cost. Standard library only. It only reads the log: it
never contacts a model provider and never stops, pauses or changes a run.

    python scripts/codex_claude_monitor.py /private/claude/transport-metadata.jsonl
    python scripts/codex_claude_monitor.py LOG --once --json --min-hit-rate 0.7
"""
import argparse
import json
from pathlib import Path
import sys
import time

# The one price table (USD per million tokens). Estimates only, never a provider invoice.
PRICES = {'claude-opus-5-5': {'input': 4.0, 'output': 20.0, 'cache_read': 0.20,
                              'cache_write_5m_multiplier': 1.25, 'cache_write_1h_multiplier': 2.0}}
TOKEN_FIELDS = ('uncached_input_tokens', 'cache_read_input_tokens', 'cache_creation_5m_input_tokens',
                'cache_creation_1h_input_tokens', 'output_tokens')
WARNING_EXIT = 2


def tokens(record):
    """One log record's token counts; None when the request reported no usage."""
    usage = record.get('usage')
    if not isinstance(usage, dict):
        return None
    number = lambda name: usage[name] if isinstance(usage.get(name), int) and not isinstance(usage.get(name), bool) else 0
    created = number('cache_creation_input_tokens')
    short, long = number('cache_creation_5m_input_tokens'), number('cache_creation_1h_input_tokens')
    if short + long != created:
        # The API did not split the writes by lifetime: attribute them to the request's own TTL.
        short, long = (0, created) if record.get('cache_ttl') == '1h' else (created, 0)
    return {'uncached_input_tokens': number('input_tokens'), 'cache_read_input_tokens': number('cache_read_input_tokens'),
            'cache_creation_5m_input_tokens': short, 'cache_creation_1h_input_tokens': long,
            'output_tokens': number('output_tokens')}


def cost_usd(counts, model='claude-opus-5-5'):
    price = PRICES.get(model)
    if price is None:
        return None
    return (counts['uncached_input_tokens'] * price['input']
            + counts['cache_read_input_tokens'] * price['cache_read']
            + counts['cache_creation_5m_input_tokens'] * price['input'] * price['cache_write_5m_multiplier']
            + counts['cache_creation_1h_input_tokens'] * price['input'] * price['cache_write_1h_multiplier']
            + counts['output_tokens'] * price['output']) / 1e6


def _empty():
    return {'requests': 0, 'requests_with_usage': 0, 'failed_requests': 0, 'thinking_blocks_dropped': 0,
            **{name: 0 for name in TOKEN_FIELDS}, 'prefixes': set(), 'model': None}


def _add(total, record):
    total['requests'] += 1
    if record.get('status') != 'completed':
        total['failed_requests'] += 1
    dropped = record.get('thinking_blocks_dropped')
    total['thinking_blocks_dropped'] += dropped if isinstance(dropped, int) else 0
    if record.get('prefix_sha256'):
        total['prefixes'].add(record['prefix_sha256'])
    counts = tokens(record)
    if counts is not None:
        total['requests_with_usage'] += 1
        total['model'] = record.get('model') or total['model']
        for name in TOKEN_FIELDS:
            total[name] += counts[name]


def _rates(total):
    cache_input = (total['uncached_input_tokens'] + total['cache_read_input_tokens']
                   + total['cache_creation_5m_input_tokens'] + total['cache_creation_1h_input_tokens'])
    created = total['cache_creation_5m_input_tokens'] + total['cache_creation_1h_input_tokens']
    return {'requests': total['requests'], 'requests_with_usage': total['requests_with_usage'],
            'failed_requests': total['failed_requests'], 'input_tokens': cache_input,
            'uncached_input_tokens': total['uncached_input_tokens'],
            'cache_read_input_tokens': total['cache_read_input_tokens'], 'cache_creation_input_tokens': created,
            'output_tokens': total['output_tokens'],
            # Hit rate = cache reads over every input token; None until a request reported input.
            'cache_hit_rate': total['cache_read_input_tokens'] / cache_input if cache_input else None,
            'cache_creation_share': created / cache_input if cache_input else None,
            'estimated_cost_usd': cost_usd(total, total['model'] or 'claude-opus-5-5'),
            'thinking_blocks_dropped': total['thinking_blocks_dropped'],
            'distinct_cache_prefixes': len(total['prefixes'])}


def label_of(record, by='run', names=None):
    if by == 'key':
        value = record.get('key_label')
    elif by == 'session':
        value = record.get('codex_session')
    else:
        value = record.get('run')
    value = str(value) if value else 'unknown'
    return (names or {}).get(value, value)


def summarize(records, now=None, window_s=600, by='run', names=None, min_hit_rate=None, min_requests=20):
    """Cumulative and rolling-window cache statistics per label and overall.

    A row is flagged only when its rolling-window hit rate is below `min_hit_rate` after at
    least `min_requests` requests with usage in that window. The flag is advisory.
    """
    now = time.time() if now is None else now
    groups, recent = {}, {}
    overall, overall_recent = _empty(), _empty()
    for record in records:
        if not isinstance(record, dict) or record.get('event') not in (None, 'request'):
            continue
        label = label_of(record, by, names)
        _add(groups.setdefault(label, _empty()), record)
        _add(overall, record)
        at = record.get('at')
        if isinstance(at, (int, float)) and now - window_s <= at <= now:
            _add(recent.setdefault(label, _empty()), record)
            _add(overall_recent, record)

    def row(total, window):
        result = _rates(total)
        rolling = _rates(window)
        result['window'] = {key: rolling[key] for key in ('requests', 'requests_with_usage', 'input_tokens',
                                                          'cache_read_input_tokens', 'cache_hit_rate',
                                                          'cache_creation_share')}
        result['warning'] = bool(min_hit_rate is not None and rolling['requests_with_usage'] >= min_requests
                                 and rolling['cache_hit_rate'] is not None and rolling['cache_hit_rate'] < min_hit_rate)
        return result

    rows = {label: row(total, recent.get(label, _empty())) for label, total in sorted(groups.items())}
    return {'generated_at': now, 'window_s': window_s, 'grouped_by': by, 'min_hit_rate': min_hit_rate,
            'min_requests': min_requests, 'cost_note': 'Estimate from list prices; not a provider invoice',
            'overall': row(overall, overall_recent), 'labels': rows,
            'warning': any(item['warning'] for item in rows.values())}


def read_log(path):
    """Every complete JSON line. A partly written last line is left for the next pass."""
    records = []
    try:
        with Path(path).open('rb') as stream:
            for line in stream:
                if not line.endswith(b'\n'):
                    break
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
    except FileNotFoundError:
        pass
    return records


def batch_names(batch):
    """Map each run's Codex installation ID to its folder name, from the runs' home markers.

    With `runtime.codex_home_scope = "task"` every run has its own Codex home, so the
    installation ID the CLI sends identifies the run. Homes shared by several runs cannot
    be told apart this way.
    """
    names, owners = {}, {}
    for marker in sorted(Path(batch).rglob('codex-home.json')):
        try:
            home = Path(json.loads(marker.read_text())['codex_home'])
            identity = (home/'installation_id').read_text().strip()
        except (OSError, ValueError, KeyError, TypeError):
            continue
        run = marker.parent
        while run.name in ('engine', 'private'):
            run = run.parent
        owners.setdefault(identity, []).append(run.name)
    for identity, runs in owners.items():
        label = 'codex-'+identity[:8]
        names[label] = runs[0] if len(runs) == 1 else label+' (shared by %d runs)' % len(runs)
    return names


def _percent(value):
    return '   n/a' if value is None else '%5.1f%%' % (100 * value)


def render(summary):
    header = '%-34s %6s %7s %7s %7s %12s %12s %9s' % ('run', 'reqs', 'hit', 'hit/win', 'write', 'input tok',
                                                      'output tok', 'est. USD')
    lines = [time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(summary['generated_at']))
             + '  window %d s, grouped by %s' % (summary['window_s'], summary['grouped_by']), header]
    for label, row in [*summary['labels'].items(), ('ALL', summary['overall'])]:
        cost = row['estimated_cost_usd']
        lines.append('%-34s %6d %7s %7s %7s %12d %12d %9s%s%s' % (
            label[:34], row['requests'], _percent(row['cache_hit_rate']), _percent(row['window']['cache_hit_rate']),
            _percent(row['cache_creation_share']), row['input_tokens'], row['output_tokens'],
            'n/a' if cost is None else '%.2f' % cost,
            '  WARNING low cache-hit rate' if row['warning'] else '',
            '  (%d failed)' % row['failed_requests'] if row['failed_requests'] else ''))
    lines.append('hit = cache_read / (uncached + cache_read + cache_creation); write = cache_creation share; '
                 'cost is an estimate from list prices.')
    return '\n'.join(lines)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('log', type=Path, help='Metadata JSONL written by the gateway')
    parser.add_argument('--window-s', type=float, default=600, help='Rolling window (default 600 s)')
    parser.add_argument('--interval-s', type=float, default=5, help='Seconds between prints (default 5)')
    parser.add_argument('--by', choices=('run', 'key', 'session'), default='run',
                        help='Group by run label (default), gateway key label or Codex session')
    parser.add_argument('--batch', type=Path, help='Batch folder: show run folder names instead of installation IDs')
    parser.add_argument('--min-hit-rate', type=float, help='Mark rows whose rolling hit rate is below this fraction')
    parser.add_argument('--min-requests', type=int, default=20,
                        help='Requests needed in the window before a row can be marked (default 20)')
    parser.add_argument('--once', action='store_true', help='Print once; exit 2 if a row is marked')
    parser.add_argument('--json', action='store_true', help='Print the summary as JSON')
    args = parser.parse_args(argv)
    if args.min_hit_rate is not None and not 0 <= args.min_hit_rate <= 1:
        parser.error('--min-hit-rate is a fraction between 0 and 1')
    while True:
        names = batch_names(args.batch) if args.batch and args.by == 'run' else None
        summary = summarize(read_log(args.log), window_s=args.window_s, by=args.by, names=names,
                            min_hit_rate=args.min_hit_rate, min_requests=args.min_requests)
        print(json.dumps(summary) if args.json else render(summary), flush=True)
        if args.once:
            return WARNING_EXIT if summary['warning'] else 0
        try:
            time.sleep(max(.5, args.interval_s))
        except KeyboardInterrupt:
            return 0


if __name__ == '__main__':
    raise SystemExit(main())
