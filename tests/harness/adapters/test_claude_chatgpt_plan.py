import json
import http.server
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import queue
import time
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

from roboteam.launch.claude_prepare import model_entry
from roboteam.harness.claude.session import runner

from roboteam.harness.adapters.gpt_in_claude import gateway


class ChatGPTPlanProfileTests(unittest.TestCase):
    def selected(self, endpoint):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'models.json'
            path.write_text(json.dumps({'schema': 'roboteam.claude-models.v1', 'models': {'plan': {
                'provider': 'openai_chatgpt_plan', 'model': 'gpt-6.1-sol', 'effort': 'high',
                'env_key': 'LOCAL_GATEWAY_KEY', 'base_url': endpoint}}}))
            return model_entry('plan', path)

    def test_plain_http_is_limited_to_literal_loopback(self):
        self.assertEqual(self.selected('http://127.0.0.1:18461')['model'], 'gpt-6.1-sol')
        for endpoint in ('http://example.com', 'http://127.0.0.1.example.com', 'http://127.0.0.1:18461?token=x'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                self.selected(endpoint)

    def test_managed_price_cannot_change_permission_settings(self):
        with self.assertRaises(ValueError):
            runner.build_command('gpt-6.1-sol', 'high', 'mcp.json', 'hello', managed_settings={'permissions': {}})
        settings = {'modelPricing': {'overrides': {'gpt-6.1-sol': {'input': 2, 'output': 10, 'cacheRead': .1, 'cacheWrite': 2.5}}}}
        command = runner.build_command('gpt-6.1-sol', 'high', 'mcp.json', 'hello', managed_settings=settings)
        self.assertEqual(json.loads(command[command.index('--managed-settings')+1]), settings)
        ordinary = runner.build_command('claude-haiku-5-5', 'high', 'mcp.json', 'hello')
        self.assertNotIn('--managed-settings', ordinary)

    def test_native_context_capacity_is_explicit_and_not_inherited_from_the_shell(self):
        selected={'provider':'openai_chatgpt_plan','model':'gpt-6.1-sol','base_url':'http://127.0.0.1:18461',
                  'env_key':'LOCAL_GATEWAY_KEY','context_capacity':300000}
        env=runner.build_env(selected,{'LOCAL_GATEWAY_KEY':'fixture','CLAUDE_CODE_MAX_CONTEXT_TOKENS':'1000000'},'fixture-config')
        self.assertEqual(env['CLAUDE_CODE_MAX_CONTEXT_TOKENS'],'300000')
        for invalid in (True,'300000',99999,1000001):
            with self.subTest(invalid=invalid),self.assertRaises(ValueError):
                runner.build_env({**selected,'context_capacity':invalid},{'LOCAL_GATEWAY_KEY':'fixture'},'fixture-config')

    def test_transport_identity_uses_actual_native_launch_ids(self):
        parent=str(uuid.uuid4());child=str(uuid.uuid4())
        selected={'provider':'openai_chatgpt_plan'}
        for command,identity,source in ((['claude','--session-id',parent],parent,None),
            (['claude','--resume',parent],parent,None),
            (['claude','--resume',parent,'--fork-session','--session-id',child],child,parent)):
            env={};runner.bind_gateway_session(selected,command,env)
            self.assertIn('X-RoboTeam-Session: '+identity,env['ANTHROPIC_CUSTOM_HEADERS'])
            self.assertEqual('X-RoboTeam-Fork-Source' in env['ANTHROPIC_CUSTOM_HEADERS'],bool(source))
        unchanged={'ANTHROPIC_CUSTOM_HEADERS':'Existing: header'}
        runner.bind_gateway_session({'provider':'anthropic'},['claude'],unchanged)
        self.assertEqual(unchanged['ANTHROPIC_CUSTOM_HEADERS'],'Existing: header')

    @unittest.skipUnless(shutil.which('claude'), 'requires the real pinned CLI and a local-only stub')
    def test_native_full_persistent_request_translates_without_model_calls(self):
        failures, observed = [], []
        class Stub(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                if not self.path.startswith('/v1/messages') or 'count_tokens' in self.path:
                    self.send_error(404)
                    return
                body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                edit=next((t for t in body.get('tools',[]) if t['name']=='Edit'),{})
                defaults={k:v['default'] for k,v in edit.get('input_schema',{}).get('properties',{}).items() if 'default' in v}
                observed.append({'roles': [m.get('role') for m in body['messages']], 'tools': len(body.get('tools', [])), 'edit_defaults':defaults})
                try:
                    gateway.to_responses(body)
                except Exception as error:
                    failures.append(str(error))
                message = gateway.to_message({'id': 'resp_stub', 'model': gateway.MODEL, 'status': 'completed',
                    'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'READY'}]}],
                    'usage': {'input_tokens': 10, 'output_tokens': 1}})
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Connection', 'close')
                self.end_headers()
                for event, data in gateway.message_events(message):
                    self.wfile.write(('event: '+event+'\ndata: '+json.dumps(data)+'\n\n').encode())
                self.close_connection = True
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Stub)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                model_entry_value = {'model': gateway.MODEL, 'provider': 'openai_chatgpt_plan',
                                 'context_capacity':300000,'env_key': 'LOCAL_GATEWAY_KEY',
                                 'base_url': f'http://127.0.0.1:{server.server_port}'}
                env = runner.build_env(model_entry_value, {'PATH': os.environ['PATH'], 'LOCAL_GATEWAY_KEY': 'local-stub-key'}, temporary)
                settings = {'sandbox': {'enabled': True, 'allowUnsandboxedCommands': False}}
                argv = runner.build_command(gateway.MODEL, 'high', json.dumps({'mcpServers': {}}), None,
                                            settings=settings, stream_input=True, system_prompt='Reply READY; do not call tools.')
                message = {'type': 'user', 'message': {'role': 'user', 'content': 'Reply READY.'}, 'session_id': ''}
                result = subprocess.run(argv, input=json.dumps(message)+'\n', text=True, capture_output=True,
                                        env=env, cwd=temporary, timeout=60)
                self.assertEqual(result.returncode, 0, result.stderr[-1500:])
                self.assertTrue(observed)
                self.assertGreaterEqual(observed[0]['tools'], 6)
                self.assertIs(observed[0]['edit_defaults'].get('replace_all'),False,observed[0])
                self.assertEqual(failures, [])
                summary=runner.summarize(result.stdout.splitlines())
                self.assertEqual(summary['model_usage'][gateway.MODEL]['contextWindow'],300000)
        finally:
            server.shutdown()
            server.server_close()

    @unittest.skipUnless(shutil.which('claude'), 'requires the real pinned CLI and a local-only stub')
    def test_native_compacts_at_267k_instead_of_the_unknown_model_167k_default(self):
        requests=[];failures=[]
        replay_temporary=tempfile.TemporaryDirectory()
        self.addCleanup(replay_temporary.cleanup)
        replay=gateway.ReplayStore(Path(replay_temporary.name)/'replay.sqlite')
        class Stub(http.server.BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_POST(self):
                body=self.rfile.read(int(self.headers.get('Content-Length','0')))
                if 'count_tokens' in self.path:
                    self.send_response(404);self.send_header('Content-Length','0')
                    self.send_header('Connection','close');self.end_headers();self.close_connection=True;return
                payload=json.loads(body)
                try:request=gateway.to_responses(payload,replay=replay)
                except gateway.ProtocolError as error:
                    failures.append({'error':str(error),'calls':len(requests),'assistant_blocks':[
                        [{'type':b.get('type'),'text':b.get('text','')[:160]} for b in m.get('content',[]) if isinstance(b,dict)]
                        if isinstance(m.get('content'),list) else m.get('content','')[:160]
                        for m in payload['messages'] if m['role']=='assistant']})
                    self.send_error(400,'Fixture rejected replay');return
                requests.append(True)
                size=170000 if len(requests)<3 else 269000 if len(requests)==3 else 1000
                response={'id':'resp_fixture_'+str(len(requests)),'model':gateway.MODEL,'status':'completed',
                    'output':[{'id':'msg_fixture_'+str(len(requests)),'type':'message','role':'assistant',
                        'phase':'final_answer','status':'completed',
                        'content':[{'type':'output_text','text':'READY_'+str(len(requests))}]}],
                    'usage':{'input_tokens':size,'output_tokens':1}}
                message=gateway.to_message(response)
                replay.remember(request,response,message)
                self.send_response(200);self.send_header('Content-Type','text/event-stream')
                self.send_header('Connection','close');self.end_headers();self.close_connection=True
                for event,data in gateway.message_events(message):
                    self.wfile.write(('event: '+event+'\ndata: '+json.dumps(data)+'\n\n').encode())
                self.wfile.flush()
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),Stub)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as temporary:
                selected={'provider':'openai_chatgpt_plan','model':gateway.MODEL,'context_capacity':300000,
                          'env_key':'LOCAL_GATEWAY_KEY','base_url':f'http://127.0.0.1:{server.server_port}'}
                env=runner.build_env(selected,{'PATH':os.environ['PATH'],'LOCAL_GATEWAY_KEY':'fixture'},temporary)
                env['CLAUDE_CODE_AUTO_COMPACT_WINDOW']='300000'
                command=runner.build_command(gateway.MODEL,'high',json.dumps({'mcpServers':{}}),None,
                    enable_robot=False,stream_input=True,system_prompt='Reply READY.')
                process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,
                                         text=True,env=env,cwd=temporary)
                output=queue.Queue()
                def read():
                    for line in process.stdout:output.put(json.loads(line))
                    output.put(None)
                reader=threading.Thread(target=read,daemon=True);reader.start()
                try:
                    for turn in range(4):
                        process.stdin.write(json.dumps({'type':'user','message':{'role':'user','content':f'Turn {turn}: reply READY.'}})+'\n')
                        process.stdin.flush();deadline=time.monotonic()+60
                        while True:
                            event=output.get(timeout=max(.1,deadline-time.monotonic()))
                            self.assertIsNotNone(event,'Native CLI exited before the result')
                            if event.get('type')=='result':
                                self.assertEqual(failures,[])
                                self.assertEqual(event['modelUsage'][gateway.MODEL]['contextWindow'],300000)
                                break
                        if turn<3:self.assertEqual(len(requests),turn+1,'Premature compaction below the 267k threshold')
                    self.assertGreaterEqual(len(requests),5,'Compaction must remain enabled above 267k')
                finally:
                    process.stdin.close()
                    try:process.wait(timeout=10)
                    except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
                    process.stdout.close();reader.join(timeout=2)
        finally:server.shutdown();server.server_close()

    @unittest.skipUnless(shutil.which('claude'), 'requires the real pinned CLI and local fixture responses')
    def test_native_tools_resume_and_fork_replay_exact_outputs_after_gateway_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            fixture=root/'fixture.txt';fixture.write_text('Native tool fixture.\n')
            calls=[];audits=[];outputs={}

            class Response(io.BytesIO):
                status=200
                def getheader(self,name,default=None):return default

            class Connection:
                def reply(self,payload):
                    if calls:
                        baseline=next((identity for identity,output in reversed(list(outputs.items())) if output[0] in payload['input']),None)
                        if baseline is None:raise AssertionError('Missing exact replay baseline')
                        expected=outputs[baseline]
                        start=next((i for i,item in enumerate(payload['input']) if item==expected[0]),None)
                        if start is None or payload['input'][start:start+len(expected)]!=expected:
                            raise AssertionError('Native CLI did not preserve complete original output items')
                    number=len(calls)+1
                    if number==1:
                        output=[{'id':'rs_native','type':'reasoning','summary':[],'encrypted_content':'fixture-opaque'},
                            {'id':'msg_native','type':'message','role':'assistant','phase':'commentary','status':'completed',
                             'content':[{'type':'output_text','text':'Reading the fixture.','annotations':[]}]},
                            {'id':'fc_native','type':'function_call','namespace':'robot_frontier','status':'completed',
                             'call_id':'call_native','name':'Read','arguments':'{\n  "file_path": '+json.dumps(str(fixture))+'\n}'}]
                    elif number==2:
                        output=[{'id':'fc_native_edit','type':'function_call','namespace':'robot_frontier','status':'completed',
                            'call_id':'call_native_edit','name':'Edit','arguments':json.dumps({'file_path':str(fixture),
                            'old_string':'Native tool fixture.','new_string':'Native edited fixture.'})}]
                    else:
                        output=[{'id':'msg_native_'+str(number),'type':'message','role':'assistant',
                            'phase':'final_answer','status':'completed',
                            'content':[{'type':'output_text','text':'READY_'+str(number),'annotations':[]}]}]
                    identity='resp_native_'+str(number)
                    outputs[identity]=output;calls.append(payload)
                    result={'id':identity,'model':gateway.MODEL,'status':'completed','output':output,
                        'input_transformations':[], 'prompt_cache_diagnostics':{'type':'cache_hit'},
                        'usage':{'input_tokens':100,'output_tokens':5,'input_tokens_details':{'cached_tokens':80}}}
                    return result

            def start(port):
                (root/'api-key.txt').write_text('fixture-api-key')
                server=gateway.Gateway(('127.0.0.1',port),root/'api-key.txt','fixture-key',root/'metadata.jsonl',
                                       auth_mode='openai_api_key')
                server.store=SimpleNamespace(access_token=lambda:'fixture-only')
                sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'helpers'))
                from chatgpt_websocket_fixture import ProviderSocket
                server.transport=gateway.WebSocketTransport(server.store,lambda token:ProviderSocket(Connection().reply))
                server.audit=lambda record:audits.append(record)
                threading.Thread(target=server.serve_forever,daemon=True).start()
                return server

            server=start(0);port=server.server_port
            selected={'provider':'openai_chatgpt_plan','model':gateway.MODEL,'context_capacity':300000,
                      'env_key':'LOCAL_GATEWAY_KEY','base_url':f'http://127.0.0.1:{port}'}
            env=runner.build_env(selected,{'PATH':os.environ['PATH'],'LOCAL_GATEWAY_KEY':'fixture-key'},root/'native-config')
            def turn(resume=None,fork=False):
                args=runner.build_command(gateway.MODEL,'high',json.dumps({'mcpServers':{}}),'Reply READY.',
                    session_id=str(uuid.uuid4()) if fork else None,resume=resume if not fork else None,
                    fork_from=resume if fork else None,
                    settings={'sandbox':{'enabled':True,'allowUnsandboxedCommands':False}},
                    system_prompt='Use Read when requested, then reply READY.')
                runner.bind_gateway_session(selected,args,env)
                process=subprocess.run(args,cwd=root,env=env,text=True,capture_output=True,timeout=90)
                self.assertEqual(process.returncode,0,process.stderr[-1000:]+process.stdout[-2500:])
                summary=runner.summarize(process.stdout.splitlines())
                self.assertEqual(summary['turn_status'],'ended',process.stdout[-2500:])
                self.assertEqual(summary['model_usage'][gateway.MODEL]['contextWindow'],300000)
                return summary
            try:
                first=turn()
                self.assertEqual(first['result_text'],'READY_3')
                self.assertEqual(first['tool_calls'],2)
                self.assertEqual(fixture.read_text(),'Native edited fixture.\n')
                self.assertEqual(calls[1]['input'][2:5],outputs['resp_native_1'])
                server.shutdown();server.server_close();server=start(port)
                resumed=turn(first['session_id'])
                self.assertEqual(resumed['session_id'],first['session_id'])
                self.assertEqual(resumed['result_text'],'READY_4')
                forked=turn(first['session_id'],fork=True)
                self.assertNotEqual(forked['session_id'],first['session_id'])
                self.assertEqual(forked['result_text'],'READY_5')
                self.assertEqual(len(calls),5)
                completed=[r for r in audits if r.get('completed')]
                self.assertEqual(len(completed),5)
                self.assertTrue(all(r['auth']=='openai_api_key' for r in completed))
                self.assertTrue(all(r['input_transformations']==[] for r in completed))
                self.assertEqual(completed[-1]['comparison_response_id'],'resp_native_4')
                self.assertTrue(any(r.get('native_default_response_ids') for r in completed))
            finally:server.shutdown();server.server_close()

    @unittest.skipUnless(shutil.which('claude'), 'requires the real pinned CLI and local fixture responses')
    def test_native_pending_tool_fork_keeps_exact_replay_and_identity_checks(self):
        from roboteam.harness.claude.checks import blocked_precheck as blocked
        from roboteam.harness.claude.checks import preflight
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);audits=[];calls=[];fork_projection=[]
            class Response(io.BytesIO):
                status=200
                def getheader(self,name,default=None):return default
            class Connection:
                def reply(self,p):
                    calls.append(p);number=len(calls)
                    latest=next((item for item in reversed(p['input']) if item.get('role')=='user'),{})
                    text=str(latest.get('content',''))
                    if 'tool-free setup turn' in text or not p.get('tools'):answer='READY'
                    elif p['input'][-1].get('type')=='function_call_output':answer='green red'
                    elif 'Call the robot tool once' in text:
                        output=[{'id':'fc_pending_'+str(number),'type':'function_call','call_id':'call_pending_'+str(number),
                            'namespace':'robot_frontier','name':'mcp__robot__robot','status':'completed',
                            'arguments':'{ "op": "observe", "data": {}, "views": ["top"] }'}]
                        answer=None
                    else:answer='READY'
                    if answer is not None:output=[{'id':'msg_pending_'+str(number),'type':'message','role':'assistant',
                        'phase':'final_answer','status':'completed','content':[{'type':'output_text','text':answer}]}]
                    result={'id':'resp_pending_'+str(number),'model':gateway.MODEL,'status':'completed','output':output,
                            'usage':{'input_tokens':100,'output_tokens':10}}
                    return result
            server=gateway.Gateway(('127.0.0.1',0),root/'unused-auth.json','fixture-key')
            server.store=SimpleNamespace(access_token=lambda:'fixture-only');server.audit=audits.append
            sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'helpers'))
            from chatgpt_websocket_fixture import ProviderSocket
            server.transport=gateway.WebSocketTransport(server.store,lambda token:ProviderSocket(Connection().reply))
            threading.Thread(target=server.serve_forever,daemon=True).start()
            selected={**model_entry('sol_chatgpt_plan'),'base_url':f'http://127.0.0.1:{server.server_port}',
                      'env_key':'LOCAL_GATEWAY_KEY'}
            try:
                translate=gateway.to_responses
                def capture(payload,*args,**kwargs):
                    if kwargs.get('fork_source'):
                        fork_projection.extend(m['content'] for m in payload['messages'] if m['role']=='assistant')
                    return translate(payload,*args,**kwargs)
                with patch.object(blocked,'model_entry',return_value=selected),patch.object(preflight.preflight_probe,'choose',return_value=('green','red')),patch.object(gateway,'to_responses',side_effect=capture):
                    receipt=blocked.run_blocked_precheck('fixture',root/'check',2,
                        {'PATH':os.environ['PATH'],'LOCAL_GATEWAY_KEY':'fixture-key'})
                self.assertTrue(receipt['passed'],{'receipt':receipt,'fork_projection':fork_projection,'audits':audits})
                self.assertTrue(receipt['checks']['native_history_prefix'])
                self.assertTrue(receipt['checks']['parent_blocked'])
            finally:server.shutdown();server.server_close()


if __name__ == '__main__':
    unittest.main()
