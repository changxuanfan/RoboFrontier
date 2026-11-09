import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from robofrontier.run_metrics import export_metrics, native_codex_sessions, native_subagent_calls, run_skills, usage


class RunMetricTests(unittest.TestCase):
    def test_claude_cache_writes_setup_and_duplicate_terminal_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp); output = run/'private/outputs'; output.mkdir(parents=True)
            first = {'event':'cli_turn_completed', 'actor':'Controller', 'session_id':'s', 'at':10,
                     'events_name':'turn1', 'phase':'policy', 'duration_s':4, 'reported_cost_usd':.1,
                     'usage':{'input_tokens':10,'cache_read_input_tokens':20,'cache_creation_input_tokens':30,'output_tokens':4}}
            setup = {**first, 'actor':'Delegate_a', 'events_name':'fork1', 'phase':'fork_setup', 'at':11,
                     'reported_cost_usd':.2}
            (output/'claude-host.jsonl').write_text('\n'.join(map(json.dumps,[first, first, setup]))+'\n')
            result = export_metrics(run, 'claude')
            self.assertEqual(result['usage']['input_tokens'],120)
            self.assertEqual(result['usage']['cached_input_tokens'],40)
            self.assertAlmostEqual(result['reported_cost_usd'],.3)
            self.assertTrue(result['usage_complete']); self.assertTrue(result['cost_complete'])
            self.assertEqual(result['phase_counts'], {'fork_setup':1,'policy':1})
            self.assertEqual(result['model_process_wall_seconds_union'],5)
            self.assertEqual(result['model_process_seconds_sum'],8)
            self.assertEqual(result['by_actor']['Delegate_a']['input_tokens'],60)
            self.assertEqual(result['fork_setup_seconds_sum'],4)

    def test_claude_delegate_fork_is_a_policy_turn_timed_by_its_fork_event(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp); output = run/'private/outputs'; output.mkdir(parents=True)
            turn = {'event':'cli_turn_completed', 'actor':'Delegate_a', 'session_id':'c', 'at':10,
                    'events_name':'turn1', 'phase':'policy', 'duration_s':4, 'reported_cost_usd':.1,
                    'usage':{'input_tokens':10,'output_tokens':4}}
            fork = {'event':'fork_created', 'actor':'Delegate_a', 'session_id':'c', 'parent':'p', 'duration_s':.5}
            (output/'claude-host.jsonl').write_text('\n'.join(map(json.dumps,[fork, turn]))+'\n')
            result = export_metrics(run, 'claude')
            self.assertEqual(result['phase_counts'], {'policy':1})
            self.assertEqual(result['fork_setup_seconds_sum'], .5)

    def test_codex_uses_first_last_then_cumulative_deltas_not_inherited_totals(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'private/outputs'; output.mkdir(parents=True)
            def event(total, cached, out):
                return {'event':'thread/tokenUsage/updated','thread_id':'child','actor':'Delegate_a',
                        'token_usage':{'total':{'inputTokens':total,'cachedInputTokens':cached,'outputTokens':out},
                                       'last':{'inputTokens':100,'cachedInputTokens':40,'outputTokens':5}}}
            first=event(1000,500,40); later=event(1250,650,50)
            (output/'codex-host.jsonl').write_text('\n'.join(map(json.dumps,[first,first,later]))+'\n')
            result=export_metrics(tmp,'codex')
            self.assertEqual(result['usage']['input_tokens'],350)
            self.assertEqual(result['usage']['cached_input_tokens'],190)
            self.assertEqual(result['usage']['output_tokens'],15)
            self.assertAlmostEqual(result['cache_hit_rate'],190/350)
            self.assertIsNone(result['reported_cost_usd'])

    def test_missing_cache_fields_are_unknown_and_legacy_reports_are_partial(self):
        self.assertIsNone(usage('claude', {'input_tokens':10})['input_tokens'])
        with tempfile.TemporaryDirectory() as tmp:
            evidence=Path(tmp)/'private/evidence'; evidence.mkdir(parents=True)
            (evidence/'old-summary.json').write_text(json.dumps({'actor':'Controller','record':{
                'summary':{'usage':{'input_tokens':10,'output_tokens':4},'total_cost_usd':.1}}}))
            result=export_metrics(tmp,'claude')
            self.assertFalse(result['cost_complete']); self.assertFalse(result['usage_complete'])
            self.assertEqual(result['evidence_scope'],'legacy_policy_only')
            self.assertEqual(result['reported_cost_usd'],.1)

    def test_claude_model_usage_is_aggregate_and_unfinished_turn_is_not_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'private/outputs';output.mkdir(parents=True)
            values={'inputTokens':10,'cacheReadInputTokens':20,'cacheCreationInputTokens':30,'outputTokens':4}
            done={'event':'cli_turn_completed','events_name':'turn1','usage':{'input_tokens':1},
                  'model_usage':{'model1':values,'model2':values},'reported_cost_usd':.1}
            started={'event':'cli_turn_started','events_name':'turn2'}
            (output/'claude-host.jsonl').write_text('\n'.join(map(json.dumps,[done,started]))+'\n')
            result=export_metrics(tmp,'claude')
            self.assertEqual(result['usage']['input_tokens'],120)
            self.assertEqual(result['usage']['output_tokens'],8)
            self.assertEqual(result['known_usage_subtotals']['input_tokens'],120)
            self.assertEqual(result['rows'][0]['usage_source'],'model_usage')
            self.assertEqual(result['unfinished_cli_turns'],1)
            self.assertFalse(result['usage_complete']);self.assertFalse(result['cost_complete'])

    def _claude_turns(self, tmp, *turns):
        output=Path(tmp)/'private/outputs';output.mkdir(parents=True)
        rows=[]
        for index,(session,actor,cumulative) in enumerate(turns):
            row={'event':'cli_turn_completed','events_name':f'turn{index}','session_id':session,'actor':actor,
                 'phase':'policy','at':index,'duration_s':1,'reported_cost_usd':.1,'usage':{'input_tokens':1}}
            if cumulative is not None:
                read,write,fresh,out=cumulative
                row['model_usage']={'m':{'inputTokens':fresh,'cacheReadInputTokens':read,
                                         'cacheCreationInputTokens':write,'outputTokens':out}}
            else: row['usage']=None
            rows.append(row)
        (output/'claude-host.jsonl').write_text('\n'.join(map(json.dumps,rows))+'\n')
        return export_metrics(tmp,'claude')

    def test_claude_model_usage_counts_each_session_once_across_persistent_turns(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self._claude_turns(tmp,('s','G',(800,100,100,10)),('s','G',(900,100,150,15)),
                                      ('other','K',(40,5,5,2)),('s','G',(1000,120,180,20)),('s','G',(1000,120,180,20)))
            self.assertEqual(result['usage']['input_tokens'],1300+50)
            self.assertEqual(result['usage']['cached_input_tokens'],1040)
            self.assertEqual(result['usage']['cache_write_input_tokens'],125)
            self.assertEqual(result['usage']['output_tokens'],22)
            self.assertEqual(result['by_actor']['G']['input_tokens'],1300)
            self.assertEqual(result['by_actor']['K']['input_tokens'],50)
            self.assertEqual([r['usage']['input_tokens'] for r in result['rows']],[1000,150,50,150,0])
            self.assertEqual(result['rows'][1]['usage']['cache_miss_input_tokens'],50)
            self.assertTrue(result['usage_complete'])

    def test_claude_counter_that_restarts_counts_from_zero_again(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self._claude_turns(tmp,('s','G',(800,100,100,10)),('s','G',(30,10,10,1)),('s','G',(60,10,20,2)))
            self.assertEqual([r['usage']['input_tokens'] for r in result['rows']],[1000,50,40])
            self.assertEqual(result['usage']['input_tokens'],1090)
            self.assertEqual(result['usage']['output_tokens'],12)

    def test_claude_turn_without_a_result_stays_unknown_and_next_turn_keeps_its_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            result=self._claude_turns(tmp,('s','G',(800,100,100,10)),('s','G',None),('s','G',(900,100,150,15)))
            self.assertIsNone(result['usage']['input_tokens'])
            self.assertEqual(result['known_usage_subtotals']['input_tokens'],1150)
            self.assertEqual(result['known_usage_subtotals']['output_tokens'],15)

    def _claude_transcripts(self, tmp, files):
        from datetime import datetime, timezone
        from robofrontier import run_layout
        def stamp(at): return datetime.fromtimestamp(at,timezone.utc).isoformat().replace('+00:00','Z')
        root=run_layout.path(tmp,'engine_config','claude')/'projects/p'
        for name,(session,records) in files.items():
            path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
            lines=[]
            for record in records:
                if record[0]=='compact':
                    lines.append({'type':'system','subtype':'compact_boundary','sessionId':session,'timestamp':stamp(record[1]),
                                  'compactMetadata':{'preTokens':record[2]}})
                else:
                    ident,at,read,write,fresh,out=record
                    lines.append({'type':'assistant','sessionId':session,'timestamp':stamp(at),'message':{'id':ident,
                        'usage':{'input_tokens':fresh,'cache_read_input_tokens':read,'cache_creation_input_tokens':write,'output_tokens':out}}})
            path.write_text('\n'.join(map(json.dumps,lines))+'\n')

    def _claude_results(self, tmp, *results):
        output=Path(tmp)/'private/outputs';output.mkdir(parents=True)
        rows=[]
        for index,(session,actor,at,cumulative) in enumerate(results):
            read,write,fresh,out=cumulative
            row={'event':'cli_turn_completed','events_name':f'turn{index}','session_id':session,'actor':actor,'phase':'policy',
                 'duration_s':2,'reported_cost_usd':.1,'usage':{'input_tokens':1},
                 'model_usage':{'m':{'inputTokens':fresh,'cacheReadInputTokens':read,'cacheCreationInputTokens':write,'outputTokens':out}}}
            if at is not None: row['at']=at
            rows.append(row)
        (output/'claude-host.jsonl').write_text('\n'.join(map(json.dumps,rows))+'\n')

    def test_claude_requests_after_the_last_result_count_from_transcripts(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._claude_results(tmp,('s','G',1000,(90,5,5,10)))
            self._claude_transcripts(tmp,{'s.jsonl':('s',[('before',900,90,5,5,10),('late',1100,1,0,0,1),('late',1101,70,20,10,5)]),
                                          's/subagents/agent-1.jsonl':('s',[('agent',1200,5,3,2,1)])})
            result=export_metrics(tmp,'claude')
            self.assertEqual(result['usage']['input_tokens'],100+100+10)
            self.assertEqual(result['usage']['cached_input_tokens'],165)
            self.assertEqual(result['usage']['cache_write_input_tokens'],28)
            self.assertEqual(result['usage']['output_tokens'],16)
            self.assertEqual(result['by_actor']['G']['input_tokens'],210)
            late=result['rows'][-1]
            self.assertEqual((late['phase'],late['usage_source'],late['actor']),('after_last_result','transcript','G'))
            self.assertEqual(result['usage_after_last_result'],{'sessions':1,'compactions':0,'compaction_pre_tokens':0})
            self.assertTrue(result['usage_complete']);self.assertFalse(result['cost_complete'])
            self.assertEqual(result['model_process_seconds_sum'],2)

    def test_claude_transcript_adds_nothing_when_every_request_has_a_result(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._claude_results(tmp,('s','G',1000,(90,5,5,10)),('old','K',None,(9,0,1,1)))
            self._claude_transcripts(tmp,{'s.jsonl':('s',[('before',900,90,5,5,10)]),'old.jsonl':('old',[('any',5000,9,0,1,1)])})
            result=export_metrics(tmp,'claude')
            self.assertEqual(result['usage']['input_tokens'],110)
            self.assertEqual(result['phase_counts'],{'policy':2})
            self.assertTrue(result['cost_complete'])

    def test_claude_fork_copies_count_once_and_only_when_no_result_covers_them(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._claude_results(tmp,('parent','Controller',1000,(90,5,5,10)),('child','Delegate_a',1500,(4,1,0,1)))
            self._claude_transcripts(tmp,{
                'parent.jsonl':('parent',[('old',900,90,5,5,10),('pending',1200,50,0,0,2)]),
                'child.jsonl':('child',[('old',900,90,5,5,10),('pending',1200,50,0,0,2),('own',1300,4,1,0,1)]),
                'silent.jsonl':('silent',[('old',900,90,5,5,10),('quiet',1400,7,0,0,1)])})
            result=export_metrics(tmp,'claude')
            self.assertEqual(result['usage']['input_tokens'],100+5+50+7)
            self.assertEqual(result['by_actor']['Controller']['input_tokens'],150)
            self.assertEqual(result['by_actor']['Delegate_a']['input_tokens'],5)
            self.assertEqual(result['known_usage_subtotals']['output_tokens'],14)

    def test_claude_compaction_after_the_last_result_leaves_usage_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._claude_results(tmp,('s','G',1000,(90,5,5,10)))
            self._claude_transcripts(tmp,{'s.jsonl':('s',[('compact',900,500),('compact',1100,270),('late',1200,10,0,0,1)])})
            result=export_metrics(tmp,'claude')
            self.assertEqual(result['usage']['input_tokens'],110)
            self.assertEqual(result['usage_after_last_result'],{'sessions':1,'compactions':1,'compaction_pre_tokens':270})
            self.assertFalse(result['usage_complete'])

    def test_collected_session_mapping_wins_over_stale_batch_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); run=root/'batch/profile/case'; run.mkdir(parents=True)
            (root/'batch/codex-home.json').write_text('{"codex_home":"/missing/original-server"}')
            session=root/'sessions/Controller.jsonl';session.parent.mkdir();session.write_text('{}\n')
            (root/'collection.json').write_text(json.dumps({'jobs':[{'run':'batch/profile/case','roles':[
                {'thread_id':'native','session':'sessions/Controller.jsonl'}]}]}))
            self.assertEqual(native_codex_sessions(run,'native'),[session.resolve()])

    def test_batch_home_does_not_fall_back_to_another_default_session(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); run=root/'batch/case';run.mkdir(parents=True)
            home=root/'other';(home/'sessions').mkdir(parents=True)
            (home/'sessions/native.jsonl').write_text('{}')
            (root/'batch/codex-home.json').write_text('{"codex_home":"/missing/original-server"}')
            with patch.dict('os.environ', {'CODEX_HOME':str(home)}):
                self.assertEqual(native_codex_sessions(run,'native'),[])
                self.assertEqual(native_codex_sessions(run,'native',home),[(home/'sessions/native.jsonl').resolve()])


class RunEvidenceTests(unittest.TestCase):
    def test_run_skills_lists_each_heading_of_the_shared_lessons_file(self):
        from robofrontier.policy_bootstrap import SKILLS_HEADER
        from robofrontier.run_layout import manifest_record
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp); (run/'private/inputs').mkdir(parents=True)
            self.assertEqual(run_skills(run), [])  # A legacy run has no lessons file.
            (run/'private/inputs/manifest.json').write_text(json.dumps(manifest_record('codex')))
            self.assertEqual(run_skills(run), [])
            lessons = run/'workspace/skills.md'; lessons.parent.mkdir()
            lessons.write_text(SKILLS_HEADER)
            self.assertEqual(run_skills(run)[0]['entries'], [])
            lessons.write_text(SKILLS_HEADER + '\n## [fix] Reopen before regrasp — Controller — tags: grasp, recovery\n'
                               'Content: x\n### rev 2 — Delegate_ab — open to 4 cm; faster\nContent: y\n'
                               '## loose heading\n### a loose revision\n')
            [record] = run_skills(run)
            self.assertEqual(record['path'], 'workspace/skills.md')
            self.assertEqual(record['entries'], [
                {'type': 'fix', 'title': 'Reopen before regrasp', 'role': 'Controller', 'tags': ['grasp', 'recovery'],
                 'revisions': [{'rev': 2, 'role': 'Delegate_ab', 'change': 'open to 4 cm; faster'}]},
                {'type': None, 'title': 'loose heading', 'role': None, 'tags': [],
                 'revisions': [{'rev': None, 'role': None, 'change': 'a loose revision'}]}])

    def test_a_linked_or_special_skills_file_is_reported_and_never_read(self):
        from robofrontier.run_layout import manifest_record
        with tempfile.TemporaryDirectory() as tmp:
            run = Path(tmp)/'run'; (run/'private/inputs/meta').mkdir(parents=True); (run/'workspace').mkdir()
            (run/'private/inputs/manifest.json').write_text(json.dumps(manifest_record('codex')))
            (run/'private/inputs/meta/x.md').write_text('## private heading\n')
            outside = Path(tmp)/'outside.md'; outside.write_text('## outside heading\n')
            lessons = run/'workspace/skills.md'
            for target in (outside, Path('../private/inputs/meta/x.md')):
                with self.subTest(target=str(target)):
                    lessons.symlink_to(target)
                    [record] = run_skills(run)
                    self.assertEqual(record['path'], 'workspace/skills.md')
                    self.assertEqual(record['entries'], []); self.assertIn('not read', record['issue'])
                    lessons.unlink()
            os.mkfifo(lessons)
            [record] = run_skills(run)  # must not block
            self.assertEqual(record['entries'], []); self.assertIn('not read', record['issue'])

    def test_native_subagent_calls_are_counted_but_robot_and_text_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            codex, claude = Path(tmp)/'rollout.jsonl', Path(tmp)/'session.jsonl'
            codex.write_text('\n'.join(json.dumps(r) for r in [
                {'type':'response_item','payload':{'type':'function_call','name':'spawn_agent','namespace':'collaboration'}},
                {'type':'response_item','payload':{'type':'function_call','name':'collaboration.wait_agent'}},
                {'type':'response_item','payload':{'type':'function_call','name':'robot','arguments':'{"op":"return_task"}'}},
                {'type':'response_item','payload':{'type':'message','content':[{'text':'I will not spawn_agent'}]}}])+'\n')
            claude.write_text('\n'.join(json.dumps(r) for r in [
                {'type':'assistant','message':{'content':[{'type':'tool_use','name':'Agent','input':{}}]}},
                {'type':'assistant','message':{'content':[{'type':'tool_use','name':'mcp__robot__robot','input':{'op':'send_message'}}]}},
                {'type':'user','message':{'content':'Task: place the blocks'}}])+'\n')
            self.assertEqual(native_subagent_calls([codex]), {'spawn_agent': 1, 'wait_agent': 1})
            self.assertEqual(native_subagent_calls([claude]), {'Agent': 1})
            self.assertEqual(native_subagent_calls([]), {})

    def test_cache_miss_has_one_definition_for_both_engines(self):
        # The same request: 100 input tokens, 90 read from cache, 9 of the rest written to cache.
        claude = usage('claude', {'input_tokens':1,'cache_read_input_tokens':90,'cache_creation_input_tokens':9,'output_tokens':4})
        codex = usage('codex', {'inputTokens':100,'cachedInputTokens':90,'outputTokens':4})
        self.assertEqual((claude['input_tokens'], claude['cache_miss_input_tokens'], claude['uncached_input_tokens']), (100, 10, 1))
        self.assertEqual((codex['input_tokens'], codex['cache_miss_input_tokens'], codex['uncached_input_tokens']), (100, 10, 10))
        self.assertIsNone(usage('codex', {'inputTokens':100})['cache_miss_input_tokens'])


class TranscriptCostTests(unittest.TestCase):
    PRICES = {'source': 'test', 'cache_write_5m_multiplier': 1.25, 'cache_write_1h_multiplier': 2.0,
              'models': {'m': {'input': 1.0, 'output': 10.0, 'cache_read': 0.1, 'long_prompt_threshold_tokens': 1000,
                               'long_prompt_input': 2.0, 'long_prompt_output': 20.0}}}

    def run_with(self, root, messages):
        from robofrontier import run_layout
        run = Path(root)/'run'; (run/'private/inputs').mkdir(parents=True)
        (run/'private/inputs/manifest.json').write_text(json.dumps({'engine': 'claude', **run_layout.manifest_record('claude')}))
        projects = run_layout.path(run, 'engine_config', 'claude')/'projects/p'; (projects/'s/subagents').mkdir(parents=True)
        lines = [json.dumps({'message': m}) for m in messages]
        (projects/'s.jsonl').write_text('\n'.join(lines[:-1])+'\n')
        (projects/'s/subagents/agent-1.jsonl').write_text(lines[-1]+'\n')
        return run

    def test_each_request_is_priced_once_at_its_prompt_tier(self):
        from robofrontier.run_metrics import claude_transcript_cost
        small = {'id': 'a', 'model': 'm', 'usage': {'input_tokens': 100, 'cache_read_input_tokens': 200, 'output_tokens': 10,
                 'cache_creation_input_tokens': 400, 'cache_creation': {'ephemeral_5m_input_tokens': 400, 'ephemeral_1h_input_tokens': 0}}}
        large = {'id': 'b', 'model': 'm', 'usage': {'input_tokens': 2000, 'output_tokens': 100}}
        with tempfile.TemporaryDirectory() as tmp:
            # Transcripts repeat a message once per content block; the sub-agent's request counts too.
            run = self.run_with(tmp, [small, small, large])
            result = claude_transcript_cost(run, self.PRICES)
            expected = (100*1 + 200*0.1 + 400*1.25 + 10*10)/1e6 + (2000*2 + 100*20)/1e6
            self.assertAlmostEqual(result['estimated_cost_usd'], expected)
            self.assertEqual(result['priced_requests'], 2)
            self.assertEqual(result['tokens']['output_tokens'], 110)
        with tempfile.TemporaryDirectory() as tmp:
            run = self.run_with(tmp, [small, {**large, 'model': 'third-party'}])
            result = claude_transcript_cost(run, self.PRICES)
            self.assertIsNone(result['estimated_cost_usd']); self.assertEqual(result['unpriced_models'], ['third-party'])

    def test_the_catalog_prices_the_anthropic_models_it_uses(self):
        from robofrontier.run_metrics import claude_pricing
        prices = claude_pricing()['models']
        self.assertEqual((prices['claude-haiku-5-5']['input'], prices['claude-haiku-5-5']['output']), (0.10, 0.50))


if __name__ == '__main__': unittest.main()
