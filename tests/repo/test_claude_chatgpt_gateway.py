import base64
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import io
import json
from pathlib import Path
import sys
import http.client
import threading
import tempfile
import unittest
import uuid
from types import SimpleNamespace
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[2] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import claude_chatgpt_gateway as gateway


def stream(*documents):
    return io.BytesIO(b''.join(b'data: ' + json.dumps(d).encode() + b'\n\n' for d in documents))


class MessagesBridgeTests(unittest.TestCase):
    def dynamic_fork_fixture(self,root,legacy=False):
        parent,child=str(uuid.uuid4()),str(uuid.uuid4())
        project=root/('run/private/claude-config/projects/project' if legacy else 'run/private/engine/config/projects/project');project.mkdir(parents=True)
        control={'type':'text','text':'No response requested.'}
        def row(kind,content,model=None,previous=None):
            result={'type':kind,'uuid':str(uuid.uuid4()),'parentUuid':previous,'sessionId':parent,
                    'message':{'role':kind,'content':content}}
            if model is not None:result.update(isApiErrorMessage=False);result['message']['model']=model
            return result
        source=[row('user','prior')]
        source.append(row('assistant',[control],'<synthetic>',source[-1]['uuid']))
        source.append(row('assistant',[{'type':'text','text':'done'}],gateway.MODEL,source[-1]['uuid']))
        from roboteam.engines.claude.provenance import history
        digest=gateway.hashlib.sha256(json.dumps(history(source,parent),sort_keys=True).encode()).hexdigest()
        child_rows=[{**r,'sessionId':child} for r in source]
        child_rows.append({**row('user','child setup',previous=source[-1]['uuid']),'sessionId':child})
        later=row('user','parent advanced',previous=source[-1]['uuid'])
        (project/(parent+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in source+[later]))
        child_path=project/(child+'.jsonl');child_path.write_text(''.join(json.dumps(r)+'\n' for r in child_rows))
        claim_dir=root/'run/private/claude-forks';claim_dir.mkdir()
        claim_path=claim_dir/'Delegate_fixture.json'
        claim={'status':'claimed','actor':'Delegate_fixture','child_session':child,'parent_session':parent,
            'source_session':parent,'tool_permissions':'gated','parent_history_sha256':digest,
            'first_input_sha256':gateway.hashlib.sha256(b'child setup').hexdigest()}
        claim_path.write_text(json.dumps(claim));claim_path.chmod(0o600)
        index=root/'index.json';index.write_text(json.dumps({parent:str(project/(parent+'.jsonl'))}));index.chmod(0o600)
        replay=gateway.ReplayStore(root/'replay.sqlite',index)
        request=gateway.to_responses({'messages':[{'role':'user','content':'prior'}]},session_id=parent,replay=replay)
        response=self.response();replay.remember(request,response,gateway.to_message(response))
        payload={'messages':[{'role':'user','content':'prior'},{'role':'assistant','content':[control]},
            {'role':'assistant','content':'done'},{'role':'user','content':'child setup'}]}
        return replay,parent,child,payload,claim_path,child_path,index

    def test_new_fork_can_inherit_a_control_before_any_provider_output_and_survive_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary)
            replay,parent,child,payload,claim,child_path,index=self.dynamic_fork_fixture(root)
            request=gateway.to_responses(payload,replay=replay,session_id=child,fork_source=parent)
            self.assertEqual(request['input'].native_controls,['resume_no_response'])
            self.assertIn({'role':'assistant','content':'No response requested.'},request['input'])
            self.assertIn(self.response()['output'][0],request['input'])
            self.assertNotIn(child,json.loads(index.read_text()))
            restarted=gateway.ReplayStore(root/'replay.sqlite',index)
            self.assertEqual(gateway.to_responses(payload,replay=restarted,session_id=child)['input'].native_controls,
                             ['resume_no_response'])

    def test_dynamic_fork_rejects_modified_inherited_history_wrong_input_or_uncertain_claim(self):
        for field in ('copy','input','uncertain','parent_digest'):
            with self.subTest(field=field),tempfile.TemporaryDirectory() as temporary:
                replay,parent,child,payload,claim_path,child_path,index=self.dynamic_fork_fixture(Path(temporary))
                if field=='copy':
                    rows=[json.loads(r) for r in child_path.read_text().splitlines()]
                    rows[0]['message']['content']='modified inherited input'
                    child_path.write_text(''.join(json.dumps(r)+'\n' for r in rows))
                else:
                    claim=json.loads(claim_path.read_text())
                    claim[{'input':'first_input_sha256','uncertain':'status','parent_digest':'parent_history_sha256'}[field]]= 'uncertain' if field=='uncertain' else '0'*64
                    claim_path.write_text(json.dumps(claim))
                with self.assertRaises(gateway.ProtocolError):
                    gateway.to_responses(payload,replay=replay,session_id=child,fork_source=parent)

    def test_dynamic_fork_accepts_the_native_preflight_config_layout(self):
        with tempfile.TemporaryDirectory() as temporary:
            replay,parent,child,payload,claim,child_path,index=self.dynamic_fork_fixture(Path(temporary),legacy=True)
            request=gateway.to_responses(payload,replay=replay,session_id=child,fork_source=parent)
            self.assertEqual(request['input'].native_controls,['resume_no_response'])

    def test_dynamic_fork_waits_for_native_transcript_flush_before_accepting(self):
        with tempfile.TemporaryDirectory() as temporary:
            replay,parent,child,payload,claim,child_path,index=self.dynamic_fork_fixture(Path(temporary))
            full=child_path.read_text();child_path.write_text(full.splitlines()[0]+'\n')
            timer=threading.Timer(.15,lambda:child_path.write_text(full));timer.start()
            try:
                request=gateway.to_responses(payload,replay=replay,session_id=child,fork_source=parent)
                self.assertEqual(request['input'].native_controls,['resume_no_response'])
            finally:timer.join()

    def test_root_resume_control_requires_a_native_session_bound_synthetic_witness(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sid=str(uuid.uuid4());native=root/(sid+'.jsonl')
            block={'type':'text','text':'No response requested.'}
            event={'type':'assistant','sessionId':sid,'isApiErrorMessage':False,
                   'message':{'model':'<synthetic>','content':[block]}}
            native.write_text(json.dumps(event)+'\n');index=root/'index.json'
            index.write_text(json.dumps({sid:str(native)}));index.chmod(0o600)
            replay=gateway.ReplayStore(root/'replay.sqlite',index)
            original=gateway.to_responses({'messages':[{'role':'user','content':'original'}]},session_id=sid,replay=replay)
            response=self.response();replay.remember(original,response,gateway.to_message(response))
            payload={'messages':[{'role':'user','content':'resumed setup'}, {'role':'assistant','content':[block]},
                                 {'role':'user','content':'continue'}]}
            empty=gateway.ReplayStore(root/'empty-replay.sqlite',index)
            self.assertEqual(gateway.to_responses(payload,session_id=sid,replay=empty)['input'].native_controls,
                             ['resume_no_response'])
            restored=gateway.to_responses(payload,session_id=sid,replay=replay)['input']
            self.assertEqual(restored.native_controls,['resume_no_response'])
            self.assertEqual(restored[1],{'role':'assistant','content':'No response requested.'})
            with self.assertRaises(gateway.ProtocolError):
                gateway.to_responses(payload,session_id=str(uuid.uuid4()),replay=replay)
            doubled={'messages':payload['messages']+[{'role':'assistant','content':[block]}]}
            with self.assertRaises(gateway.ProtocolError):gateway.to_responses(doubled,session_id=sid,replay=replay)
            with native.open('a') as stream:stream.write(json.dumps(event)+'\n')
            self.assertEqual(gateway.to_responses(doubled,session_id=sid,replay=replay)['input'].native_controls,
                             ['resume_no_response','resume_no_response'])
            payload['messages'][1]['content']=[{'type':'text','text':'Untracked output'}]
            with self.assertRaises(gateway.ProtocolError):gateway.to_responses(payload,session_id=sid,replay=replay)

    def test_resume_control_cannot_use_model_output_or_an_unknown_response_lineage(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sid=str(uuid.uuid4());native=root/(sid+'.jsonl')
            block={'type':'text','text':'No response requested.'}
            event={'type':'assistant','sessionId':sid,'isApiErrorMessage':False,
                   'message':{'model':gateway.MODEL,'content':[block]}}
            native.write_text(json.dumps(event)+'\n');index=root/'index.json'
            index.write_text(json.dumps({sid:str(native)}));index.chmod(0o600)
            replay=gateway.ReplayStore(root/'replay.sqlite',index)
            payload={'messages':[{'role':'assistant','content':[block]}]}
            with self.assertRaises(gateway.ProtocolError):gateway.to_responses(payload,session_id=sid,replay=replay)
            original=gateway.to_responses({'messages':[]},session_id=sid,replay=replay)
            response=self.response();replay.remember(original,response,gateway.to_message(response))
            with self.assertRaises(gateway.ProtocolError):gateway.to_responses(payload,session_id=sid,replay=replay)

    def test_root_control_waits_for_flush_and_rejects_an_in_place_rewrite(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);sid=str(uuid.uuid4());native=root/(sid+'.jsonl');native.write_text('')
            index=root/'index.json';index.write_text(json.dumps({sid:str(native)}));index.chmod(0o600)
            witness=gateway.NativeControls(index)
            event={'type':'assistant','sessionId':sid,'isApiErrorMessage':False,
                'message':{'model':'<synthetic>','content':[{'type':'text','text':'No response requested.'}]}}
            timer=threading.Timer(.15,lambda:native.write_text(json.dumps(event)+'\n'));timer.start()
            try:self.assertTrue(witness.confirms(sid,0))
            finally:timer.join()
            event['message']['model']=gateway.MODEL
            native.write_text(json.dumps(event)+'\n'+json.dumps({'padding':'x'*1000})+'\n')
            self.assertFalse(witness.confirms(sid,0))

    def test_api_key_mode_is_explicit_and_keeps_original_replay_database(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary); key=root/'key.txt'; key.write_text('fixture-api-key\n')
            replay=root/'old-auth'/'response-replay.sqlite'; replay.parent.mkdir()
            with patch.object(gateway.CredentialStore,'access_token',side_effect=AssertionError('OAuth must not be consulted')):
                server=gateway.Gateway(('127.0.0.1',0),key,'local-fixture',root/'metadata.jsonl',
                                       auth_mode='openai_api_key',replay_file=replay)
                self.addCleanup(server.server_close)
                self.assertEqual(server.store.access_token(),'fixture-api-key')
                self.assertEqual(server.replay.path,replay)
                self.assertEqual(server.auth_mode,'openai_api_key')
                server.hold_quota('insufficient_quota')
                self.assertEqual(server.current_quota()['auth'],'openai_api_key')
                self.assertNotIn('fixture-api-key',server.quota_file.read_text())
            for value in ('', 'PASTE_OPENAI_API_KEY_HERE', 'one two'):
                key.write_text(value)
                with self.subTest(value=value),self.assertRaises(ValueError):
                    gateway.APIKeyStore(key).access_token()
            key.unlink()
            with self.assertRaises(FileNotFoundError):gateway.APIKeyStore(key).access_token()

    def attach_replay(self, server):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        server.replay = gateway.ReplayStore(Path(temporary.name)/'response-replay.sqlite')

    def response(self, **values):
        return {'id': 'resp_test', 'model': gateway.MODEL, 'status': 'completed',
                'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': 'done'}]}], **values}

    def test_tool_image_history_keeps_call_binding_and_order(self):
        holder=SimpleNamespace();self.attach_replay(holder)
        original=self.response(output=[{'type':'function_call','call_id':'call_1','namespace':'robot_frontier',
                                       'name':'robot','arguments':'{"op":"observe"}'}])
        holder.replay.remember(gateway.to_responses({'messages':[]}),original,gateway.to_message(original))
        image = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': 'aW1hZ2U='}}
        request = gateway.to_responses({'system': [{'type': 'text', 'text': 'system'}], 'messages': [
            {'role': 'assistant', 'content': [{'type': 'tool_use', 'id': 'call_1', 'name': 'robot', 'input': {'op': 'observe'}}]},
            {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_1', 'content': [image]}, {'type': 'text', 'text': 'read it'}]}],
            'tools': [{'name': 'robot', 'input_schema': {'type': 'object'}}]},replay=holder.replay)
        self.assertEqual([item.get('type', item.get('role')) for item in request['input']],
                         ['function_call', 'function_call_output', 'user'])
        self.assertEqual(request['input'][1]['call_id'], 'call_1')
        self.assertEqual(request['input'][1]['output'][0]['type'], 'input_image')
        self.assertEqual(request['tools'][0]['type'], 'namespace')
        self.assertTrue(request['stream'])
        self.assertFalse(request['store'])
        self.assertNotIn('max_output_tokens', request)

    def test_encrypted_reasoning_roundtrips_without_fabricated_thought(self):
        holder=SimpleNamespace();self.attach_replay(holder)
        reasoning = {'id': 'rs_1', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque'}
        response=self.response(output=[reasoning, {'type': 'function_call', 'call_id': 'call_2',
                                                  'name': 'robot', 'arguments': '{"op":"observe"}'}])
        message = gateway.to_message(response)
        holder.replay.remember(gateway.to_responses({'messages':[]}),response,message)
        self.assertEqual(message['content'][0]['type'], 'redacted_thinking')
        request = gateway.to_responses({'messages': [{'role': 'assistant', 'content': message['content']}]},replay=holder.replay)
        self.assertEqual(request['input'][0], reasoning)
        self.assertEqual(request['input'][1]['call_id'], 'call_2')

    def test_native_mid_conversation_system_messages_keep_position(self):
        request = gateway.to_responses({'messages': [
            {'role': 'system', 'content': 'initial environment'},
            {'role': 'user', 'content': 'task'},
            {'role': 'system', 'content': [{'type': 'text', 'text': 'updated environment'}]}]})
        self.assertEqual([item['role'] for item in request['input']], ['developer', 'user', 'developer'])
        self.assertEqual(request['input'][-1]['content'], 'updated environment')

    def test_http_success_without_complete_event_is_failure(self):
        for response in (stream({'type': 'response.created'}), stream({'type': 'response.incomplete', 'response': {}}),
                         stream({'type': 'response.failed', 'response': {'error': {'code': 'quota'}}})):
            with self.subTest(response=response), self.assertRaises(gateway.ProtocolError):
                gateway.completed_response(response)

    def test_cancelled_stream_is_never_completed(self):
        cancelled = threading.Event()
        cancelled.set()
        with self.assertRaises(ConnectionResetError):
            gateway.completed_response(stream({'type':'response.completed','response':self.response()}), cancelled)

    def test_rejected_request_cannot_corrupt_the_next_native_request(self):
        server = gateway.ThreadingHTTPServer(('127.0.0.1',0), gateway.Handler)
        server.key='local-fixture'; server.audit=lambda record: None
        server.current_quota=lambda:None
        self.attach_replay(server)
        self.addCleanup(server.server_close)
        worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
        self.addCleanup(server.shutdown)
        client=http.client.HTTPConnection(*server.server_address,timeout=3)
        self.addCleanup(client.close)
        body=json.dumps({'messages':[{'role':'user','content':'x'*1000}]})
        headers={'x-api-key':server.key,'Content-Type':'application/json'}
        client.request('POST','/v1/messages/count_tokens',body,headers)
        first=client.getresponse(); self.assertEqual(first.status,404)
        self.assertEqual(first.getheader('Connection'),'close'); first.read()
        with patch.object(gateway.Handler,'authorized',return_value=False):
            client.request('POST','/v1/messages',None,headers)
            second=client.getresponse(); self.assertEqual(second.status,401)
            self.assertEqual(json.loads(second.read())['error']['type'],'authentication_error')

    def test_temporary_upstream_failures_allow_native_retry_but_bad_credentials_do_not(self):
        server = gateway.ThreadingHTTPServer(('127.0.0.1',0), gateway.Handler)
        server.key='local-fixture'; server.audit=lambda record: None
        server.current_quota=lambda:None
        self.attach_replay(server)
        server.store=SimpleNamespace(access_token=lambda:'fixture-only')
        self.addCleanup(server.server_close)
        worker=threading.Thread(target=server.serve_forever,daemon=True); worker.start()
        self.addCleanup(server.shutdown)
        for status,expected in ((429,'true'),(503,'true'),(401,'false')):
            @contextmanager
            def exchange(*args):
                raise gateway.UpstreamError('fixture',status=status)
                yield
            server.transport=SimpleNamespace(exchange=exchange)
            with self.subTest(status=status):
                client=http.client.HTTPConnection(*server.server_address,timeout=3)
                try:
                    client.request('POST','/v1/messages',json.dumps({'messages':[]}),{'x-api-key':server.key})
                    result=client.getresponse()
                    self.assertEqual(result.status,status)
                    self.assertEqual(result.getheader('x-should-retry'),expected)
                    self.assertEqual(result.getheader('Connection'),'close')
                    result.read()
                finally:client.close()

    def test_stream_quota_preserves_exact_code_and_parameter(self):
        response=stream({'type':'response.failed','response':{'error':{
            'code':'subscription_sharing_usage_limit_exceeded','param':'fixture'}}})
        with self.assertRaises(gateway.UpstreamError) as caught:
            gateway.completed_response(response)
        self.assertEqual(caught.exception.code,'subscription_sharing_usage_limit_exceeded')
        self.assertEqual(caught.exception.param,'fixture')

    def test_prefix_metadata_identifies_history_rewrites_without_recording_content(self):
        first=gateway.to_responses({'messages':[{'role':'user','content':'stable private fixture'}]})
        second=gateway.to_responses({'messages':[{'role':'user','content':'stable private fixture'},
                                                  {'role':'user','content':'new fixture'}]})
        a,b=gateway.request_fingerprints(first),gateway.request_fingerprints(second)
        self.assertEqual(a['input_prefix_sha256']['1'],b['input_prefix_sha256']['1'])
        second['input'][0]['content'][0]['text']='rewritten fixture'
        self.assertNotEqual(a['input_prefix_sha256']['1'],gateway.request_fingerprints(second)['input_prefix_sha256']['1'])
        self.assertNotIn('private fixture',json.dumps(a))

    def test_direct_admission_error_shape_is_not_assumed_to_be_an_api_error_object(self):
        self.assertEqual(gateway.upstream_error({'detail':'route unavailable'})['message'],'route unavailable')
        self.assertIsNone(gateway.upstream_error({'detail':'route unavailable'})['code'])
        self.assertEqual(gateway.upstream_error({'error':'not an object'})['message'],'Upstream request failed')

    def test_quota_hold_survives_restart_and_blocks_before_upstream(self):
        with tempfile.TemporaryDirectory() as temporary:
            log=Path(temporary)/'metadata.jsonl'
            server=gateway.Gateway(('127.0.0.1',0),Path(temporary)/'unused-auth.json','local-fixture',log)
            code='subscription_sharing_usage_limit_exceeded'
            server.hold_quota(code)
            server.server_close()
            server=gateway.Gateway(('127.0.0.1',0),Path(temporary)/'unused-auth.json','local-fixture',log)
            self.addCleanup(server.server_close)
            server.transport.connect=lambda token:self.fail('A quota-held request must never contact OpenAI')
            worker=threading.Thread(target=server.serve_forever,daemon=True);worker.start()
            self.addCleanup(server.shutdown)
            client=http.client.HTTPConnection(*server.server_address,timeout=3)
            try:
                client.request('POST','/v1/messages','{}',{'x-api-key':server.key})
                result=client.getresponse()
                self.assertEqual(result.status,429)
                self.assertEqual(result.getheader('x-should-retry'),'false')
                self.assertEqual(json.loads(result.read())['error']['code'],code)
                self.assertIsNone(server.current_quota()['reset_at'])
            finally:client.close()

    def test_rejects_truncated_event_and_wrong_model(self):
        for response in (io.BytesIO(b'data: {"type":"response.completed"}'),
                         stream({'type': 'response.completed', 'response': self.response(model='different')})):
            with self.assertRaises(gateway.ProtocolError):
                gateway.completed_response(response)

    def test_completion_and_tool_stream_are_explicit(self):
        value = self.response(output=[{'type': 'function_call', 'call_id': 'call_x', 'name': 'robot', 'arguments': '{}'}])
        result = gateway.completed_response(stream({'type': 'response.completed', 'response': value}))
        translated = gateway.to_message(result)
        events = list(gateway.message_events(translated,result['output']))
        self.assertEqual(events[-1][0], 'message_stop')
        self.assertEqual(translated['stop_reason'], 'tool_use')
        self.assertEqual(events[1][1]['content_block']['id'], 'call_x')

    def test_reports_cache_usage_without_double_counting(self):
        result = gateway.to_message(self.response(usage={'input_tokens': 100, 'output_tokens': 9,
                                                       'input_tokens_details': {'cached_tokens': 40, 'cache_write_tokens': 10}}))
        self.assertEqual(result['usage'], {'input_tokens': 50, 'cache_read_input_tokens': 40,
                                          'cache_creation_input_tokens': 10, 'output_tokens': 9})

    def test_unsupported_content_and_controls_fail_explicitly(self):
        for payload in ({'messages': [{'role': 'user', 'content': [{'type': 'document'}]}]},
                        {'messages': [], 'temperature': 0.5},
                        {'messages': [{'role': 'assistant', 'content': [{'type': 'thinking', 'thinking': 'fake', 'signature': 'bad'}]}]}):
            with self.subTest(payload=payload), self.assertRaises(gateway.ProtocolError):
                gateway.to_responses(payload)


class ExactReplayTests(unittest.TestCase):
    def test_only_original_schema_default_insertion_is_accepted(self):
        request=gateway.to_responses({'messages':[{'role':'user','content':'Edit fixture'}],
            'tools':[{'name':'Edit','input_schema':{'type':'object','properties':{
                'file_path':{'type':'string'},'replace_all':{'type':'boolean','default':False}}}}]},
            session_id='schema-default')
        response={'id':'resp_default','model':gateway.MODEL,'status':'completed','output':[
            {'id':'fc_default','type':'function_call','name':'Edit','namespace':'robot_frontier',
             'call_id':'call_default','arguments':'{ "file_path": "fixture.txt" }'}]}
        message=gateway.to_message(response);self.store.remember(request,response,message)
        payload={'messages':[{'role':'user','content':'Edit fixture'},{'role':'assistant','content':[
            {'type':'tool_use','id':'call_default','name':'Edit','input':{'file_path':'fixture.txt','replace_all':False}}]}]}
        restored=gateway.to_responses(payload,replay=self.store,session_id='schema-default')
        self.assertEqual(restored['input'][1],response['output'][0])
        self.assertEqual(restored['input'].native_defaults,['resp_default'])
        for value in (True,0,'false'):
            payload['messages'][1]['content'][0]['input']['replace_all']=value
            with self.assertRaises(gateway.ProtocolError):
                gateway.to_responses(payload,replay=self.store,session_id='schema-default')

    def test_schema_defaults_never_permit_removal_or_unadvertised_additions(self):
        self.assertFalse(gateway.same_arguments({'replace_all':False},{},{'properties':{'replace_all':{'default':False}}}))
        self.assertFalse(gateway.same_arguments({}, {'replace_all':False},{}))
        self.assertFalse(gateway.same_arguments({'replace_all':True},{'replace_all':False},{'properties':{'replace_all':{'default':False}}}))

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.path = Path(self.temporary.name)/'response-replay.sqlite'
        self.store = gateway.ReplayStore(self.path)
        self.initial = {'messages': [{'role': 'user', 'content': 'Inspect the robot.'}]}
        self.request = gateway.to_responses(self.initial, replay=self.store)
        self.raw = [
            {'id': 'rs_fixture', 'type': 'reasoning', 'summary': [], 'encrypted_content': 'opaque-fixture'},
            {'id': 'msg_fixture', 'type': 'message', 'status': 'completed', 'role': 'assistant',
             'phase': 'commentary', 'content': [{'type': 'output_text', 'text': 'Checking.', 'annotations': []}]},
            {'id': 'fc_fixture', 'type': 'function_call', 'status': 'completed', 'namespace': 'robot_frontier',
             'call_id': 'call_fixture', 'name': 'robot', 'arguments': '{\n "op": "observe", "view": "top"\n}'}]
        self.response = {'id': 'resp_fixture', 'model': gateway.MODEL, 'status': 'completed',
                         'output': self.raw, 'usage': {'input_tokens': 100, 'output_tokens': 10}}
        self.message = gateway.to_message(self.response)
        self.store.remember(self.request, self.response, self.message)

    def following(self, content=None):
        return {'messages': self.initial['messages'] + [
            {'role': 'assistant', 'content': self.message['content'] if content is None else content},
            {'role': 'user', 'content': [{'type': 'tool_result', 'tool_use_id': 'call_fixture',
                                         'content': 'Original tool result.'}]}]}

    def test_original_output_items_and_argument_bytes_survive_restart(self):
        restored = gateway.to_responses(self.following(), replay=gateway.ReplayStore(self.path))
        self.assertEqual(restored['input'][1:4], self.raw)
        self.assertEqual(restored['input'][2]['phase'], 'commentary')
        self.assertEqual(restored['input'][3]['arguments'], self.raw[-1]['arguments'])
        self.assertEqual(restored['prompt_cache_options'], {'comparison_response_id': 'resp_fixture'})
        self.assertEqual(restored['input'].replay_prefix_changes, [])
        serialized = json.loads(json.dumps(restored))
        self.assertEqual(serialized['input'][1:4], self.raw)

    def test_stream_uses_original_tool_argument_string(self):
        events = list(gateway.message_events(self.message, self.raw))
        arguments = [data['delta']['partial_json'] for _, data in events
                     if data.get('delta', {}).get('type') == 'input_json_delta']
        self.assertEqual(arguments, [self.raw[-1]['arguments']])

    def test_modified_assistant_text_or_tool_arguments_are_rejected(self):
        for index, key, value in ((1, 'text', 'Changed.'), (2, 'input', {'op': 'move'}), (2, 'id', 'different-call')):
            content = json.loads(json.dumps(self.message['content']))
            content[index][key] = value
            with self.subTest(key=key), self.assertRaisesRegex(gateway.ProtocolError, 'history changed'):
                gateway.to_responses(self.following(content), replay=self.store)

    def test_no_legacy_fallback_or_silent_reconstruction(self):
        empty = gateway.ReplayStore(Path(self.temporary.name)/'empty.sqlite')
        with self.assertRaisesRegex(gateway.ProtocolError, 'legacy history'):
            gateway.to_responses(self.following(), replay=empty)
        with self.assertRaisesRegex(gateway.ProtocolError, 'requires original output replay'):
            gateway.to_responses(self.following())

    def test_legitimate_compaction_keeps_original_items_and_exposes_prefix_change(self):
        payload = self.following()
        payload['messages'][0]['content'] = 'Native compacted context.'
        restored = gateway.to_responses(payload, replay=self.store)
        self.assertEqual(restored['input'][1:4], self.raw)
        self.assertEqual(restored['input'].replay_prefix_changes, ['resp_fixture'])

    def test_ambiguous_retry_output_is_rejected(self):
        alternate = json.loads(json.dumps(self.response))
        alternate['id'] = 'resp_other'
        alternate['output'][1]['phase'] = 'final_answer'
        self.store.remember(self.request, alternate, gateway.to_message(alternate))
        with self.assertRaisesRegex(gateway.ProtocolError, 'Ambiguous'):
            gateway.to_responses(self.following(), replay=self.store)

    def test_response_id_cannot_be_rebound(self):
        changed = {**self.response, 'output': self.raw[:-1]}
        with self.assertRaisesRegex(gateway.ProtocolError, 'identity was reused'):
            self.store.remember(self.request, changed, gateway.to_message(changed))

    def test_adjacent_original_message_boundaries_and_refusals_are_preserved(self):
        original = [{'id': 'msg_a', 'type': 'message', 'role': 'assistant', 'phase': 'commentary',
                     'content': [{'type': 'output_text', 'text': 'First.'}]},
                    {'id': 'msg_b', 'type': 'message', 'role': 'assistant', 'phase': 'final_answer',
                     'content': [{'type': 'refusal', 'refusal': 'Second.'}]}]
        response = {**self.response, 'id': 'resp_messages', 'output': original}
        message = gateway.to_message(response)
        self.store.remember(self.request, response, message)
        payload = {'messages': self.initial['messages'] + [
            {'role': 'assistant', 'content': message['content']}, {'role': 'user', 'content': 'Continue.'}]}
        restored = gateway.to_responses(payload, replay=self.store)
        self.assertEqual(restored['input'][1:3], original)

    def test_retry_prefix_cannot_substitute_true_for_one(self):
        response = {**self.response, 'id': 'resp_number', 'output': [
            {**self.raw[-1], 'call_id': 'call_number', 'arguments': '{"value":1}'}]}
        message = gateway.to_message(response)
        self.store.remember(self.request, response, message)
        message['content'][0]['input']['value'] = True
        payload = {'messages': self.initial['messages'] + [{'role': 'assistant', 'content': message['content']}]}
        with self.assertRaises(gateway.ProtocolError):
            gateway.to_responses(payload, replay=self.store)

    def test_parallel_branches_cannot_select_another_branchs_original_output(self):
        def branch(index):
            response = {**self.response, 'id': 'resp_parallel_'+str(index), 'output': [
                {**self.raw[-1], 'id': 'fc_parallel_'+str(index), 'call_id': 'call_parallel_'+str(index),
                 'arguments': '{ "branch": '+str(index)+' }'}]}
            message = gateway.to_message(response)
            self.store.remember(self.request, response, message)
            payload = {'messages': self.initial['messages'] + [{'role': 'assistant', 'content': message['content']}]}
            restored = gateway.to_responses(payload, replay=gateway.ReplayStore(self.path))
            self.assertEqual(restored['input'][1:], response['output'])
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(branch, range(24)))

    def test_client_bookkeeping_does_not_discard_original_metadata(self):
        content = json.loads(json.dumps(self.message['content']))
        content[-1]['caller'] = {'type': 'direct'}
        content[1]['cache_control'] = {'type': 'ephemeral'}
        restored = gateway.to_responses(self.following(content), replay=self.store)
        self.assertEqual(restored['input'][1:4], self.raw)

    def test_diagnostics_capture_reasoning_removal_without_logging_payload(self):
        result = {**self.response, 'input': 'private user prompt',
                  'input_transformations': [{'id': 'rs_old', 'type': 'reasoning', 'action': 'remove',
                                             'reason': 'prefix_mismatch', 'content': 'private old reasoning'}],
                  'prompt_cache_diagnostics': {'type': 'cache_miss', 'reason': 'input_changed',
                      'comparison_reusable_tokens': 9000, 'cache_missed_tokens': 8000, 'input': 'private diagnostic input'}}
        metadata = gateway.response_metadata(result)
        self.assertEqual(metadata['input_transformations'][0]['reason'], 'prefix_mismatch')
        self.assertEqual(metadata['cache_diagnostics']['cache_missed_tokens'], 8000)
        self.assertNotIn('private', json.dumps(metadata))

    def test_missing_diagnostics_are_unknown_not_reported_as_a_cache_hit(self):
        result = gateway.response_metadata(self.response)
        self.assertIsNone(result['cache_diagnostics'])
        self.assertIsNone(result['input_transformations'])

    def test_native_numeric_spelling_does_not_rewrite_original_arguments(self):
        original = ' { "distance": 1.0, "scale": 1e-3, "text": "\\u673a" } '
        response = {**self.response, 'id': 'resp_numeric', 'output': [
            {**self.raw[-1], 'call_id': 'call_numeric', 'arguments': original}]}
        message = gateway.to_message(response)
        self.store.remember(self.request, response, message)
        message['content'][0]['input']['distance'] = 1
        payload = {'messages': [{'role': 'user', 'content': 'Compacted context.'},
                                {'role': 'assistant', 'content': message['content']}]}
        restored = gateway.to_responses(payload, replay=self.store)
        self.assertEqual(restored['input'][-1]['arguments'], original)
        self.assertEqual(restored['input'].replay_prefix_changes, ['resp_numeric'])

    def test_repeated_plaintext_with_different_original_metadata_is_not_guessed_after_compaction(self):
        for number in (1, 2):
            response = {**self.response, 'id': 'resp_plain_'+str(number), 'output': [
                {'id': 'msg_plain_'+str(number), 'type': 'message', 'role': 'assistant', 'phase': 'final_answer',
                 'content': [{'type': 'output_text', 'text': 'Same answer.'}]}]}
            message = gateway.to_message(response)
            self.store.remember(self.request, response, message)
        payload = {'messages': [{'role': 'user', 'content': 'Compacted context.'},
                                {'role': 'assistant', 'content': message['content']}]}
        with self.assertRaisesRegex(gateway.ProtocolError, 'Ambiguous'):
            gateway.to_responses(payload, replay=self.store)

    def test_persistence_failure_does_not_release_a_tool_or_lose_upstream_usage(self):
        server = gateway.Gateway(('127.0.0.1', 0), Path(self.temporary.name)/'unused-auth.json', 'fixture-key')
        self.addCleanup(server.server_close)
        server.store = SimpleNamespace(access_token=lambda: 'fixture-only')
        response = stream({'type': 'response.completed', 'response': self.response})
        response.status = 200
        response.getheader = lambda name, default=None: default
        @contextmanager
        def exchange(request,done,record):
            record.update(ws_mode='full_replay')
            yield self.response
        server.transport.exchange=exchange
        records = []
        server.audit = records.append
        with patch.object(server.replay, 'remember', side_effect=OSError('fixture storage failure')):
            threading.Thread(target=server.serve_forever, daemon=True).start()
            self.addCleanup(server.shutdown)
            client = http.client.HTTPConnection(*server.server_address, timeout=3)
            try:
                client.request('POST', '/v1/messages', json.dumps({**self.initial, 'stream': True}), {'x-api-key': 'fixture-key'})
                reply = client.getresponse()
                body = reply.read().decode()
                self.assertIn('event: error', body)
                self.assertNotIn('content_block_start', body)
                self.assertNotIn('message_stop', body)
            finally:
                client.close()
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]['completed'])
        self.assertTrue(records[0]['upstream_completed'])
        self.assertEqual(records[0]['usage']['input_tokens'], 100)

    def test_untracked_native_history_is_rejected_before_inference(self):
        server = gateway.Gateway(('127.0.0.1', 0), Path(self.temporary.name)/'empty'/'unused-auth.json', 'fixture-key')
        self.addCleanup(server.server_close)
        server.transport.connect = lambda token: self.fail('Untracked history must not reach inference')
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        client = http.client.HTTPConnection(*server.server_address, timeout=3)
        try:
            client.request('POST', '/v1/messages', json.dumps(self.following()), {'x-api-key': 'fixture-key'})
            reply = client.getresponse()
            self.assertEqual(reply.status, 400)
            self.assertIn('legacy history', reply.read().decode())
        finally:
            client.close()

    def test_identical_text_is_resolved_by_native_session_and_fork_ancestry(self):
        originals={}
        for session in ('parent_a','parent_b'):
            request=gateway.to_responses(self.initial,replay=self.store,session_id=session)
            response={**self.response,'id':'resp_'+session,'output':[
                {'id':'msg_'+session,'type':'message','role':'assistant','phase':'final_answer',
                 'content':[{'type':'output_text','text':'READY'}]}]}
            message=gateway.to_message(response)
            self.store.remember(request,response,message)
            originals[session]=response['output']
        payload={'messages':self.initial['messages']+[{'role':'assistant','content':'READY'},
                                                    {'role':'user','content':'Continue.'}]}
        for session in originals:
            restored=gateway.to_responses(payload,replay=self.store,session_id=session)
            self.assertEqual(restored['input'][1],originals[session][0])
        fork=gateway.to_responses(payload,replay=self.store,session_id='child',fork_source='parent_a')
        self.assertEqual(fork['input'][1],originals['parent_a'][0])
        resumed=gateway.to_responses(payload,replay=self.store,session_id='child')
        self.assertEqual(resumed['input'][1],originals['parent_a'][0])
        with self.assertRaisesRegex(gateway.ProtocolError,'cannot be rebound'):
            gateway.to_responses(payload,replay=self.store,session_id='child',fork_source='parent_b')
        with self.assertRaisesRegex(gateway.ProtocolError,'unavailable'):
            gateway.to_responses(payload,replay=self.store,session_id='unrelated')

    def test_native_fork_control_is_not_fabricated_as_a_model_output(self):
        request=gateway.to_responses(self.initial,replay=self.store,session_id='parent')
        self.store.remember(request,{**self.response,'id':'resp_scoped'},self.message)
        payload=self.following()
        payload['messages'] += [{'role':'assistant','content':'No response requested.'},
                                {'role':'user','content':'Tool-free setup turn.'}]
        child=gateway.to_responses(payload,replay=self.store,session_id='child',fork_source='parent')
        self.assertEqual(child['input'].native_controls,['fork_no_response'])
        self.assertEqual(child['input'][-2],{'role':'assistant','content':'No response requested.'})
        with self.assertRaisesRegex(gateway.ProtocolError,'unavailable'):
            gateway.to_responses(payload,replay=self.store,session_id='parent')
        payload['messages'][-2]['content']='Different untracked assistant output.'
        with self.assertRaisesRegex(gateway.ProtocolError,'unavailable'):
            gateway.to_responses(payload,replay=self.store,session_id='child')


if __name__ == '__main__':
    unittest.main()
