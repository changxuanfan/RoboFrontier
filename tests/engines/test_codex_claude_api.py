"""Codex with Claude through the loopback Messages adapter: profile rules and the real CLI.

The native test drives the installed Codex CLI through `scripts/codex_claude_gateway.py`
(run by a Python that has the optional `anthropic` SDK) against a local stand-in for the
Anthropic API. No model provider is contacted and every key is fake.
"""
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
from unittest import mock

from robofrontier.engines.codex import launch
from robofrontier.engines.codex.launch import launch_config, profile
from robofrontier.runtime import outage

from anthropic_upstream_fixture import AnthropicStub, text, thinking, tool_use, usage

ROOT = Path(__file__).resolve().parents[2]
BETA = 'thinking-binding-controls-2026-08-01'
UPSTREAM_KEY = 'fake-anthropic-key-for-offline-tests'


def gateway_python():
    """A Python that can import the optional SDK: ROBOFRONTIER_GATEWAY_PYTHON, else .venv-gateway."""
    for candidate in (os.environ.get('ROBOFRONTIER_GATEWAY_PYTHON'), ROOT/'.venv-gateway/bin/python'):
        if candidate and Path(candidate).is_file() and subprocess.run(
                [str(candidate), '-c', 'import anthropic'], capture_output=True).returncode == 0:
            return str(candidate)
    return None


def catalog(folder, **fields):
    path = Path(folder)/'models.json'
    entry = {'model': 'claude-opus-5-5', 'provider': 'claude_gateway', 'transport': 'loopback_gateway',
             'transport_revision': 'messages-adapter-v1', 'base_url': 'http://127.0.0.1:18470/v1',
             'env_key': 'LOCAL_GATEWAY_KEY', 'effort': 'high', 'vision': True, 'context_capacity': 1000000}
    entry.update(fields)
    path.write_text(json.dumps({'context_window': 300000, 'auto_compact_token_limit': 267000,
                                'profiles': {'p': {k: v for k, v in entry.items() if v is not None}}}))
    return path


