"""A robot_only Codex run registers the robot tool and switches Codex's own tools off.

The launch checks need no CLI. The integration test runs the installed Codex CLI against
a local stub provider (nothing reaches a model) and reads the tool list the model is
actually sent on a new thread, a fork and a resumed thread, then lets the stub ask for
each of Codex's own tools; it is skipped when `codex` or `node` is not installed.
"""
from collections import Counter
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from robofrontier.engines.codex.check_codex_broker import NATIVE
from robofrontier.engines.codex.launch import launch_config
from robofrontier.tasks.config import ROOT

OFF = ('shell_tool', 'view_image', 'shell_snapshot', 'unified_exec', 'plugins', 'browser_use', 'computer_use',
       'code_mode', 'code_mode_only', 'code_mode_host', 'multi_agent', 'multi_agent_v2', 'apps', 'goals')
CLIENT = r'''
const fs=require('fs'),path=require('path'),root=process.argv[1],out=process.argv[2];
const {CodexRpc}=require(root+'/robofrontier/engines/codex/codex_rpc');
const {robotTool}=require(root+'/robofrontier/engines/codex/codex_policy_host');
const broker=require(root+'/robofrontier/engines/codex/tool_broker');
const launch=JSON.parse(fs.readFileSync(out+'/launch.json')),scenarios=JSON.parse(fs.readFileSync(out+'/scenarios.json'));
let waits=new Map(),robotCalls=0,otherCalls=[];
const rpc=new CodexRpc(launch.args,{stderr:fs.openSync(out+'/server.log','w'),
  onEvent:m=>{if(m.method==='turn/completed')waits.get(m.params.threadId)?.(m.params.turn);},
  onRequest:async(method,p)=>{
    if(method!=='item/tool/call'||p.tool!=='robot'){otherCalls.push(p?.tool??method);throw new Error('Unsupported host tool');}
    robotCalls++;return {success:true,contentItems:[{type:'inputText',text:'ROBOT-RAN'}]};
  }});
async function turn(id,scenario){
  let timer;const finished=new Promise((resolve,reject)=>{
    waits.set(id,resolve);timer=setTimeout(()=>reject(new Error('Turn timeout: '+scenario)),30000);});
  try{await rpc.call('turn/start',{threadId:id,input:[{type:'text',text:'scenario:'+scenario}]});
    const result=await finished;if(result.status!=='completed')throw new Error(scenario+': '+JSON.stringify(result.error));
  }finally{clearTimeout(timer);waits.delete(id);}
}
(async()=>{
 const threads=[];
 try{
  await rpc.initialize();await broker.admit(rpc,launch);
  if(broker.enabled(launch)||!broker.robotOnly(launch))throw new Error('Not a robot_only launch');
  const parent=(await rpc.call('thread/start',{cwd:out+'/workspace',model:launch.model,modelProvider:launch.provider,
    approvalPolicy:'never',dynamicTools:[robotTool,...(broker.enabled(launch)?broker.tools:[])],
    baseInstructions:'Offline robot_only protocol check. No robot world.',
    config:{web_search:'disabled','features.multi_agent':false}})).thread.id;
  threads.push(parent);
  for(const scenario of scenarios)await turn(parent,scenario);
  const child=await rpc.call('thread/fork',{threadId:parent,cwd:out+'/workspace',model:launch.model,
    modelProvider:launch.provider,excludeTurns:true,ephemeral:false});
  threads.push(child.thread.id);await turn(child.thread.id,'fork');
  await rpc.call('thread/resume',{threadId:child.thread.id,cwd:out+'/workspace',model:launch.model,excludeTurns:true});
  await turn(child.thread.id,'resume');
  fs.writeFileSync(out+'/client-report.json',JSON.stringify({robot_calls:robotCalls,other_host_calls:otherCalls,
    fork_verified:child.thread.forkedFromId===parent}));
 }finally{
  for(const threadId of threads)try{await rpc.call('thread/archive',{threadId});}catch{}
  await rpc.close();
 }
})().then(()=>process.exit(0)).catch(e=>{console.error(e.stack);process.exit(1)});
'''


