import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from robofrontier.batch.prepare import load_env, select_cases
from robofrontier.batch import codex_batch as benchmark
from robofrontier.batch.codex_batch import prepare_batch
from robofrontier.engines.codex.launch import profile, launch_config
from robofrontier.runtime.cli import fork_provenance
from robofrontier.tasks.families import prepare
from robofrontier.runtime.service import RuntimeService
from runtime.test_policy_probe import BudgetWorld
from fake_pipeline import fake_capture


class CliBenchmarkTests(unittest.TestCase):
    def test_native_subscription_launch_disables_inherited_mcp_without_changing_home(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); home = root/'native'; home.mkdir()
            config = home/'config.toml'
            content = '[mcp_servers.personal]\ncommand="unused"\n[profiles.other.mcp_servers.extra]\ncommand="unused"\n'
            config.write_text(content)
            output = root/'preflight'; output.mkdir()
            with patch.dict(os.environ, {'CODEX_HOME':str(home)}):
                result = launch_config(profile('luna_subscription'), output)
            self.assertIn('mcp_servers.personal.enabled=false', result['args'])
            self.assertIn('profiles.other.mcp_servers.extra.enabled=false', result['args'])
            self.assertEqual(config.read_text(), content)

    def test_the_personal_codex_config_is_not_a_layer_of_a_dedicated_home(self):
        # Codex does not load ~/.codex when CODEX_HOME points elsewhere; disabling its
        # servers would add half-defined entries that the app-server rejects.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); user = root/'user'; (user/'.codex').mkdir(parents=True)
            (user/'.codex/config.toml').write_text('[mcp_servers.personal_only]\ncommand="unused"\n')
            home = root/'dedicated'; home.mkdir(); (home/'config.toml').write_text('[mcp_servers.shared]\ncommand="unused"\n')
            output = user/'repo/runs/preflight'; output.mkdir(parents=True)
            with patch.dict(os.environ, {'CODEX_HOME': str(home)}), patch('pathlib.Path.home', return_value=user):
                args = ' '.join(launch_config(profile('luna_subscription'), output)['args'])
            self.assertIn('mcp_servers.shared.enabled=false', args)
            self.assertNotIn('personal_only', args)
            # When the personal folder is the active home it is still read.
            with patch.dict(os.environ, {'CODEX_HOME': str(user/'.codex')}), patch('pathlib.Path.home', return_value=user):
                self.assertIn('mcp_servers.personal_only.enabled=false', ' '.join(launch_config(profile('luna_subscription'), output)['args']))

    def test_profile_selected_standing_workers_use_direct_team_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            catalog=json.loads((benchmark.ROOT/'configs/models.json').read_text())['engines']['codex']
            catalog['profiles']['luna']['benchmark_topology']='peer'
            config=root/'models.json';config.write_text(json.dumps(catalog))
            prepared=prepare_batch(root/'batch',['luna'],cases=['transport-a04-d1'],config=config)
            run=Path(json.loads(prepared.read_text())['jobs'][0]['run_directory'])
            harness=json.loads((run/'private/inputs/harness.json').read_text())
            self.assertEqual((harness['topology'],harness['startup_protocol']),('peer','direct_team_v3'))

    def test_level_and_minimum_arms_select_four_tasks_without_launch(self):
        expected=['transport-a04-d2','mosaic-a04-6x12-d2','relay-a08-d2','dial-best5-n04-d2']
        with patch.object(benchmark.subprocess,'run') as launch:
            rows=select_cases(level=2,min_arms=True)
            self.assertEqual([row['case_id'] for row in rows],expected)
            self.assertEqual([row['arms'] for row in rows],[4,4,8,8])
            self.assertEqual(len(select_cases(level=1)),12)
            self.assertEqual(len(select_cases()),36)
            launch.assert_not_called()
        with self.assertRaisesRegex(ValueError,'Unknown task families'):select_cases(families=['typo'])
        with self.assertRaisesRegex(ValueError,'conflicting'):select_cases(cases=[expected[0]],level=1)

    def test_context_and_native_vision_are_required(self):
        for name in ('astra', 'luna', 'deepseek', 'kimi', 'glm'):
            p=profile(name)
            self.assertEqual((p['context_window'],p['auto_compact_token_limit']),(300000,267000))
        with tempfile.TemporaryDirectory() as tmp:
            file=Path(tmp)/'models.json'
            file.write_text(json.dumps(dict(context_window=400000,auto_compact_token_limit=350000,
                profiles={'small':dict(model='small',provider='openai',vision=True,context_capacity=128000)})))
            with self.assertRaisesRegex(ValueError,'capacity'):profile('small',file)
            file.write_text(json.dumps(dict(context_window=272000,auto_compact_token_limit=245000,
                profiles={'text':dict(model='text',provider='openai',vision=False,context_capacity=272000)})))
            with self.assertRaisesRegex(ValueError,'native images'):profile('text',file)

    def test_custom_provider_is_scoped_and_has_image_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            launch=launch_config(profile('deepseek'),Path(tmp))
            self.assertIn('model_provider="deepseek"',launch['args'])
            model=json.loads((Path(tmp)/'models.json').read_text())['models'][0]
            self.assertIn('image',model['input_modalities'])
            self.assertIsNone(model['tool_mode'])
            self.assertFalse(model['use_responses_lite'])
            self.assertNotIn('experimental_bearer_token',json.dumps(launch))

    def test_failed_preflight_cannot_relabel_an_older_pass(self):
        selected=profile('astra')
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp)/'runs/engineering/model-compatibility/astra'
            target.mkdir(parents=True)
            (target/'report.json').write_text(json.dumps({'passed':True,'profile_sha256':'old'}))
            with patch.object(benchmark,'ROOT',Path(tmp)),patch.object(benchmark,'runs_root',return_value=Path(tmp)/'runs'),\
                    patch.object(benchmark,'profile',return_value=selected),\
                    patch.object(benchmark,'launch_config',return_value={}),\
                    patch('sys.argv',['benchmark','preflight','--models','astra']),\
                    patch.dict(os.environ),\
                    patch.object(benchmark.subprocess,'run',return_value=SimpleNamespace(returncode=1)):
                with self.assertRaises(SystemExit):benchmark.main()
            self.assertFalse(json.loads((target/'report.json').read_text())['passed'])

    def test_models_share_fresh_private_dial_instance_but_not_runtime(self):
        with tempfile.TemporaryDirectory() as tmp:
            file=prepare_batch(Path(tmp)/'batch',['astra','deepseek'],cases=['dial-best5-n04-d1'])
            batch=json.loads(file.read_text());a,b=[Path(j['run_directory']) for j in batch['jobs']]
            self.assertNotEqual(a,b)
            self.assertEqual((a/'private/inputs/suite-code.json').read_bytes(),(b/'private/inputs/suite-code.json').read_bytes())
            self.assertEqual(batch['model_calls'],0)
            for run in (a,b):
                cfg=json.loads((run/'private/inputs/harness.json').read_text())
                self.assertEqual(cfg['observation_renderer'],'classic')
                self.assertFalse(cfg['record_realtime_video'])
                self.assertFalse(any('suite-code' in str(p) for p in (run/'public').rglob('*')))

    def test_env_is_literal_and_existing_values_win(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'RF_EXISTING':'existing'}, clear=True):
            env=Path(tmp)/'.env'
            env.write_text("RF_EXISTING=other\nRF_LITERAL='$(touch nope)'\nRF_EMPTY=\n")
            load_env(env)
            self.assertEqual(os.environ['RF_EXISTING'], 'existing')
            self.assertEqual(os.environ['RF_LITERAL'], '$(touch nope)')
            self.assertEqual(os.environ['RF_EMPTY'], '')
            env.write_text('INVALID KEY=value\n')
            with self.assertRaisesRegex(ValueError, 'line 1'): load_env(env)

    def test_launch_works_without_local_model_cache(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {'CODEX_HOME':tmp}):
            output=Path(tmp)/'launch'; output.mkdir()
            launch=launch_config(profile('luna'), output)
            self.assertEqual(launch['model'],'gpt-6-luna')
            self.assertIn('image',json.loads((output/'models.json').read_text())['models'][0]['input_modalities'])

    def test_changed_cli_or_catalog_rejects_old_preflight_before_start(self):
        import hashlib
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); folder=root/'batch'; run=folder/'astra'/'case'
            (run/'private/inputs').mkdir(parents=True)
            launch={'profile':{'provider':'openai'}}
            (run/'private/inputs/codex.json').write_text(json.dumps(launch))
            (run/'private/inputs/models.json').write_text('{"models": []}')
            (folder/'batch.json').write_text(json.dumps({'status':'prepared_not_started','jobs':[
                {'profile':'astra','run_directory':str(run),'status':'prepared'}]}))
            receipt=root/'runs/engineering/model-compatibility/astra/report.json'
            receipt.parent.mkdir(parents=True)
            profile_hash=hashlib.sha256(json.dumps(launch['profile'],sort_keys=True).encode()).hexdigest()
            receipt.write_text(json.dumps({'passed':True,'profile_sha256':profile_hash,
                                           'catalog_sha256':'old','codex_version':'old'}))
            with patch.object(benchmark,'ROOT',root),patch.object(benchmark,'runs_root',return_value=root/'runs'),\
                    patch.object(benchmark,'verify_inputs',return_value=[]),\
                    patch.object(benchmark.subprocess,'check_output',return_value='codex new\n'),\
                    patch.object(benchmark.subprocess,'run') as start:
                with self.assertRaisesRegex(ValueError,'rerun preflight'):
                    benchmark.run_batch(folder,1)
                start.assert_not_called()

    def test_released_policy_service_enforces_24h_without_host(self):
        # A run frozen before the active-time clock counts 24 h of wall time from START.
        from runtime.test_active_time import old_protocol_prepare
        with tempfile.TemporaryDirectory() as tmp:
            run=old_protocol_prepare('transport-a04-d1',Path(tmp)/'run')
            s=RuntimeService(run,BudgetWorld,fake_capture)
            try:
                s.store.update_agent('Controller',ready=True,thread_id='engineering-only')
                s.store.start();s.store.put('start_at',time.time()-86401)
                s.pump()
                self.assertEqual(s.store.get('termination_reason'),'wall_limit')
                self.assertEqual(s.store.get('lifecycle'),'ended')
                self.assertTrue(s.shutdown)
                self.assertEqual(json.loads((run/'private/outputs/budget-cutoff.json').read_text())['protocol']['wall_limit_s'],86400)
            finally:s.close()

    def test_released_policy_service_enforces_24h_of_active_time_without_host(self):
        with tempfile.TemporaryDirectory() as tmp:
            run=prepare('transport-a04-d1',Path(tmp)/'run')
            s=RuntimeService(run,BudgetWorld,fake_capture)
            try:
                s.store.update_agent('Controller',ready=True,thread_id='engineering-only')
                s.store.start();s.store.put('start_at',time.time()-86401);s.store.put('physics_state','running')
                s.pump()
                self.assertEqual(s.store.get('lifecycle'),'running')
                s.store.put('active_s',86400.);s.policy_budget.active=None  # read again, as a restarted owner would
                s.pump()
                self.assertEqual(s.store.get('termination_reason'),'wall_limit')
                self.assertTrue(s.shutdown)
                cutoff=json.loads((run/'private/outputs/budget-cutoff.json').read_text())
                self.assertEqual((cutoff['protocol']['wall_limit_s'],cutoff['protocol']['clock']),(86400,'active_time_v1'))
                self.assertAlmostEqual(cutoff['active_s'],86400.,delta=1.)
            finally:s.close()

    def test_paginated_fork_lineage_ignores_unrelated_matching_filenames(self):
        parent='00000000-0000-0000-0000-000000000001';child='00000000-0000-0000-0000-000000000002'
        def line(ordinal,typ,payload):return dict(ordinal=ordinal,type=typ,payload=payload)
        with tempfile.TemporaryDirectory() as tmp,patch.dict(os.environ,{'CODEX_HOME':tmp}):
            folder=Path(tmp)/'sessions';folder.mkdir()
            a=line(0,'session_meta',{'id':parent});b=line(1,'response_item',{'role':'user'})
            (folder/f'rollout-{parent}_a.jsonl').write_text(json.dumps(a)+'\n'+json.dumps(b)+'\n')
            (folder/f'rollout-{parent}_b.jsonl').write_text(json.dumps(line(2,'response_item',{'role':'assistant'}))+'\n')
            # Each paginated segment carries its own session metadata in practice.
            (folder/f'rollout-{parent}_b.jsonl').write_text(json.dumps(line(2,'session_meta',{'id':parent}))+'\n')
            (folder/f'rollout-{child}.jsonl').write_text(json.dumps(line(3,'session_meta',{
                'id':child,'forked_from_id':parent,'forked_from_ordinal_exclusive':3}))+'\n')
            (folder/f'rollout-{parent}_other.jsonl').write_text(json.dumps(line(0,'session_meta',{'id':child}))+'\n')
            p=fork_provenance(parent,child)
            self.assertEqual(p['source_ordinal'],3)
            self.assertEqual(p['source_thread_id'],parent)


if __name__=='__main__':unittest.main()
