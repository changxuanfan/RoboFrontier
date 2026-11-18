"""Cache monitor arithmetic on a synthetic gateway log; standard library only, no network."""

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from roboteam.harness.adapters.claude_in_codex import monitor  # noqa: E402

NOW = 1_800_000_000.0


def record(
    at, run, uncached, read, written=0, output=0, *, ttl='5m', split=True, status='completed', **extra
):
    usage = {
        'input_tokens': uncached,
        'cache_read_input_tokens': read,
        'cache_creation_input_tokens': written,
        'output_tokens': output,
    }
    if split:
        usage.update(
            cache_creation_5m_input_tokens=0 if ttl == '1h' else written,
            cache_creation_1h_input_tokens=written if ttl == '1h' else 0,
        )
    return {
        'event': 'request',
        'at': at,
        'run': run,
        'key_label': 'default',
        'codex_session': 'thread-' + run,
        'model': 'claude-opus-5-5',
        'status': status,
        'cache_ttl': ttl,
        'usage': usage,
        'prefix_sha256': 'p-' + run,
        **extra,
    }


class CacheMonitorTests(unittest.TestCase):
    def test_hit_rate_creation_share_and_totals_per_run_and_overall(self):
        records = [
            record(NOW - 30, 'a', 100, 900, 0, 50),
            record(NOW - 20, 'a', 0, 600, 400, 50),
            record(NOW - 10, 'b', 1000, 0, 1000, 10),
        ]
        summary = monitor.summarize(records, now=NOW)
        a, b, overall = summary['labels']['a'], summary['labels']['b'], summary['overall']
        self.assertEqual(
            (a['requests'], a['input_tokens'], a['cache_read_input_tokens'], a['output_tokens']),
            (2, 2000, 1500, 100),
        )
        self.assertEqual((a['cache_hit_rate'], a['cache_creation_share']), (0.75, 0.2))
        self.assertEqual((b['cache_hit_rate'], b['cache_creation_share']), (0.0, 0.5))
        self.assertEqual(
            (overall['requests'], overall['input_tokens'], overall['cache_hit_rate']), (3, 4000, 0.375)
        )
        self.assertEqual(
            (overall['uncached_input_tokens'], overall['cache_creation_input_tokens']), (1100, 1400)
        )
        self.assertEqual(a['distinct_cache_prefixes'], 1)

    def test_cost_estimate_uses_the_one_price_table(self):
        million = 1_000_000
        counts = {
            'uncached_input_tokens': million,
            'cache_read_input_tokens': million,
            'cache_creation_5m_input_tokens': million,
            'cache_creation_1h_input_tokens': million,
            'output_tokens': million,
        }
        # 4 input + 0.20 read + 4*1.25 five-minute write + 4*2 one-hour write + 20 output.
        self.assertAlmostEqual(monitor.cost_usd(counts), 4 + 0.20 + 5 + 8 + 20)
        self.assertIsNone(monitor.cost_usd(counts, 'unknown-model'))
        self.assertEqual(
            monitor.PRICES['claude-opus-5-5'],
            {
                'input': 4.0,
                'output': 20.0,
                'cache_read': 0.20,
                'cache_write_5m_multiplier': 1.25,
                'cache_write_1h_multiplier': 2.0,
            },
        )
        five = monitor.summarize([record(NOW, 'a', 0, 0, million)], now=NOW)['overall']['estimated_cost_usd']
        hour = monitor.summarize([record(NOW, 'a', 0, 0, million, ttl='1h')], now=NOW)['overall'][
            'estimated_cost_usd'
        ]
        unsplit = monitor.summarize([record(NOW, 'a', 0, 0, million, ttl='1h', split=False)], now=NOW)[
            'overall'
        ]['estimated_cost_usd']
        self.assertEqual((five, hour, unsplit), (5.0, 8.0, 8.0))

    def test_rolling_window_counts_only_recent_requests(self):
        records = [
            record(NOW - 3600, 'a', 0, 1000),
            record(NOW - 601, 'a', 0, 1000),
            record(NOW - 600, 'a', 500, 500),
            record(NOW - 1, 'a', 1000, 0),
            record(NOW + 5, 'a', 0, 9999),
        ]
        row = monitor.summarize(records, now=NOW, window_s=600)['labels']['a']
        self.assertEqual(
            (row['window']['requests'], row['window']['input_tokens'], row['window']['cache_hit_rate']),
            (2, 2000, 0.25),
        )
        self.assertEqual(row['requests'], 5)
        short = monitor.summarize(records, now=NOW, window_s=10)['labels']['a']['window']
        self.assertEqual((short['requests'], short['cache_hit_rate']), (1, 0.0))
        empty = monitor.summarize(records, now=NOW + 9999, window_s=10)['labels']['a']['window']
        self.assertEqual((empty['requests'], empty['cache_hit_rate']), (0, None))

    def test_low_rate_is_only_marked_after_enough_recent_requests(self):
        low = [record(NOW - i, 'cold', 900, 100) for i in range(5)]
        good = [record(NOW - i, 'warm', 100, 900) for i in range(5)]
        few = monitor.summarize(low + good, now=NOW, min_hit_rate=0.5, min_requests=6)
        self.assertFalse(few['warning'])
        enough = monitor.summarize(low + good, now=NOW, min_hit_rate=0.5, min_requests=5)
        self.assertEqual(
            (enough['labels']['cold']['warning'], enough['labels']['warm']['warning'], enough['warning']),
            (True, False, True),
        )
        # Old good history does not hide a currently cold window, and no threshold means no mark.
        mixed = [record(NOW - 5000, 'cold', 0, 10**6)] + low
        self.assertTrue(
            monitor.summarize(mixed, now=NOW, min_hit_rate=0.5, min_requests=5)['labels']['cold']['warning']
        )
        self.assertFalse(monitor.summarize(low, now=NOW, min_requests=1)['warning'])

    def test_failed_and_usage_less_requests_are_counted_without_inventing_tokens(self):
        records = [
            record(NOW, 'a', 100, 900),
            {'event': 'request', 'at': NOW, 'run': 'a', 'status': 'upstream_error'},
            record(NOW, 'a', 10, 0, status='failed', thinking_blocks_dropped=2),
            'not a record',
            {'event': 'other'},
        ]
        row = monitor.summarize(records, now=NOW)['labels']['a']
        self.assertEqual(
            (
                row['requests'],
                row['requests_with_usage'],
                row['failed_requests'],
                row['input_tokens'],
                row['thinking_blocks_dropped'],
            ),
            (3, 2, 2, 1010, 2),
        )
        self.assertIsNone(monitor.summarize([records[1]], now=NOW)['overall']['cache_hit_rate'])

    def test_grouping_by_key_or_session_and_run_names_from_a_batch(self):
        records = [
            record(NOW, 'codex-abcdef12', 0, 10),
            {**record(NOW, 'codex-abcdef12', 0, 10), 'key_label': 'task-b', 'codex_session': 'thread-2'},
        ]
        self.assertEqual(
            sorted(monitor.summarize(records, now=NOW, by='key')['labels']), ['default', 'task-b']
        )
        self.assertEqual(
            sorted(monitor.summarize(records, now=NOW, by='session')['labels']),
            ['thread-2', 'thread-codex-abcdef12'],
        )
        with tempfile.TemporaryDirectory() as folder:
            batch, home = Path(folder) / 'batch', Path(folder) / 'homes/one'
            (batch / 'runs/transport-n04/private/harness').mkdir(parents=True)
            home.mkdir(parents=True)
            (home / 'installation_id').write_text('abcdef12-3456-7890\n')
            (batch / 'runs/transport-n04/private/harness/codex-home.json').write_text(
                json.dumps({'codex_home': str(home)})
            )
            names = monitor.batch_names(batch)
            self.assertEqual(names, {'codex-abcdef12': 'transport-n04'})
            self.assertEqual(
                list(monitor.summarize(records, now=NOW, names=names)['labels']), ['transport-n04']
            )

    def test_once_mode_reads_a_log_file_and_exits_nonzero_only_on_a_marked_row(self):
        with tempfile.TemporaryDirectory() as folder:
            log = Path(folder) / 'metadata.jsonl'
            import time

            now = time.time()
            lines = [json.dumps(record(now - i, 'cold', 900, 100)) for i in range(3)]
            log.write_text('\n'.join(lines) + '\n' + '{"partly written')
            self.assertEqual(len(monitor.read_log(log)), 3)
            self.assertEqual(monitor.read_log(Path(folder) / 'missing.jsonl'), [])
            before = log.read_bytes()
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = monitor.main(
                    [str(log), '--once', '--json', '--min-hit-rate', '0.5', '--min-requests', '3']
                )
            summary = json.loads(output.getvalue())
            self.assertEqual(
                (code, summary['warning'], summary['labels']['cold']['window']['cache_hit_rate']),
                (2, True, 0.1),
            )
            with contextlib.redirect_stdout(io.StringIO()) as plain:
                self.assertEqual(monitor.main([str(log), '--once', '--min-hit-rate', '0.05']), 0)
                self.assertEqual(
                    monitor.main([str(log), '--once', '--min-hit-rate', '0.5', '--min-requests', '3']), 2
                )
            self.assertIn('WARNING low cache-hit rate', plain.getvalue())
            self.assertIn('estimate', plain.getvalue())
            self.assertEqual(log.read_bytes(), before)  # the monitor only reads


if __name__ == '__main__':
    unittest.main()