def offline_profile(**extra):
    return dict(model='offline-robot-only', provider='offline_protocol', effort='high', vision=True,
                context_window=300000, auto_compact_token_limit=267000, use_cached_model_metadata=False,
                base_url='http://127.0.0.1:1', env_key='ROBOFRONTIER_OFFLINE_STUB_TOKEN', **extra)


def overrides(launch):
    args = launch['args']
    pairs = [args[n + 1].split('=', 1) for n in range(len(args) - 1) if args[n] == '-c']
    return {key: json.loads(value) for key, value in pairs if not value.startswith(('[', '{')) or key != 'skills.config'}


class LaunchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.folder = Path(self.tmp.name)
        self.previous = os.environ.get('CODEX_HOME'); os.environ['CODEX_HOME'] = str(self.folder/'home')

    def tearDown(self):
        if self.previous is None: os.environ.pop('CODEX_HOME', None)
        else: os.environ['CODEX_HOME'] = self.previous
        self.tmp.cleanup()

    def test_robot_only_switches_codex_tools_off_without_the_tool_worker(self):
        launch = launch_config(offline_profile(tool_mode='robot_only'), self.folder)
        values = overrides(launch)
        for flag in OFF:
            self.assertIs(values['features.' + flag], False, flag)
        self.assertIs(values['agents.enabled'], False)
        self.assertEqual(values['web_search'], 'disabled')
        model = json.loads((self.folder/'models.json').read_text())['models'][0]
        self.assertIsNone(model['apply_patch_tool_type'])
        self.assertEqual(model['multi_agent_version'], 'disabled')
        self.assertTrue(model['node_repl_disabled'])
        self.assertEqual(model['experimental_supported_tools'], [])
        self.assertEqual((launch['tool_backend'], launch['tool_mode']), ('native', 'robot_only'))
        self.assertIsNone(launch['tool_backend_sha256'])

    def test_a_full_native_launch_is_what_it_was(self):
        launch = launch_config(offline_profile(), self.folder)
        values = overrides(launch)
        self.assertNotIn('tool_mode', launch)
        self.assertNotIn('features.shell_tool', values)
        self.assertNotIn('features.view_image', values)
        self.assertEqual(json.loads((self.folder/'models.json').read_text())['models'][0]['apply_patch_tool_type'], 'freeform')
        explicit = launch_config(offline_profile(tool_mode='full'), self.folder)
        self.assertEqual(explicit['args'], launch['args'])
        self.assertNotIn('tool_mode', explicit)

    def test_robot_only_with_the_tool_worker_is_refused(self):
        with self.assertRaises(ValueError):
            launch_config(offline_profile(tool_mode='robot_only', tool_backend='landlock-v1'), self.folder)
        with self.assertRaises(ValueError):
            launch_config(offline_profile(tool_mode='no_shell'), self.folder)


