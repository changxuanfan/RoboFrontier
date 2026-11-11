"""Antigravity usage accounting, fork evidence and delegate start, without a CLI."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from robofrontier.batch import metrics
from robofrontier.engines.antigravity import provenance
from robofrontier.engines.antigravity.driver import Driver, ForkUnacknowledged, usage_baseline, usage_delta
from robofrontier.engines.common.identity import fingerprint
from robofrontier.runtime import layout
from robofrontier.runtime.setup import write_json


def prepared(folder):
    """A run folder that records the current layout, as every prepared run does."""
    run = Path(folder)
    write_json(run/'private/inputs/manifest.json', {'engine': 'antigravity', **layout.manifest_record('antigravity')})
    return run


def varint(value):
    out = bytearray()
    while True:
        byte, value = value & 127, value >> 7
        out.append(byte | (128 if value else 0))
        if not value:
            return bytes(out)


def message(fields):
    return b''.join(varint(number << 3 | 2) + varint(len(value)) + value for number, value in fields.items())


def tool_metadata(tool_id, name, args):
    return message({4: message({1: tool_id.encode(), 2: name.encode(), 3: json.dumps(args).encode()})})


def history(home, session, rows):
    folder = Path(home)/'conversations'
    folder.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(folder/(session+'.db')) as db:
        db.execute('CREATE TABLE steps (idx INTEGER, step_type INTEGER, status INTEGER, step_payload BLOB, metadata BLOB)')
        db.executemany('INSERT INTO steps VALUES (?,?,?,?,?)', [(i, *row) for i, row in enumerate(rows)])


class UsageTests(unittest.TestCase):
    def test_new_session_starts_from_zero(self):
        self.assertEqual(usage_baseline([]), {'input_tokens': 0, 'output_tokens': 0, 'thinking_tokens': 0,
                                               'cache_read_tokens': 0})

    def test_fork_child_does_not_charge_inherited_thinking(self):
        # Values of the 2026-11-11 subscription preflight: the child's transcript holds
        # the inherited rows, without a thinking count.
        rows = [{'input_tokens': 22465, 'output_tokens': 431, 'cache_read_tokens': 0}, {'content': 'no usage'}]
        baseline = usage_baseline(rows)
        self.assertIsNone(baseline['thinking_tokens'])
        delta, totals = usage_delta({'input_tokens': 28723, 'output_tokens': 476, 'thinking_tokens': 393,
                                     'cache_read_tokens': 0, 'total_tokens': 29199}, baseline)
        self.assertEqual((delta['input_tokens'], delta['output_tokens']), (6258, 45))
        self.assertIsNone(delta['thinking_tokens'])
        later, _ = usage_delta({'input_tokens': 30000, 'output_tokens': 500, 'thinking_tokens': 400,
                                'cache_read_tokens': 0}, totals)
        self.assertEqual(later['thinking_tokens'], 7)

    def test_a_result_without_usage_keeps_the_running_totals(self):
        before = {'input_tokens': 100, 'output_tokens': 10, 'thinking_tokens': 5, 'cache_read_tokens': 0}
        delta, totals = usage_delta(None, before)
        self.assertEqual(totals, before)
        self.assertTrue(all(value is None for value in delta.values()))
        delta, _ = usage_delta({'input_tokens': 150, 'output_tokens': 12, 'thinking_tokens': 6,
                                'cache_read_tokens': 0}, totals)
        self.assertEqual(delta, {'input_tokens': 50, 'output_tokens': 2, 'thinking_tokens': 1, 'cache_read_tokens': 0})

    def test_reported_output_already_includes_thinking(self):
        with tempfile.TemporaryDirectory() as folder:
            run = prepared(folder)
            metrics.host_event(run, 'cli_turn_started', actor='Controller', session_id='s', events_name='one.jsonl')
            metrics.host_event(run, 'cli_turn_completed', actor='Controller', session_id='s', events_name='one.jsonl',
                phase='policy', duration_s=3.0, reported_cost_usd=None,
                usage_delta={'input_tokens': 3248, 'output_tokens': 129, 'thinking_tokens': 128, 'cache_read_tokens': 0})
            exported = metrics.export_metrics(run, 'antigravity')
        row = exported['rows'][0]
        self.assertEqual(row['usage']['output_tokens'], 129)
        self.assertEqual(row['thinking_tokens'], 128)


class ForkEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.parent, self.child = str(uuid.uuid4()), str(uuid.uuid4())
        self.args = {'op': 'delegate', 'data': {'scopes': []}}
        self.call = tool_metadata('tool-1', provenance.ROBOT_TOOL, {**self.args, 'toolSummary': 'Delegate'})
        self.binding = {'session_id': self.parent, 'actor': 'Controller', 'step': 2, 'trajectory': str(uuid.uuid4()),
                        'tool_id': 'tool-1', 'input_sha256': fingerprint(self.args), 'call_id': 'batch'}
        self.prefix = [(14, 3, b'in', b'm0'), (15, 3, b'plan', b'm1')]

    def write(self, parent_status=provenance.PENDING, child_prefix=None):
        history(self.home, self.parent, self.prefix + [(132, parent_status, b'call', self.call)])
        history(self.home, self.child, (child_prefix or self.prefix)
                + [(132, provenance.CANCELED, b'call', self.call), (provenance.FORK_NOTICE, 3, b'notice', None)])

    def test_proof_names_the_bound_call(self):
        self.write()
        proof = provenance.verify(self.home, self.parent, self.child, 2, binding=self.binding,
                                  snapshot=self.home/'snapshot')
        self.assertEqual(proof['pending_tool_id'], 'tool-1')
        self.assertEqual(proof['pending_input_sha256'], fingerprint(self.args))
        self.assertEqual(provenance.verify(self.home/'snapshot', self.parent, self.child, 2, binding=self.binding), proof)

    def test_parent_call_must_still_be_pending(self):
        self.write(parent_status=3)
        with self.assertRaisesRegex(ValueError, 'pending'):
            provenance.verify(self.home, self.parent, self.child, 2, binding=self.binding)
        with self.assertRaisesRegex(ValueError, 'pending'):
            provenance.verify(self.home, self.parent, self.child, 2)

    def test_another_tool_call_or_arguments_do_not_match_the_binding(self):
        self.write()
        for change in ({'tool_id': 'tool-2'}, {'input_sha256': fingerprint({'op': 'delegate', 'data': {}})}, {'step': 1}):
            with self.assertRaises(ValueError):
                provenance.verify(self.home, self.parent, self.child, 2, binding={**self.binding, **change})

    def test_saved_digest_covers_metadata(self):
        self.write()
        rows = provenance.steps(self.home, self.parent)
        changed = [(*rows[0][:4], b'other'), rows[1]]
        self.assertNotEqual(provenance.digest(rows[:2]), provenance.digest(changed))

    def test_changed_inherited_metadata_fails(self):
        self.write(child_prefix=[(14, 3, b'in', b'changed'), (15, 3, b'plan', b'm1')])
        with self.assertRaisesRegex(ValueError, 'inherited'):
            provenance.verify(self.home, self.parent, self.child, 2, binding=self.binding)


class DriverTests(unittest.TestCase):
    def driver(self, home, session):
        driver = Driver.__new__(Driver)
        driver.session, driver.lock, driver.inputs = session, threading.RLock(), {}
        patcher = patch.object(Driver, 'home', new=home)
        patcher.start()
        self.addCleanup(patcher.stop)
        return driver

    def test_unacknowledged_fork_keeps_the_child_id(self):
        parent, child = str(uuid.uuid4()), str(uuid.uuid4())
        driver = self.driver(Path('.'), parent)
        driver.rpc = lambda method, body: {'newCascadeId': child, 'forkedAtStepIndex': 7}
        with self.assertRaises(ForkUnacknowledged) as caught:
            driver.fork(3)
        self.assertEqual(caught.exception.child, child)
        self.assertEqual(driver.fork(7), child)

    def test_input_is_delivered_only_when_the_native_history_holds_it(self):
        with tempfile.TemporaryDirectory() as folder:
            session = str(uuid.uuid4())
            history(folder, session, [(14, 3, b'old', None), (15, 3, b'reply', None)])
            driver = self.driver(Path(folder), session)
            # Not written yet and the turn is no longer running: never delivered.
            self.assertFalse(driver.input_delivered('turn.jsonl', 1, alive=lambda: False))
            # Written to the pipe, but the session recorded no new input step.
            driver.inputs['turn.jsonl'] = 2
            self.assertFalse(driver.input_delivered('turn.jsonl', .2))
            with sqlite3.connect(Path(folder)/'conversations'/(session+'.db')) as db:
                db.execute('INSERT INTO steps VALUES (2, 14, 3, ?, NULL)', (b'new',))
            self.assertTrue(driver.input_delivered('turn.jsonl', 1))


class StopTests(unittest.TestCase):
    def test_one_failed_child_cleanup_does_not_skip_the_others(self):
        from robofrontier.engines.antigravity.orchestration import ForkSetup
        calls = []
        class Host:
            def __init__(self, name, fail):
                self.name, self.fail = name, fail
            def stop(self):
                calls.append((self.name, 'stop'))
                if self.fail:
                    raise RuntimeError('boom')
            def close_process(self):
                calls.append((self.name, 'close'))
        with tempfile.TemporaryDirectory() as folder:
            setup = ForkSetup.__new__(ForkSetup)
            setup.cancel_event, setup.launch_lock = threading.Event(), threading.RLock()
            setup.parent = type('Parent', (), {'run': prepared(folder)})()
            setup.hosts = {'a': Host('a', True), 'b': Host('b', False)}
            setup.request_stop()
            events = [json.loads(line) for line in
                      layout.path(Path(folder), 'host_log', 'claude').read_text().splitlines()]
        self.assertEqual(calls, [('a', 'stop'), ('a', 'close'), ('b', 'stop'), ('b', 'close')])
        self.assertTrue(setup.cancel_event.is_set())
        self.assertEqual([e['actor'] for e in events if e['event'] == 'delegate_cleanup_failed'], ['a'])


class SystemPromptTests(unittest.TestCase):
    def native(self, content):
        return {'agentConfig': {
            'mixinConfig': {'promptSections': [{'custom': {'title': 'System Prompt', 'content': content}},
                                               {'builtinName': 'user_information'}, {'builtinName': 'guidelines'}],
                            'tools': [{'name': 'manage_task', 'builtin': True}]},
            'customizationDiscovery': {'skills': {'inheritUser': True}, 'rules': {'inheritUser': True}}}}

    def test_only_the_frozen_prompt_remains_and_user_customizations_are_off(self):
        from robofrontier.engines.antigravity.context import DISCOVERY, policy_spec, prompt_only
        system = 'Role statement.\n\n# Rules\n- one'
        native = self.native('Role statement.')
        # As the CLI parses the agent file: the heading became a second section's title.
        native['agentConfig']['mixinConfig']['promptSections'].insert(1, {'custom': {'title': 'Rules', 'content': '- one'}})
        spec = policy_spec(native, 267000, system)
        agent = spec['agentConfig']
        self.assertEqual(agent['mixinConfig']['promptSections'], [{'custom': {'title': '', 'content': system}}])
        self.assertEqual(agent['cascadeConfig']['checkpointConfig']['maxTokenLimit'], 267000)
        self.assertTrue(all(agent['customizationDiscovery'][name]['inheritUser'] is False for name in DISCOVERY))
        self.assertTrue(prompt_only(spec, system))
        # As the CLI reads it back: an empty title is omitted.
        del agent['mixinConfig']['promptSections'][0]['custom']['title']
        self.assertTrue(prompt_only(spec, system))

    def test_a_native_session_with_other_sections_or_text_is_refused(self):
        from robofrontier.engines.antigravity.context import policy_spec, prompt_only
        system = 'Role statement.'
        self.assertFalse(prompt_only(self.native(system), system))
        spec = policy_spec(self.native(system), 267000, system)
        self.assertFalse(prompt_only(spec, system + ' Extra.'))
        spec['agentConfig']['customizationDiscovery']['rules']['inheritUser'] = True
        self.assertFalse(prompt_only(spec, system))
        with self.assertRaisesRegex(ValueError, 'frozen system prompt'):
            policy_spec(self.native('Another agent.'), 267000, system)


class PreflightBudgetTests(unittest.TestCase):
    def test_a_dollar_cap_is_refused_before_any_provider_call(self):
        from robofrontier import cli
        config = {'policy': {'engine': 'antigravity', 'profile': 'flash_subscription', 'effort': 'low'}}
        with patch('robofrontier.batch.prepare.load_env'), \
                patch('robofrontier.engines.antigravity.preflight.run_precheck') as precheck:
            for confirmed in (True, False):
                with self.assertRaisesRegex(ValueError, 'max-budget-usd'):
                    cli.preflight(config, confirm_spend=confirmed, max_budget_usd=0)
        precheck.assert_not_called()


if __name__ == '__main__':
    unittest.main()