class LoopbackProfileTests(unittest.TestCase):
    def test_checked_in_profile_selects_one_model_through_the_local_adapter(self):
        p = profile('opus_claude_api')
        self.assertEqual((p['model'], p['effort'], p['vision'], p['provider']),
                         ('claude-opus-5-5', 'high', True, 'claude_gateway'))
        self.assertEqual((p['context_window'], p['auto_compact_token_limit'], p['context_capacity']),
                         (300000, 267000, 1000000))
        self.assertEqual((p['base_url'], p['env_key'], p['upstream_host']),
                         ('http://127.0.0.1:18470/v1', 'ROBOFRONTIER_CLAUDE_GATEWAY_KEY', 'api.anthropic.com'))
        with tempfile.TemporaryDirectory() as folder:
            started = launch_config(p, Path(folder))
            model = json.loads((Path(folder)/'models.json').read_text())['models'][0]
        for expected in ('model="claude-opus-5-5"', 'model_reasoning_effort="high"', 'model_context_window=300000',
                         'model_auto_compact_token_limit=267000',
                         'model_providers.claude_gateway.base_url="http://127.0.0.1:18470/v1"',
                         'model_providers.claude_gateway.env_key="ROBOFRONTIER_CLAUDE_GATEWAY_KEY"',
                         'model_providers.claude_gateway.wire_api="responses"',
                         'model_providers.claude_gateway.requires_openai_auth=false',
                         'model_providers.claude_gateway.supports_websockets=false'):
            self.assertIn(expected, started['args'])
        self.assertEqual(model['input_modalities'], ['text', 'image'])
        self.assertEqual((model['slug'], model['context_window'], model['support_verbosity']),
                         ('claude-opus-5-5', 300000, False))
        # Model shells inherit neither the local key nor an upstream credential.
        self.assertIn('shell_environment_policy.exclude=["ROBOFRONTIER_CLAUDE_GATEWAY_KEY", "ANTHROPIC_API_KEY", '
                      '"ANTHROPIC_AUTH_TOKEN"]', started['args'])
        self.assertNotIn('Authorization', json.dumps(started))

    def test_plain_http_is_limited_to_the_marked_literal_loopback_profile(self):
        with tempfile.TemporaryDirectory() as folder:
            self.assertEqual(profile('p', catalog(folder))['model'], 'claude-opus-5-5')
            for fields in ({'base_url': 'http://example.com:18470/v1'}, {'base_url': 'http://127.0.0.1.example.com:18470/v1'},
                           {'base_url': 'http://localhost:18470/v1'}, {'base_url': 'http://127.0.0.1/v1'},
                           {'base_url': 'http://127.0.0.1:18470/v1?key=x'}, {'base_url': 'http://user:pw@127.0.0.1:18470/v1'},
                           {'base_url': 'https://api.anthropic.com/v1'}, {'base_url': 'http://[::1]:18470/v1'},
                           {'env_key': None}, {'transport_revision': None}, {'http_headers': {'X-Extra': 'value'}},
                           {'transport': 'other_gateway'},
                           # Without the explicit mark, every provider still needs HTTPS.
                           {'transport': None}, {'transport': None, 'provider': 'github_pat'},
                           {'provider': 'openai'}):
                with self.subTest(fields=fields), self.assertRaises(ValueError):
                    profile('p', catalog(folder, **fields))

    def test_other_profiles_keep_https_and_their_catalog_defaults(self):
        from robofrontier.configuration import model_catalog
        for name, entry in model_catalog('codex')['profiles'].items():
            if name == 'opus_claude_api':
                continue
            with self.subTest(profile=name):
                self.assertNotIn('transport', entry)
                self.assertFalse(str(entry.get('base_url', 'https://')).startswith('http://'))
        with tempfile.TemporaryDirectory() as folder:
            launch_config(profile('sol61_github_pat'), Path(folder))
            model = json.loads((Path(folder)/'models.json').read_text())['models'][0]
            self.assertNotIn('shell_environment_policy', json.dumps(launch_config(profile('luna'), Path(folder))['args']))
        self.assertTrue(model['support_verbosity'])

    def test_codex_never_receives_the_upstream_credential(self):
        base = {'ANTHROPIC_API_KEY': 'upstream', 'ANTHROPIC_AUTH_TOKEN': 'upstream', 'LOCAL_GATEWAY_KEY': 'local'}
        self.assertEqual(launch.gateway_environment({'transport': 'loopback_gateway'}, dict(base)),
                         {'LOCAL_GATEWAY_KEY': 'local'})
        self.assertEqual(launch.gateway_environment({'provider': 'github_pat'}, dict(base)), base)

    def test_a_run_starts_only_with_its_own_adapter_listening(self):
        health = {'ready': True, 'model': 'claude-opus-5-5', 'transport_revision': 'messages-adapter-v1'}

        class Health(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps(health).encode()
                self.send_response(200 if self.path == '/healthz' else 404)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        server = ThreadingHTTPServer(('127.0.0.1', 0), Health)
        threading.Thread(target=server.serve_forever, kwargs={'poll_interval': .02}, daemon=True).start()
        try:
            p = {'transport': 'loopback_gateway', 'model': 'claude-opus-5-5', 'transport_revision': 'messages-adapter-v1',
                 'base_url': 'http://127.0.0.1:%d/v1' % server.server_port}
            launch.require_gateway(p)
            launch.require_gateway({'provider': 'github_pat', 'base_url': 'https://unused.invalid'})
            for changed in ({'transport_revision': 'messages-adapter-v0'}, {'model': 'claude-opus-5'}):
                with self.subTest(changed=changed), self.assertRaisesRegex(ValueError, 'not this profile'):
                    launch.require_gateway({**p, **changed})
        finally:
            server.shutdown()
            server.server_close()
        with self.assertRaisesRegex(ValueError, 'not listening'):
            launch.require_gateway(p, timeout_s=1)

    def test_outage_probe_watches_the_upstream_api_not_the_loopback_port(self):
        with tempfile.TemporaryDirectory() as run:
            (Path(run)/'private/inputs').mkdir(parents=True)
            (Path(run)/'private/inputs/codex.json').write_text(json.dumps({'profile': profile('opus_claude_api')}))
            self.assertEqual(outage.model_hosts(run, 'codex'), ('api.anthropic.com',))

    def test_container_and_slurm_entries_refuse_a_host_loopback_profile(self):
        from robofrontier.batch import container, slurm_job
        chosen = {'profiles': {'opus_claude_api': {'transport': 'loopback_gateway', 'env_key': 'K'}}}
        with mock.patch('robofrontier.cli._catalog', return_value=chosen):
            with self.assertRaisesRegex(ValueError, 'not in a container'):
                container._credential_environment({'policy': {'profile': 'opus_claude_api'}}, {'K': 'v'})
        self.assertIn("'loopback_gateway'", Path(slurm_job.__file__).read_text())


NODE_DRIVER = r'''
const fs=require('fs'),{CodexRpc}=require(process.argv[1]+'/robofrontier/engines/codex/codex_rpc');
const out=process.argv[2],launch=JSON.parse(fs.readFileSync(out+'/launch.json'));
(async()=>{
const waiters=new Map(),usage=[],events=[];let release,entered,calls=0;
const hold=new Promise(r=>release=r),ready=new Promise(r=>entered=r);
const wait=id=>new Promise(r=>waiters.set(id,r));
const rpc=new CodexRpc(launch.args,{stderr:fs.openSync(out+'/server.log','w'),
 onEvent:m=>{if(m.method==='thread/tokenUsage/updated')usage.push(m.params.tokenUsage.last);
  if(m.method==='thread/compacted'||(m.method==='item/completed'&&m.params?.item?.type==='contextCompaction'))events.push('compacted');
  if(m.method==='turn/completed'){const cb=waiters.get(m.params.threadId);if(cb){waiters.delete(m.params.threadId);cb(m.params);}}},
 onRequest:async(m,p)=>{if(m!=='item/tool/call')throw Error(m);calls++;
  if(p.tool==='delegate'){entered();await hold;return {success:true,contentItems:[{type:'inputText',text:'delegate result'}]};}
  if(p.tool!=='probe')throw Error('unexpected tool '+p.tool);
  return {success:true,contentItems:[{type:'inputText',text:'local tool result'},
   {type:'inputImage',imageUrl:JSON.parse(fs.readFileSync(out+'/image.json')).url}]};}});
const turn=async(id,input)=>{const done=wait(id);await rpc.call('turn/start',{threadId:id,model:launch.model,effort:launch.effort,input});
 const end=await Promise.race([done,new Promise((_,reject)=>setTimeout(()=>reject(Error('turn timeout')),60000))]);
 if(end.turn.status!=='completed')throw Error('turn failed: '+JSON.stringify(end.turn.error));};
try{
 await rpc.initialize();
 const a=await rpc.call('thread/start',{cwd:out+'/work',model:launch.model,modelProvider:launch.provider,approvalPolicy:'never',
  baseInstructions:'BASE_INSTRUCTIONS_MARKER',
  dynamicTools:['probe','delegate'].map(name=>({type:'function',name,description:name+' tool',inputSchema:{type:'object',properties:{}}}))});
 const id=a.thread.id;
 await turn(id,[{type:'text',text:'PARALLEL please'},{type:'localImage',path:out+'/colors.png'}]);
 await turn(id,[{type:'text',text:'second plain turn'}]);
 await turn(id,[{type:'text',text:'SHELL now'}]);
 await turn(id,[{type:'text',text:'PATCH now'}]);
 await rpc.call('thread/compact/start',{threadId:id});
 for(let i=0;i<300&&!events.includes('compacted');i++)await new Promise(r=>setTimeout(r,100));
 if(!events.includes('compacted'))throw Error('compaction did not finish');
 await new Promise(r=>setTimeout(r,1000));
 await turn(id,[{type:'text',text:'after compaction plain'}]);
 const parent=wait(id);
 await rpc.call('turn/start',{threadId:id,model:launch.model,effort:launch.effort,input:[{type:'text',text:'DELEGATE go'}]});
 await Promise.race([ready,new Promise((_,reject)=>setTimeout(()=>reject(Error('delegate timeout')),30000))]);
 const fork=await rpc.call('thread/fork',{threadId:id,cwd:out+'/work',model:launch.model,modelProvider:launch.provider,excludeTurns:true,ephemeral:false});
 await turn(fork.thread.id,[{type:'text',text:'CHILD first message'}]);
 release();const end=await parent;if(end.turn.status!=='completed')throw Error('parent failed');
 fs.writeFileSync(out+'/native.json',JSON.stringify({parent:id,child:fork.thread.id,forkedFrom:fork.thread.forkedFromId,calls,usage}));
}finally{await rpc.close();}
})().then(()=>process.exit(0)).catch(e=>{console.error(e.stack);process.exit(1)});
'''


def plain(value):
    """A request or reply without cache markers: what the API's prefix check compares."""
    if isinstance(value, dict):
        return {key: plain(item) for key, item in value.items() if key not in ('cache_control', '_raw')}
    return [plain(item) for item in value] if isinstance(value, list) else value


@unittest.skipUnless(shutil.which('codex') and shutil.which('node') and gateway_python(),
                     'requires the pinned Codex CLI, Node.js and a Python with the optional anthropic SDK')
class NativeCliThroughGatewayTests(unittest.TestCase):
    def script(self, body, headers):
        """The fake model: what to answer, decided from the newest user turn."""
        number = len(self.stub.requests)
        last = body['messages'][-1]['content']
        words = ' '.join(block.get('text', '') for block in last if block['type'] == 'text')
        signature = 'c2lnbmF0dXJl+/%d==' % number
        if any(block['type'] == 'tool_result' for block in last):
            blocks = [thinking(signature), text('AFTER_TOOLS_%d' % number)]
        elif 'CONTEXT CHECKPOINT COMPACTION' in words:
            blocks = [thinking(signature), text('HANDOFF_SUMMARY_MARKER')]
        elif 'PARALLEL' in words and 'HANDOFF_SUMMARY_MARKER' not in words:
            blocks = [thinking(signature + 'a'), text('calling two tools'), thinking(signature + 'b'),
                      tool_use('toolu_stub_%da' % number, 'probe', {}, raw=''),
                      tool_use('toolu_stub_%db' % number, 'probe', {})]
        elif words.rstrip().endswith('SHELL now'):
            command = ('echo "KEY_VISIBLE=${ROBOFRONTIER_CLAUDE_GATEWAY_KEY:+yes}"; curl -s -o /dev/null -w "HTTP=%%{http_code}" '
                       '--max-time 3 http://127.0.0.1:%d/healthz; echo " CURL_EXIT=$?"' % self.gateway_port)
            blocks = [thinking(signature), tool_use('toolu_stub_%d' % number, 'exec_command', {'cmd': command},
                                                    raw=json.dumps({'cmd': command}, indent=1))]
        elif words.rstrip().endswith('PATCH now'):
            blocks = [tool_use('toolu_stub_%d' % number, 'apply_patch', {'input': self.patch})]
        elif words.rstrip().endswith('DELEGATE go'):
            blocks = [thinking(signature), tool_use('toolu_stub_%d' % number, 'delegate', {})]
        else:
            blocks = [thinking(signature), text('PLAIN_%d' % number)]
        self.answers.append(blocks)
        return {'blocks': blocks, 'stop_reason': 'tool_use' if blocks[-1]['type'] == 'tool_use' else 'end_turn',
                'usage': usage(), 'id': 'msg_stub_%d' % number}

    def start(self, script):
        """A fake upstream, the gateway as its own process, and a Codex launch like a prepared run's."""
        from PIL import Image
        self.stub = AnthropicStub(script)
        self.addCleanup(self.stub.close)
        temporary = tempfile.TemporaryDirectory(prefix='rf-codex-claude-')
        self.addCleanup(temporary.cleanup)
        out = Path(temporary.name).resolve()
        work, private = out/'work', out/'private-gateway'
        work.mkdir()
        private.mkdir(mode=0o700)
        log = private/'transport-metadata.jsonl'
        gateway = subprocess.Popen(
            [gateway_python(), str(ROOT/'scripts/codex_claude_gateway.py'), '--key-file', str(private/'gateway-key.json'),
             '--port', '0', '--log', str(log), '--upstream-base-url', self.stub.url],
            env={'PATH': os.environ['PATH'], 'ANTHROPIC_API_KEY': UPSTREAM_KEY,
                 'ANTHROPIC_BASE_URL': 'http://127.0.0.1:9/ignored'},
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        self.addCleanup(lambda: (gateway.kill(), gateway.wait(), gateway.stdout.close(), gateway.stderr.close()))
        started = gateway.stdout.readline()
        self.assertTrue(started, gateway.stderr.read() if gateway.poll() is not None else 'gateway did not start')
        self.gateway_port = json.loads(started)['listening'][1]
        local_key = json.loads((private/'gateway-key.json').read_text())['key']
        selected = {**profile('opus_claude_api'), 'base_url': 'http://127.0.0.1:%d/v1' % self.gateway_port}
        launch.require_gateway(selected)
        # A frozen access table as in a prepared run: workspace writable, shell network off.
        run = out/'run'
        (run/'private/inputs').mkdir(parents=True)
        (run/'private/inputs/policy-access.json').write_text(json.dumps(
            {'filesystem': {'/': 'read', str(work): 'write', str(private): 'deny'}, 'network': False}))
        home = out/'codex-home'
        home.mkdir(mode=0o700)
        pixels = io.BytesIO()
        Image.new('RGB', (32, 32), 'red').save(pixels, format='PNG')
        (out/'colors.png').write_bytes(pixels.getvalue())
        image = base64.b64encode(pixels.getvalue()).decode()
        (out/'image.json').write_text(json.dumps({'url': 'data:image/png;base64,' + image}))
        with mock.patch.dict(os.environ, {'CODEX_HOME': str(home)}):
            started = launch_config(selected, out, run_dir=run)
        (out/'launch.json').write_text(json.dumps(started))
        env = launch.gateway_environment(selected, {**os.environ, 'CODEX_HOME': str(home), 'ANTHROPIC_API_KEY': 'must-not-pass',
                                                    selected['env_key']: local_key})
        self.assertNotIn('ANTHROPIC_API_KEY', env)
        return out, log, local_key, image, env

    def test_the_live_preflight_driver_passes_against_the_fake_upstream(self):
        """The same Node driver `robofrontier preflight` runs: image, tool, manual compaction, fork."""
        from robofrontier.runtime import preflight_probe

        def script(body, headers):
            last = body['messages'][-1]['content']
            said = ' '.join(block.get('text', '') for block in last if block['type'] == 'text')
            signature = 'c2ln%d' % len(self.stub.requests)
            if any(block['type'] == 'tool_result' for block in last) and 'call protocol_check again' not in said:
                blocks = [thinking(signature), text('VISION_TOOL_OK')]
            elif 'CONTEXT CHECKPOINT COMPACTION' in said:
                blocks = [thinking(signature), text('The image was %s on the left and %s on the right.' % (self.probe['left'], self.probe['right']))]
            else:
                blocks = [thinking(signature), tool_use('toolu_check_%d' % len(self.stub.requests), 'protocol_check',
                                                        {'left': self.probe['left'], 'right': self.probe['right']})]
            return {'blocks': blocks, 'stop_reason': 'tool_use' if blocks[-1]['type'] == 'tool_use' else 'end_turn',
                    'usage': usage()}

        out, log, _, _, env = self.start(script)
        self.probe = preflight_probe.write(out/'colors.png', *preflight_probe.choose())
        (out/'probe.json').write_text(json.dumps(self.probe))
        result = subprocess.run(['node', str(ROOT/'robofrontier/engines/codex/codex_preflight.js'), str(out)],
                                capture_output=True, text=True, timeout=240, env=env)
        report = json.loads((out/'report.json').read_text())
        self.assertEqual((result.returncode, report.get('error')), (0, None), result.stderr[-2000:])
        self.assertEqual((report['passed'], report['vision_and_function'], report['compaction'], report['fork_history_and_tool']),
                         (True, True, True, True))
        bodies = [request['body'] for request in self.stub.requests]
        records = [json.loads(line) for line in log.read_text().splitlines()]
        self.assertEqual([record['request_kind'] for record in records], ['turn', 'turn', 'compaction', 'turn', 'turn'])
        self.assertEqual({record['status'] for record in records}, {'completed'})
        self.assertTrue(any(block['type'] == 'image' for block in bodies[0]['messages'][-1]['content']))
        self.assertEqual(bodies[2]['tool_choice'], {'type': 'none'})
        # The child was forked after the compaction: it replays the summary, not earlier thinking.
        self.assertEqual([message['role'] for message in bodies[3]['messages']], ['user'])
        self.assertTrue(records[3]['codex_forked_from'])

    def test_images_reasoning_compaction_and_fork_survive_the_adapter(self):
        self.answers = []
        out, log, local_key, image, env = self.start(self.script)
        work, home = out/'work', out/'codex-home'
        self.patch = '*** Begin Patch\n*** Add File: %s\n+hello from claude\n*** End Patch' % (work/'patched.txt')
        result = subprocess.run(['node', '-e', NODE_DRIVER, str(ROOT), str(out)], capture_output=True, text=True,
                                timeout=240, env=env)
        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        native = json.loads((out/'native.json').read_text())
        bodies = [request['body'] for request in self.stub.requests]
        records = [json.loads(line) for line in log.read_text().splitlines()]
        if os.environ.get('ROBOFRONTIER_CAPTURE_DIR'):
            # Optional: the exact upstream request bodies, one conversation per file, for an
            # external prefix checker. Synthetic content only.
            capture = Path(os.environ['ROBOFRONTIER_CAPTURE_DIR'])
            capture.mkdir(parents=True, exist_ok=True)
            for name, chosen in (('before-compaction', range(0, 8)), ('parent-after-compaction', (8, 9, 11)),
                                 ('forked-child', (8, 9, 10))):
                (capture/(name+'.jsonl')).write_text(''.join(json.dumps(bodies[i])+'\n' for i in chosen if i < len(bodies)))
        self.assertEqual(len(bodies), 12)
        self.assertEqual(len(records), 12)
        self.assertEqual(native['calls'], 3)

        # One model, one credential, explicit effort and thinking controls on every request.
        for request in self.stub.requests:
            body, headers = request['body'], request['headers']
            # The SDK decides the header; the only credential it carries is the adapter's own.
            self.assertEqual(headers.get('x-api-key') or headers.get('authorization', '').removeprefix('Bearer '),
                             UPSTREAM_KEY)
            self.assertNotIn(local_key, json.dumps(headers))
            self.assertIn(BETA, headers.get('anthropic-beta', ''))
            self.assertEqual(body['model'], 'claude-opus-5-5')
            self.assertEqual(body['thinking'], {'type': 'adaptive', 'block_binding': {'prefix_mismatch_behavior': 'error'}})
            self.assertEqual((body['output_config'], body['max_tokens'], body['stream']), ({'effort': 'high'}, 64000, True))
            self.assertFalse({'temperature', 'top_p', 'top_k', 'fallbacks'} & set(body))
            names = [tool['name'] for tool in body['tools']]
            self.assertEqual(names, sorted(names))
            self.assertEqual(body['system'][-1]['cache_control'], {'type': 'ephemeral'})
            self.assertLessEqual(json.dumps(body).count('"cache_control"'), 4)
        first = bodies[0]
        self.assertEqual(first['system'][0]['text'], 'BASE_INSTRUCTIONS_MARKER')
        self.assertTrue({'probe', 'delegate', 'exec_command', 'apply_patch'} <= {tool['name'] for tool in first['tools']})
        patch_tool = next(tool for tool in first['tools'] if tool['name'] == 'apply_patch')
        self.assertEqual(patch_tool['input_schema']['required'], ['input'])
        self.assertIn('Begin Patch', patch_tool['description'])

        # Images reach Claude as image blocks: the user's attachment and both tool results.
        picture = {'type': 'image', 'source': {'type': 'base64', 'media_type': 'image/png', 'data': image}}
        self.assertIn(picture, first['messages'][-1]['content'])
        results = bodies[1]['messages'][-1]['content']
        self.assertEqual([block['type'] for block in results], ['tool_result', 'tool_result'])
        for block in results:
            self.assertEqual(block['content'], [{'type': 'text', 'text': 'local tool result'}, picture])

        # Reasoning comes back unchanged and in place, with the parallel calls in one turn.
        self.assertEqual(plain(bodies[1]['messages'][-2]), {'role': 'assistant', 'content': plain(self.answers[0])})
        self.assertEqual([block['type'] for block in bodies[1]['messages'][-2]['content']],
                         ['thinking', 'text', 'thinking', 'tool_use', 'tool_use'])
        self.assertEqual(plain(bodies[2]['messages'][-2]), {'role': 'assistant', 'content': plain(self.answers[1])})
        self.assertEqual(bodies[2]['messages'][-1]['content'][-1]['text'], 'second plain turn')

        # Append-only: each request repeats the previous one's tools, system and messages.
        def extends(later, earlier):
            later, earlier = plain(later), plain(earlier)
            return (later['tools'] == earlier['tools'] and later['system'] == earlier['system']
                    and later['messages'][:len(earlier['messages'])] == earlier['messages'])
        for index in range(1, 8):
            self.assertTrue(extends(bodies[index], bodies[index-1]), 'request %d rewrote earlier history' % index)

        # Freeform apply_patch and the sandboxed shell.
        self.assertEqual((work/'patched.txt').read_text(), 'hello from claude\n')
        self.assertEqual(plain(bodies[6]['messages'][-2]['content'][-1])['input'], {'input': self.patch})
        shell = json.dumps(bodies[4]['messages'][-1]['content'][0]['content'])
        self.assertIn('HTTP=000', shell)
        self.assertNotIn('KEY_VISIBLE=yes', shell)

        # Compaction: Codex declares no tools; the session's own are sent again and none may be called.
        compaction = bodies[7]
        self.assertEqual(plain(compaction['tools']), plain(bodies[6]['tools']))
        self.assertEqual(compaction['tool_choice'], {'type': 'none'})
        self.assertNotIn('cache_control', compaction)
        self.assertIn('thinking', {block['type'] for message in compaction['messages'] if message['role'] == 'assistant'
                                   for block in message['content']})
        self.assertEqual((records[7]['request_kind'], records[7]['tools_restored']), ('compaction', True))
        after = bodies[8]
        self.assertEqual([message['role'] for message in after['messages']], ['user'])
        self.assertEqual([block['text'] for block in after['system']], ['BASE_INSTRUCTIONS_MARKER'])
        summary = ' '.join(block.get('text', '') for block in after['messages'][0]['content'])
        self.assertIn('HANDOFF_SUMMARY_MARKER', summary)
        self.assertIn('<system-reminder>', summary)
        self.assertEqual(after['cache_control'], {'type': 'ephemeral'})

        # Fork: parent and child both continue the same unchanged prefix, thinking included.
        delegate = next(index for index, blocks in enumerate(self.answers) if blocks[-1].get('name') == 'delegate')
        continuations = [body for body in bodies[delegate+1:] if extends(body, bodies[delegate])]
        self.assertEqual(len(continuations), 2)
        outputs = set()
        for body in continuations:
            turn = body['messages'][len(bodies[delegate]['messages'])]
            self.assertEqual(plain(turn), {'role': 'assistant', 'content': plain(self.answers[delegate])})
            outputs.add(body['messages'][len(bodies[delegate]['messages'])+1]['content'][0]['content'])
        self.assertEqual(outputs, {'aborted', 'delegate result'})
        forked = [record for record in records if record.get('codex_forked_from')]
        self.assertEqual({record['codex_session'] for record in forked}, {native['child']})
        self.assertEqual({record['codex_forked_from'] for record in forked}, {native['parent']})

        # Accounting as Codex reports it: input includes cache reads and writes.
        self.assertEqual(native['usage'][0], {'totalTokens': 1070, 'inputTokens': 1050, 'cachedInputTokens': 900,
                                              'cacheWriteInputTokens': 50, 'outputTokens': 20, 'reasoningOutputTokens': 7})
        for record in records:
            self.assertEqual((record['status'], record['model'], record['upstream_model']),
                             ('completed', 'claude-opus-5-5', 'claude-opus-5-5'))
            self.assertEqual(record['usage']['cache_read_input_tokens'], 900)
            self.assertEqual(record['run'], 'codex-' + (home/'installation_id').read_text().strip()[:8])
        self.assertEqual(len({record['prefix_sha256'] for record in records[:8]}), 1)
        written = log.read_text()
        for secret in (UPSTREAM_KEY, local_key, 'BASE_INSTRUCTIONS_MARKER', 'PARALLEL please', image[:40]):
            self.assertNotIn(secret, written)


if __name__ == '__main__':
    unittest.main()
