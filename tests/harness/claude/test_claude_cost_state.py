import json
import tempfile
import unittest
import uuid
from pathlib import Path
from unittest.mock import patch

from harness.claude.test_claude_runner import MODEL_ENTRY, SECRET, fake_claude
from roboteam.harness.claude.session.runner import run_turn


class NativeCostStateTests(unittest.TestCase):
    def invoke(self, root, *, fork=False, reported=0.405, unknown=False, missing=False):
        run = root / 'run'
        (run / 'workspace').mkdir(parents=True, exist_ok=True)
        source = str(uuid.uuid4())
        child = str(uuid.uuid4())
        native = run / 'private/harness/config/projects/project' / f'{source}.jsonl'
        native.parent.mkdir(parents=True)
        if not missing:
            native.write_text(
                json.dumps(
                    {
                        'type': 'cost-state',
                        'sessionId': source,
                        'totalCostUSD': 0.4,
                        'hasUnknownModelCost': unknown,
                    }
                )
                + '\n'
            )
        expected = child if fork else source
        binary = fake_claude(
            root,
            f'''
argv=sys.argv[1:]
limit=float(argv[argv.index('--max-budget-usd')+1])
assert abs(limit-0.01) < 1e-10,limit
from pathlib import Path
state=Path(os.environ['CLAUDE_CONFIG_DIR'])/'projects/project/{expected}.jsonl'
with state.open('a') as saved:
 saved.write(json.dumps({{'type':'cost-state','sessionId':{expected!r},
  'totalCostUSD':{reported},'hasUnknownModelCost':False}})+'\\n')
print(json.dumps({{'type':'result','subtype':'success','is_error':False,
 'session_id':{expected!r},'result':'READY','total_cost_usd':{reported}}}))
''',
        )
        return run_turn(
            MODEL_ENTRY,
            MODEL_ENTRY['model'],
            'high',
            None,
            'Reply READY',
            run,
            {'PATH': '/usr/bin:/bin', 'KIMI_API_KEY': SECRET},
            binary=str(binary),
            resume=None if fork else source,
            session_id=child if fork else None,
            fork_from=source if fork else None,
            enable_robot=False,
            max_budget_usd=0.01,
            timeout=5,
        )

    def test_resume_and_fork_deduct_history_without_increasing_invocation_cap(self):
        for fork in (False, True):
            with self.subTest(fork=fork), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                record = self.invoke(root, fork=fork)
                self.assertEqual(record['exit_code'], 0, record)
                summary = record['summary']
                self.assertAlmostEqual(summary['total_cost_usd'], 0.005)
                self.assertEqual(summary['native_session_total_cost_usd'], 0.405)
                self.assertEqual(summary['cost_scope'], 'invocation')
                raw = json.loads((root / 'run/private/harness/turns/events.jsonl').read_text())
                self.assertEqual(raw['total_cost_usd'], 0.405)

    def test_missing_bookkeeping_keeps_the_entire_counter_as_an_upper_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = self.invoke(Path(tmp), missing=True)
            self.assertEqual(record['summary']['total_cost_usd'], 0.405)
            self.assertEqual(record['summary']['cost_scope'], 'session_total_upper_bound')

    def test_counter_decrease_is_unknown_instead_of_negative_spending(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = self.invoke(Path(tmp), reported=0.2)
            self.assertIsNone(record['summary']['total_cost_usd'])
            self.assertEqual(record['summary']['native_session_total_cost_usd'], 0.2)

    def test_unknown_native_model_cost_blocks_before_process_creation(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch('roboteam.harness.claude.session.runner.subprocess.Popen') as launch,
        ):
            with self.assertRaisesRegex(ValueError, 'unknown model cost'):
                self.invoke(Path(tmp), unknown=True)
            launch.assert_not_called()
