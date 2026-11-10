"""Desktop robot MCP: thread-bound role lookup, and the real app-server passing the thread.

The integration test uses a LOCAL Responses stub and a fake execution service;
no inference, credentials or physics. Skipped without `codex` or `node`.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest

from robofrontier.engines.codex.desktop_robot_mcp import SERVER, DesktopRobotBridge, bound_role, calling_thread

ROOT = Path(__file__).resolve().parents[2]
THREAD = '01a19877-10bc-78a1-8113-bf51f6786dd5'
OTHER = '01a19877-10bc-78a1-8113-bf51f6786dd6'


def make_run(root, agents):
    """A run directory with a runtime DB holding `agents` and a connection per policy role."""
    run = root / 'policy/batch/profile/case'
    (run / 'private/state/connections').mkdir(parents=True); (run / 'public/inputs').mkdir(parents=True)
    db = sqlite3.connect(run / 'private/state/runtime.sqlite')
    db.execute('CREATE TABLE agents (id TEXT PRIMARY KEY, value TEXT)')
    for actor, agent in agents.items():
        db.execute('INSERT INTO agents VALUES (?,?)', (actor, json.dumps(agent)))
        (run / 'private/state/connections' / (actor + '.json')).write_text(json.dumps(
            {'actor': actor, 'run_id': run.name, 'schema_version': 3, 'url': 'http://127.0.0.1:9', 'token': 't'}))
    db.commit(); db.close()
    return run


class ThreadBindingTests(unittest.TestCase):
    def test_role_comes_only_from_the_thread_binding(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp), {'Meta': {'kind': 'manager', 'thread_id': OTHER},
                                       'Controller': {'kind': 'controller', 'thread_id': THREAD},
                                       'Delegate_aaaaaaaaaaaa': {'kind': 'delegate', 'thread_id': 'x', 'delegation_state': 'finished'}})
            database = run / 'private/state/runtime.sqlite'
            self.assertEqual(bound_role(database, THREAD), 'Controller')
            self.assertIsNone(bound_role(database, OTHER))  # the manager is never a policy role
            self.assertIsNone(bound_role(database, 'x'))  # a finished delegate keeps no access
            self.assertIsNone(bound_role(database, 'unbound'))
            self.assertEqual(calling_thread({'_meta': {'threadId': THREAD}}), THREAD)
            self.assertEqual(calling_thread({'_meta': {'x-codex-turn-metadata': {'thread_id': THREAD}}}), THREAD)
            with self.assertRaisesRegex(ValueError, 'thread'): calling_thread({})

    def test_call_uses_the_bound_connection_and_a_stable_role_scoped_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            run = make_run(Path(tmp), {'Controller': {'kind': 'controller', 'thread_id': THREAD}})
            calls = []
            bridge = DesktopRobotBridge(tmp, invoke=lambda conn, op, data, call_id, log_call_id: calls.append(
                (Path(conn), op, data, call_id)) or {'ok': True})
            meta = {'_meta': {'threadId': THREAD, 'callId': 'call_7'}}
            result = bridge.call({'op': 'move', 'data': {'robot': 'A'}, 'views': ['top']}, meta)
            self.assertEqual(calls[0][0], run.resolve() / 'private/state/connections/Controller.json')
            self.assertEqual(calls[0][2], {'robot': 'A', 'cameras': ['top']})
            self.assertEqual(calls[0][3], 'Controller-call_7')
            self.assertIn('Controller-call_7', result['content'][0]['text'])
            with self.assertRaisesRegex(ValueError, 'administrative'):
                bridge.call({'op': 'seal', 'data': {}}, meta)
            with self.assertRaisesRegex(ValueError, 'not bound'):
                bridge.call({'op': 'inbox', 'data': {}}, {'_meta': {'threadId': OTHER}})


class FakeService(BaseHTTPRequestHandler):
    image = None
    def log_message(self, *args): pass
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        data = json.dumps({'actor_served': body['actor'], 'observation': {'images': {'top': str(self.image)}}}).encode()
        self.send_response(200); self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(data))); self.end_headers(); self.wfile.write(data)


DRIVER = r'''
const fs=require('fs'),{execFileSync}=require('child_process'),{CodexRpc}=require(process.argv[1]+'/robofrontier/engines/codex/codex_rpc');
const out=process.argv[2],launch=JSON.parse(fs.readFileSync(out+'/launch.json')),run=fs.readFileSync(out+'/run.txt','utf8');
process.env.ROBOFRONTIER_OFFLINE_STUB_TOKEN='local-stub-no-credential';
(async()=>{let done;
const rpc=new CodexRpc(launch.args,{stderr:fs.openSync(out+'/server.log','w'),onEvent:m=>{if(m.method==='turn/completed'&&done)done();},
  onRequest:async()=>{throw new Error('no host tools');}});
const turn=async(threadId,text)=>{const finished=new Promise(r=>done=r);
  await rpc.call('turn/start',{threadId,model:launch.model,effort:launch.effort,input:[{type:'text',text}]});
  await Promise.race([finished,new Promise((_,j)=>setTimeout(()=>j(new Error('turn timeout')),60000))]);};
await rpc.initialize();
const start=async()=>(await rpc.call('thread/start',{model:launch.model,modelProvider:launch.provider,cwd:run,approvalPolicy:'never',ephemeral:true})).thread.id;
const bound=await start();
// What Meta does for a Desktop role: record the thread binding in the runtime DB.
execFileSync(process.argv[3],['-c',"import sqlite3,json,sys;d=sqlite3.connect(sys.argv[1]);d.execute('UPDATE agents SET value=? WHERE id=?',(json.dumps({'kind':'controller','thread_id':sys.argv[2]}),'Controller'));d.commit()",run+'/private/state/runtime.sqlite',bound]);
await turn(bound,'go');
await turn(await start(),'go-unbound');
await rpc.close();})().catch(e=>{console.error(e.stack);process.exit(1);});'''


@unittest.skipUnless(shutil.which('codex') and shutil.which('node'), 'Codex CLI or node is not installed')
class AppServerDesktopToolTests(unittest.TestCase):
    def test_bound_thread_operates_its_role_and_unbound_thread_is_refused(self):
        from engines.test_codex_policy_permissions import STUB, OUTPUT_TYPES, responses_stub
        from robofrontier.engines.codex.launch import launch_config
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve(); runs = t / 'runs'
            run = make_run(runs, {'Meta': {'kind': 'manager', 'thread_id': None},
                                  'Controller': {'kind': 'controller', 'thread_id': None}})
            image = run / 'public/observations/top.png'; image.parent.mkdir(parents=True)
            Image.new('RGB', (4, 4), 'green').save(image); FakeService.image = image
            service = ThreadingHTTPServer(('127.0.0.1', 0), FakeService)
            connection = run / 'private/state/connections/Controller.json'
            connection.write_text(json.dumps({**json.loads(connection.read_text()), 'url': 'http://127.0.0.1:%d' % service.server_port}))
            call = ('robot', {'op': 'observe', 'data': {}, 'views': ['top']})
            steps = {'go': [call], 'go-child': [call]}
            requests = []
            model = ThreadingHTTPServer(('127.0.0.1', 0), responses_stub(requests, steps, namespace='mcp__' + SERVER))
            for server in (service, model): threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                out = t / 'out'; out.mkdir(); (t / 'codex-home').mkdir()
                launch = launch_config(dict(STUB, base_url='http://127.0.0.1:%d' % model.server_port), out)
                prefix = 'mcp_servers.%s.' % SERVER
                launch['args'] += ['-c', prefix + 'command=' + json.dumps(sys.executable),
                                   '-c', prefix + 'args=' + json.dumps(['-m', 'robofrontier.engines.codex.desktop_robot_mcp', '--runs-root', str(runs)]),
                                   '-c', prefix + 'env={PYTHONPATH=' + json.dumps(str(ROOT)) + '}',
                                   '-c', prefix + 'default_tools_approval_mode="approve"']
                (out / 'launch.json').write_text(json.dumps(launch)); (out / 'run.txt').write_text(str(run))
                done = subprocess.run(['node', '-e', DRIVER, str(ROOT), str(out), sys.executable], text=True, capture_output=True,
                                      timeout=180, env=dict(os.environ, CODEX_HOME=str(t / 'codex-home')))
            finally:
                for server in (service, model): server.shutdown(); server.server_close()
            self.assertEqual(done.returncode, 0, done.stderr[-800:])
            seen = {}
            for body in requests:
                for item in body.get('input', []):
                    if isinstance(item, dict) and item.get('type') in OUTPUT_TYPES:
                        seen.setdefault(item['call_id'], json.dumps(item['output']))
            bound, unbound = list(seen.values())
            self.assertIn('actor_served', bound)
            self.assertIn('Controller', bound)
            self.assertIn('image', bound)
            self.assertNotIn('actor_served', unbound)
            self.assertIn('not bound', unbound)


if __name__ == '__main__': unittest.main()
