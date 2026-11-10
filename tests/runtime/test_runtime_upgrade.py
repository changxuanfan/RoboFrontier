"""A stopped upgrade authorizes one next segment without relaxing automatic retry."""
import hashlib
import json
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier.runtime import segments as run_segments, upgrade as runtime_upgrade
from robofrontier.runtime.setup import verify_inputs, write_json
from robofrontier.runtime.store import RuntimeStore
from engines.test_engine_parity import prepared
from runtime.test_run_segments import FakeReader


class RuntimeUpgradeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.run = prepared(Path(self.temp.name).resolve(), 'codex').resolve()
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite'); self.addCleanup(self.store.close)
        for key, value in {'lifecycle':'interrupted', 'physics_state':'stopped', 'dispatch_paused':True,
                           'integrity_valid':True, 'segment':1, 'start_at':time.time()-30,
                           'segments':[{'index':0}, {'index':1,'started_at':time.time()-20}]}.items():
            self.store.put(key, value)
        folder = run_segments.output_dir(self.run, 1)
        write_json(folder/'seal.json', {'sealed':True,'fresh_observation':True,'unresolved_action_ids':[]})
        self.store.begin_call('settled', 'Controller', 'gripper', {'state':'open'})
        self.store.finish_call('settled', {'execution_status':'completed'})
        self.before = self.store.call('settled')
        self.manifest = self.run/'private/inputs/manifest.json'
        value = json.loads(self.manifest.read_text())
        name = 'robofrontier/runtime/egress_pause.py'
        del value['source_sha256'][name]
        (self.run/'private/inputs/frozen-source'/name).unlink()
        notice = self.run/'private/inputs/bootstrap/network-resume.md'
        value['input_sha256'].pop(str(notice.relative_to(self.run)), None); notice.unlink()
        write_json(self.manifest, value)
        self.original = self.manifest.read_bytes()
        self.source = self.run/'private/inputs/frozen-source'
        frame = (FakeReader(9), 41, 12.5, np.arange(9, dtype=float))
        patcher = patch.object(run_segments, '_last_frame', lambda run, segment: frame)
        patcher.start(); self.addCleanup(patcher.stop)

    def upgrade(self):
        return runtime_upgrade.upgrade(self.run, self.store, previous_source=self.source,
                                       reason='Operator authorized one further outage continuation',
                                       expected_segment=1, expected_ledger=runtime_upgrade.ledger(self.store))

    def test_explicit_upgrade_preserves_parent_and_receipts_and_is_consumed_once(self):
        grant = self.upgrade()
        parent = self.run/'private/inputs/runtime-upgrades/2/parent-manifest.json'
        self.assertEqual(parent.read_bytes(), self.original)
        self.assertEqual(verify_inputs(self.run), [])
        self.assertEqual(self.store.call('settled'), self.before)
        self.assertEqual(run_segments.retry_eligibility(self.run, self.store), (False,'already continued automatically once; continue by hand (robofrontier continue)'))
        note = run_segments.prepare_retry(self.run, self.store, 'Authorized outage restore',
                                         manual=True, manual_authorization=grant)
        self.assertEqual(note['segment'], 2)
        self.assertEqual(self.store.call('settled'), self.before)
        self.assertFalse(run_segments.retry_eligibility(self.run, self.store, manual_authorization=grant)[0])
        self.assertEqual(run_segments.AUTOMATIC_CONTINUES, 1)

    def test_unsettled_or_live_state_cannot_be_upgraded(self):
        self.store.begin_call('pending', 'Controller', 'move', {})
        with self.assertRaisesRegex(ValueError, 'unsettled'): self.upgrade()
        self.assertEqual(self.manifest.read_bytes(), self.original)

    def test_a_world_that_closed_by_itself_upgrades_with_the_actions_its_seal_lists(self):
        self.store.begin_call('lost', 'Controller', 'move', {'robot': 'A'})
        self.store.db.execute("INSERT INTO actions VALUES ('lost','Controller','uncertain','{}')"); self.store.db.commit()
        folder = run_segments.output_dir(self.run, 1)
        with self.assertRaisesRegex(ValueError, 'unsettled'): runtime_upgrade.stopped(self.run, self.store)
        write_json(folder/'seal.json', {'sealed': True, 'fresh_observation': False, 'owner_was_live': False,
                                        'unresolved_action_ids': ['other']})
        with self.assertRaisesRegex(ValueError, 'differ'): runtime_upgrade.stopped(self.run, self.store)
        write_json(folder/'seal.json', {'sealed': True, 'fresh_observation': False, 'owner_was_live': False,
                                        'unresolved_action_ids': ['lost']})
        runtime_upgrade.stopped(self.run, self.store)
        # A live world's seal still has to be clean.
        write_json(folder/'seal.json', {'sealed': True, 'fresh_observation': True, 'owner_was_live': True,
                                        'unresolved_action_ids': ['lost']})
        with self.assertRaisesRegex(ValueError, 'unsettled'): runtime_upgrade.stopped(self.run, self.store)

    def test_changed_ledger_cannot_use_the_grant(self):
        grant = self.upgrade()
        self.store.begin_call('new', 'Controller', 'observe', {})
        self.store.finish_call('new', {'ok':True})
        self.assertFalse(run_segments.retry_eligibility(self.run, self.store, manual_authorization=grant)[0])

    def test_modified_authorization_is_rejected(self):
        grant = self.upgrade(); file = self.run/grant
        note = json.loads(file.read_text()); note['to_segment']=3; write_json(file, note)
        self.assertFalse(run_segments.retry_eligibility(self.run, self.store, manual_authorization=grant)[0])

    def test_normal_finish_cannot_be_overridden(self):
        self.store.event('TEAM_FINISH_PROPOSED', 'Controller', {})
        with self.assertRaisesRegex(ValueError, 'normal end'): self.upgrade()

    def test_a_runtime_upgrade_cannot_change_the_policy_prompts(self):
        name = 'prompts/rules.md'; file = self.source/name
        file.write_text(file.read_text()+'\nHistorical policy text\n')
        value = json.loads(self.manifest.read_text())
        value['source_sha256'][name] = hashlib.sha256(file.read_bytes()).hexdigest()
        write_json(self.manifest, value)
        with self.assertRaisesRegex(ValueError, 'policy prompts'): self.upgrade()


if __name__ == '__main__': unittest.main()