@unittest.skipUnless(shutil.which('codex') and shutil.which('node'), 'Codex CLI or node is not installed')
class RealCliTests(unittest.TestCase):
    def test_the_model_is_sent_only_the_robot_tool_and_codex_tools_do_not_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp).resolve()
            (output/'workspace').mkdir(); home = output/'codex-home'; home.mkdir(mode=0o700)
            marker = output/'NATIVE_EXECUTED'
            requests, outputs, counts = [], {}, Counter()

            class Handler(BaseHTTPRequestHandler):
                def log_message(self, *args): pass

                def do_POST(self):
                    body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    requests.append(body)
                    scenario = re.findall(r'scenario:([a-z_0-9]+)', json.dumps(body.get('input', [])))[-1]
                    counts[scenario] += 1
                    if counts[scenario] == 1:
                        name, args = 'robot', {'op': 'ready', 'data': {}}
                        if scenario in NATIVE:
                            name = NATIVE[scenario]
                            args = {'cmd': 'touch ' + str(marker), 'command': 'touch ' + str(marker),
                                    'path': str(output/'launch.json'), 'session_id': 999999}
                        elif scenario in ('policy_exec', 'policy_image'):
                            name, args = scenario, {'command': 'touch ' + str(marker), 'path': str(output/'launch.json')}
                        item = dict(id='fc_' + scenario, type='function_call', call_id='call_' + scenario, name=name,
                                    arguments=json.dumps(args), status='completed')
                        if scenario == 'native_freeform':
                            item = dict(id='fc_' + scenario, type='custom_tool_call', call_id='call_' + scenario, name=name,
                                        input='*** Begin Patch\n*** Add File: ' + str(marker) + '\n+bad\n*** End Patch',
                                        status='completed')
                    else:
                        done = [x for x in body.get('input', []) if x.get('type') in ('function_call_output', 'custom_tool_call_output')]
                        outputs[scenario] = done[-1].get('output') if done else None
                        item = dict(id='msg_' + scenario, type='message', role='assistant', status='completed',
                                    content=[dict(type='output_text', text='OK', annotations=[])])
                    response = dict(id='resp_' + str(len(requests)), object='response', created_at=int(time.time()),
                                    status='completed', model=body.get('model'), output=[item],
                                    usage=dict(input_tokens=10, output_tokens=10, total_tokens=20,
                                               input_tokens_details={'cached_tokens': 0},
                                               output_tokens_details={'reasoning_tokens': 0}))
                    self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
                    for index, (kind, data) in enumerate([
                            ('response.created', {'response': {**response, 'status': 'in_progress', 'output': []}}),
                            ('response.output_item.added', {'output_index': 0, 'item': {**item, 'status': 'in_progress'}}),
                            ('response.output_item.done', {'output_index': 0, 'item': item}),
                            ('response.completed', {'response': response})]):
                        self.wfile.write(('event: ' + kind + '\ndata: ' + json.dumps(
                            {'type': kind, 'sequence_number': index, **data}) + '\n\n').encode())
                    self.wfile.flush()
            server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            previous = os.environ.get('CODEX_HOME'); os.environ['CODEX_HOME'] = str(home)
            try:
                profile = offline_profile(tool_mode='robot_only')
                profile['base_url'] = 'http://127.0.0.1:%d' % server.server_port
                launch = launch_config(profile, output)
                (output/'launch.json').write_text(json.dumps(launch))
                scenarios = ['robot', *NATIVE, 'policy_exec', 'policy_image']
                (output/'scenarios.json').write_text(json.dumps(scenarios))
                env = {'PATH': os.environ['PATH'], 'LANG': 'C.UTF-8', 'CODEX_HOME': str(home),
                       'ROBOFRONTIER_OFFLINE_STUB_TOKEN': 'local-stub-no-credential'}
                result = subprocess.run(['node', '-e', CLIENT, str(ROOT), str(output)], env=env, capture_output=True,
                                        text=True, timeout=240)
            finally:
                server.shutdown(); server.server_close()
                if previous is None: os.environ.pop('CODEX_HOME', None)
                else: os.environ['CODEX_HOME'] = previous
            version = subprocess.run(['codex', '--version'], capture_output=True, text=True).stdout.strip()
            self.assertEqual(result.returncode, 0, version + ': ' + result.stderr[-2500:])
            inventories = [sorted(t.get('name', t.get('type')) for t in r.get('tools', [])) for r in requests]
            self.assertTrue(inventories)
            for tools in inventories:
                self.assertEqual(tools, ['robot'], version)
            # The fork and the resumed thread each made requests of their own.
            self.assertEqual(counts['fork'], 2); self.assertEqual(counts['resume'], 2)
            client = json.loads((output/'client-report.json').read_text())
            self.assertTrue(client['fork_verified'])
            self.assertEqual(client['robot_calls'], 3)  # The parent, the fork and the resumed thread.
            self.assertEqual(client['other_host_calls'], [])
            self.assertIn('ROBOT-RAN', json.dumps(outputs['robot']))
            for name in [*NATIVE, 'policy_exec', 'policy_image']:
                self.assertIn('unsupported', json.dumps(outputs.get(name)).lower(), (version, name))
            self.assertFalse(marker.exists())
            self.assertEqual(sorted(p.name for p in (output/'workspace').iterdir()), [])


if __name__ == '__main__':
    unittest.main()
