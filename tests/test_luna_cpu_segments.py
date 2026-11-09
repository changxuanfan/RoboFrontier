"""luna_cpu performance report on a continued run: downtime between segments is not elapsed time."""

import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

from scripts.luna_cpu import performance_report


class PerformanceSegmentTests(unittest.TestCase):
    def test_elapsed_and_turn_time_exclude_the_gap_between_segments(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)/'run'; (run/'private/state').mkdir(parents=True); (run/'private/outputs').mkdir()
            db = sqlite3.connect(run/'private/state/runtime.sqlite')
            db.executescript('''CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE actions(id TEXT PRIMARY KEY, actor TEXT, status TEXT NOT NULL, value TEXT NOT NULL);
                CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT, created REAL, kind TEXT, actor TEXT, value TEXT);''')
            db.execute("INSERT INTO events(created,kind) VALUES (0,'START'),(1000,'POLICY_WALL_LIMIT')")
            db.execute("INSERT INTO actions VALUES ('a','A','completed',?)", (json.dumps({'started_at': 200, 'finished_at': 250}),))
            # Segment 0 ended at 300 (host lost); segment 1 started at 500.
            db.execute("INSERT INTO meta VALUES ('segments',?)", (json.dumps([
                {'index': 0, 'started_at': 0, 'ended_at': 300}, {'index': 1, 'started_at': 500, 'downtime_s': 200}]),))
            db.commit(); db.close()
            host = [{'at': 100, 'event': 'turn/started', 'thread_id': 't', 'turn_id': '1'},  # never completed
                    {'at': 600, 'event': 'turn/started', 'thread_id': 't', 'turn_id': '2'},
                    {'at': 700, 'event': 'turn/completed', 'thread_id': 't', 'turn_id': '2'}]
            (run/'private/outputs/codex-host.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in host))
            batch = Path(tmp)/'batch'; batch.mkdir()
            (batch/'batch.json').write_text(json.dumps({'jobs': [{'case_id': 'c', 'run_directory': str(run)}]}))
            job = performance_report(batch)['jobs'][0]
            self.assertEqual((job['elapsed_s'], job['downtime_s'], job['segments']), (800, 200, 2))
            self.assertEqual(job['any_model_turn_wall_s'], 300)
            self.assertEqual(job['any_action_wall_s'], 50)


if __name__ == '__main__':
    unittest.main()
