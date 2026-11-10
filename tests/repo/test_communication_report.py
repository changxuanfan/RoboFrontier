import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from unittest import mock

from scripts.communication_report import main, report_run


def empty_run(run):
    (run / 'private/state').mkdir(parents=True)
    (run / 'private/outputs').mkdir(parents=True)
    conn = sqlite3.connect(run / 'private/state/runtime.sqlite')
    conn.executescript('create table agents(id text,value text); create table events(seq integer,created real,kind text,actor text,value text);')
    for name in ('A', 'B'):
        conn.execute('insert into agents values (?,?)', (name, json.dumps({'kind':'worker','thread_id':'thread-'+name})))
    conn.commit()
    return conn


class CommunicationReportTest(unittest.TestCase):
    def test_legacy_claude_run_reads_its_own_host_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            empty_run(run).close()
            (run / 'private/inputs').mkdir(parents=True)
            (run / 'private/inputs/manifest.json').write_text(json.dumps({'engine': 'claude'}))
            (run / 'private/outputs/claude-host.jsonl').write_text(json.dumps(
                {'event': 'robot_tool_completed', 'op': 'wait_events', 'actor': 'A', 'duration_s': 2.5})+'\n')
            result = report_run(run)
            self.assertTrue(result['host_log_found'])
            self.assertEqual(result['roles']['A']['wait_events_tool_duration']['count'], 1)

    def test_missing_host_log_reports_unknown_not_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            empty_run(run).close()
            result = report_run(run)
            self.assertFalse(result['host_log_found'])
            self.assertIsNone(result['roles']['A']['wait_events_tool_duration'])
            self.assertIsNone(result['roles']['A']['token_usage_updates'])

    def test_batch_status_comes_from_the_engineering_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            batch, output = Path(tmp)/'batch', Path(tmp)/'report.json'
            (batch/'control').mkdir(parents=True)
            (batch/'batch.json').write_text(json.dumps({'status': 'prepared_not_started', 'jobs': [],
                'layout': 'batch-v2', 'layout_paths': {'engineering_status': 'control/engineering-status.json'}}))
            (batch/'control/engineering-status.json').write_text(json.dumps({'status': 'running'}))
            with mock.patch('sys.argv', ['communication_report', str(batch), '--output', str(output)]):
                main()
            self.assertEqual(json.loads(output.read_text())['status'], 'running')

    def test_role_attribution_and_overlaps(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)
            out = run / 'private/outputs'
            conn = empty_run(run)
            events = [
                (1, 1, 'MESSAGE_PERSISTED', 'A', {}),
                (2, 3, 'DELIVERY_PREPARED', 'B', {'messages':[{'created_at':1}]}),
                (3, 4, 'WAKE_SENT', 'Meta', {'actor':'B'}),
                (4, 7, 'ACTION_FINISHED', 'A', {'started_at':2,'finished_at':7,'arm':'A'}),
                (5, 8, 'ACTION_FINISHED', 'B', {'started_at':5,'finished_at':8,'arm':'B'}),
            ]
            conn.executemany('insert into events values (?,?,?,?,?)', [(s,t,k,a,json.dumps(v)) for s,t,k,a,v in events])
            conn.commit()
            conn.close()
            (out/'codex-host.jsonl').write_text(json.dumps({'event':'thread/tokenUsage/updated','thread_id':'thread-A','at':4,
                'token_usage':{'total':{'inputTokens':100},'last':{'inputTokens':20}}})+'\n')
            result = report_run(run)
            self.assertEqual(result['roles']['A']['messages_sent'], 1)
            self.assertEqual(result['roles']['B']['wake_sent'], 1)
            self.assertEqual(result['roles']['B']['delivery_delay']['mean_s'], 2)
            self.assertEqual(result['roles']['A']['latest_recorded_token_total']['inputTokens'], 100)
            self.assertEqual(result['pairwise_action_overlap_s'], 2)


if __name__ == '__main__':
    unittest.main()
