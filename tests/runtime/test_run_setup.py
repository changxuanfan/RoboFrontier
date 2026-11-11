import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from robofrontier.runtime.setup import prepare_run,verify_inputs
from robofrontier.tasks.config import ROOT,load_task,load_harness, startup_protocol
from robofrontier.runtime.store import RuntimeStore

class SetupTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def test_prepare_is_offline_and_copies_task_roles_skill_and_source(self):
        run=prepare_run(self.root/'run')
        self.assertEqual(verify_inputs(run),[])
        self.assertEqual(json.loads((run/'public/inputs/task.json').read_text())['id'],load_task()['id'])
        # New runs show letter labels where their videos do.
        self.assertEqual(json.loads((run/'private/inputs/harness.json').read_text())['robot_labels'],'beside-robot-v1')
        store=RuntimeStore(run/'private/state/runtime.sqlite')
        try:
            self.assertEqual(store.get('lifecycle'),'prepared')
            self.assertEqual(store.agent('Meta')['kind'],'manager')
            self.assertEqual(store.agent('Controller')['kind'],'team-controller')
            self.assertTrue(all(v['thread_id'] is None for v in store.agents().values()))
            self.assertEqual(store.actions(),{})
        finally:store.close()
        self.assertIsNone(json.loads((run/'private/state/connections/A.json').read_text())['url'])
        self.assertTrue((run/'public/inputs/skill/references/tools.md').exists())
        # run-v6: one shared lessons file in the only writable folder, frozen first
        # messages and access table, and Meta's files kept private.
        self.assertEqual(json.loads((run/'private/inputs/manifest.json').read_text())['layout'],'run-v6')
        self.assertTrue((run/'workspace/skills.md').read_text().startswith('# Run skills'))
        self.assertTrue((run/'public/inputs/rules.md').is_file())
        self.assertFalse((run/'public/inputs/role_tools.js').exists())
        self.assertFalse((run/'public/inputs/roles/Meta.md').exists())
        self.assertTrue((run/'private/inputs/meta/Meta.md').is_file())
        for name in ('system.md','A.md','Controller.md','resume.md','model-restart.md'):
            self.assertTrue((run/'private/inputs/bootstrap'/name).is_file(),name)
        access=json.loads((run/'private/inputs/policy-access.json').read_text())
        self.assertEqual(access['filesystem'][str(run.resolve()/'workspace')],'write')
        self.assertEqual(access['filesystem'][str(run.resolve()/'private')],'deny')
        self.assertFalse(access['network']);self.assertFalse(access['web_search'])
        self.assertTrue((run/'private/inputs/frozen-source/robofrontier/runtime/scheduling.py').exists())
        self.assertFalse((run/'private/outputs/global-realtime.mp4').exists())
        before=(run/'private/inputs/manifest.json').read_bytes()
        with self.assertRaises(ValueError):prepare_run(run)
        self.assertEqual((run/'private/inputs/manifest.json').read_bytes(),before)
    def test_snapshot_tamper_is_reported(self):
        run=prepare_run(self.root/'run')
        p=run/'public/inputs/task.json';p.write_text('{}')
        self.assertIn('input:public/inputs/task.json',verify_inputs(run))
    def test_private_scene_or_harness_tamper_is_also_detected(self):
        run=prepare_run(self.root/'run')
        p=run/'private/inputs/task.json';v=json.loads(p.read_text());v['level']=3;p.write_text(json.dumps(v))
        self.assertIn('private:task.json',verify_inputs(run))
    def test_invalid_task_rejected_before_directory_creation(self):
        task=load_task();task['scene_sha256']='0'*64
        p=self.root/'bad.json';p.write_text(json.dumps(task))
        with self.assertRaises(ValueError):prepare_run(self.root/'run',p)
        self.assertFalse((self.root/'run').exists())

    def test_frozen_source_is_checked_and_observations_are_not_fixed_inputs(self):
        run=prepare_run(self.root/'run')
        (run/'public/observations/new.png').write_bytes(b'not real pixels')
        self.assertEqual(verify_inputs(run),[])
        (run/'private/inputs/frozen-source/robofrontier/runtime/scheduling.py').write_text('# changed')
        self.assertIn('frozen:robofrontier/runtime/scheduling.py',verify_inputs(run))

    def test_run_local_experience_is_mutable_and_not_imported_into_next_run(self):
        run=prepare_run(self.root/'first')
        experience=run/'public/results/A-experience.md'
        experience.write_text('Observed trial result; applicable only to the tested conditions.\n')
        store=RuntimeStore(run/'private/state/runtime.sqlite')
        try:store.checkpoint_work('A','working','Experience reference: '+str(experience))
        finally:store.close()
        experience.write_text('Updated after contrary observation; previous inference uncertain.\n')
        self.assertEqual(verify_inputs(run),[])
        fresh=prepare_run(self.root/'second')
        self.assertEqual(list((fresh/'public/results').iterdir()),[])
        store=RuntimeStore(fresh/'private/state/runtime.sqlite')
        try:self.assertEqual(store.agent('A')['note'],'')
        finally:store.close()
        self.assertEqual(verify_inputs(fresh),[])

    def test_legacy_layout_is_not_migrated_or_modified(self):
        from robofrontier.runtime.service import RuntimeService
        from fake_pipeline import FakeWorld,fake_capture
        run=self.root/'legacy';(run/'private').mkdir(parents=True)
        old=run/'private/manifest.json';old.write_text('{"schema_version":2}')
        before=old.read_bytes()
        with self.assertRaises(ValueError):RuntimeService(run,FakeWorld,fake_capture)
        self.assertEqual(old.read_bytes(),before)
        self.assertFalse((run/'private/state').exists())

    def test_eight_workers_prepare_with_same_skill_in_both_topologies(self):
        p=ROOT/'benchmark/transport/transport-a08-d1/task.json'
        skill=(Path(__file__).resolve().parents[2]/'prompts/skills/robot-collaboration/SKILL.md').read_bytes()
        for topology in ('hierarchical','peer'):
            cfg=load_harness();cfg['topology']=topology;cfg['startup_protocol']=startup_protocol(topology)
            c=self.root/(topology+'.json');c.write_text(json.dumps(cfg))
            run=prepare_run(self.root/topology,p,c)
            roles=json.loads((run/'public/inputs/roles.json').read_text())['roles']
            self.assertEqual(sum(v['kind']=='worker' for v in roles.values()),8)
            self.assertEqual('Controller' in roles,topology=='hierarchical')
            self.assertEqual((run/'public/inputs/skill/SKILL.md').read_bytes(),skill)
            self.assertEqual(verify_inputs(run),[])

    def test_hierarchical_controller_name_and_legacy_config(self):
        for name in ('Controller', 'Coordinator'):
            with self.subTest(name=name):
                cfg=load_harness();cfg['topology']='hierarchical';cfg['coordinator']=name
                config=self.root/(name+'.json');config.write_text(json.dumps(cfg))
                run=prepare_run(self.root/('run-'+name),harness_path=config)
                roles=json.loads((run/'public/inputs/roles.json').read_text())
                self.assertEqual(roles['coordinator'],'Controller')
                self.assertEqual(roles['roles']['Controller']['kind'],'team-controller')
                self.assertTrue((run/'public/inputs/roles/Controller.md').exists())
                self.assertEqual(verify_inputs(run),[])

if __name__=='__main__':unittest.main()
