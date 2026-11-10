"""Codex enforces the run's frozen access table (robofrontier/runtime/access.py).

The integration test drives the installed `codex app-server` with a LOCAL
Responses stub that issues shell, patch and image calls; no external inference,
credentials or robot world are involved. It is skipped when `codex` or `node`
is missing.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from robofrontier.runtime import access as policy_access
from robofrontier.runtime.layout import manifest_record
from robofrontier.engines.codex.launch import hidden_skills, launch_config

ROOT = Path(__file__).resolve().parents[1]
STUB = dict(model='offline-protocol', provider='offline_protocol', effort='high', vision=True,
            context_window=272000, auto_compact_token_limit=258400, env_key='ROBOFRONTIER_OFFLINE_STUB_TOKEN')


OUTPUT_TYPES = ('function_call_output', 'custom_tool_call_output')


def responses_stub(requests, steps, namespace=None, before=None):
    """Replay `steps[turn_text]`: one tool call per request until the list is used up.

    A step is (name, input); apply_patch is a freeform custom tool, the others take JSON.
    `namespace` addresses function calls to a tool namespace, such as an MCP server.
    `before(turn, index)` runs just before step `index` of that turn is sent.
    """
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args): pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length']))); requests.append(body)
            items = [x for x in body.get('input', []) if isinstance(x, dict)]
            last_user = max((i for i, x in enumerate(items) if x.get('role') == 'user'), default=-1)
            answered = sum(x.get('type') in OUTPUT_TYPES for x in items[last_user + 1:])
            turn = steps['go-child' if last_user >= 0 and 'go-child' in json.dumps(items[last_user]) else 'go']
            n = len(requests)
            if before is not None: before(turn, answered)
            if answered < len(turn):
                name, data = turn[answered]
                item = (dict(id='ct_%d' % n, type='custom_tool_call', call_id='call_%d' % n, name=name, input=data, status='completed')
                        if name == 'apply_patch' else
                        dict(id='fc_%d' % n, type='function_call', call_id='call_%d' % n, name=name,
                             arguments=json.dumps(data), status='completed', **({'namespace': namespace} if namespace else {})))
            else:
                item = dict(id='msg_%d' % n, type='message', role='assistant', status='completed',
                            content=[dict(type='output_text', text='DONE', annotations=[])])
            response = dict(id='resp_%d' % len(requests), object='response', created_at=int(time.time()), status='completed',
                            model=body.get('model'), output=[item],
                            usage=dict(input_tokens=1, output_tokens=1, total_tokens=2,
                                       input_tokens_details={'cached_tokens': 0}, output_tokens_details={'reasoning_tokens': 0}))
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            events = [('response.created', {'response': {**response, 'status': 'in_progress', 'output': []}}),
                      ('response.output_item.added', {'output_index': 0, 'item': {**item, 'status': 'in_progress'}}),
                      ('response.output_item.done', {'output_index': 0, 'item': item}),
                      ('response.completed', {'response': response})]
            for i, (kind, data) in enumerate(events):
                self.wfile.write(('event: %s\ndata: %s\n\n' % (kind, json.dumps({'type': kind, 'sequence_number': i, **data}))).encode())
            self.wfile.flush()
    return Handler


DRIVER = r'''
const fs=require('fs'),{CodexRpc}=require(process.argv[1]+'/robofrontier/engines/codex/codex_rpc');
const out=process.argv[2],launch=JSON.parse(fs.readFileSync(out+'/launch.json')),run=fs.readFileSync(out+'/run.txt','utf8');
process.env.ROBOFRONTIER_OFFLINE_STUB_TOKEN='local-stub-no-credential';
(async()=>{let done;
const rpc=new CodexRpc(launch.args,{stderr:fs.openSync(out+'/server.log','w'),
  onEvent:m=>{if(m.method==='turn/completed'&&done)done();},onRequest:async()=>{throw new Error('no host tools');}});
const turn=async(threadId,text)=>{const finished=new Promise(r=>done=r);
  await rpc.call('turn/start',{threadId,model:launch.model,effort:launch.effort,input:[{type:'text',text}]});
  await Promise.race([finished,new Promise((_,j)=>setTimeout(()=>j(new Error('turn timeout')),60000))]);};
await rpc.initialize();
const parent=(await rpc.call('thread/start',{model:launch.model,modelProvider:launch.provider,cwd:run,approvalPolicy:'never',ephemeral:false})).thread.id;
await turn(parent,'go');
const child=(await rpc.call('thread/fork',{threadId:parent,cwd:run,model:launch.model,modelProvider:launch.provider,excludeTurns:true,ephemeral:false})).thread.id;
await turn(child,'go-child');
await rpc.close();})().catch(e=>{console.error(e.stack);process.exit(1);});'''


@unittest.skipUnless(shutil.which('codex') and shutil.which('node'), 'Codex CLI or node is not installed')
class AppServerPermissionTests(unittest.TestCase):
    def test_profile_applies_to_policy_and_forked_threads(self):
        with tempfile.TemporaryDirectory() as tmp:
            t = Path(tmp).resolve(); repo, home = t / 'repo', t / 'home'
            run, other = repo / 'runs/batch/profile/case-a', repo / 'runs/batch/profile/case-b'
            files = {run / 'public/inputs/task.json': 'PUBLIC-TASK', run / 'private/inputs/task.json': 'OWN-ANSWER',
                     other / 'private/inputs/task.json': 'OTHER-ANSWER', repo / 'configs/task.json': 'REPO-ANSWER',
                     repo / '.env': 'ENV-SECRET', home / '.codex/auth.json': 'HOME-SECRET'}
            for path, text in files.items():
                path.parent.mkdir(parents=True, exist_ok=True); path.write_text(text)
            for name in ('workspace', 'public/results'): (run / name).mkdir(parents=True, exist_ok=True)
            # A run-v6 run: the policy works in workspace/, the only place it can write.
            (run / 'private/inputs/manifest.json').write_text(json.dumps(manifest_record('codex')))
            (run / 'private/inputs/policy-access.json').write_text(json.dumps(
                policy_access.record(run, repo=repo, home=home, tmp_dirs=(), checkouts=[repo])))
            # No AGENTS.md is injected; personal and live repo skills are not listed, bundled ones are.
            (run / 'AGENTS.md').write_text('RUN-AGENTS-MD'); (repo / 'AGENTS.md').write_text('REPO-AGENTS-MD')
            for root, name in ((repo, 'repo-skill'), (home, 'personal-skill')):
                (root / '.agents/skills' / name).mkdir(parents=True)
                (root / '.agents/skills' / name / 'SKILL.md').write_text('---\nname: %s\ndescription: %s-LISTED\n---\nx' % (name, name.upper()))
            subprocess.run(['git', 'init', '-q', str(repo)], check=True)
            secrets = ' '.join(str(p) for p in (repo / 'configs/task.json', other / 'private/inputs/task.json',
                                                 run / 'private/inputs/task.json', repo / '.env', home / '.codex/auth.json'))
            for name, marker in (('probe.sh', 'PARENT'), ('probe-child.sh', 'CHILD')):
                # Absolute paths: the policy's working directory is workspace/.
                (run / name).write_text('\n'.join(['cat %s' % secrets, 'cat %s/public/inputs/task.json' % run,
                                                   'echo x > %s/root.txt && echo %s-WROTE-ROOT' % (run, marker),
                                                   'echo x > %s/workspace/%s.txt && echo %s-WROTE-SCRATCH' % (run, marker, marker),
                                                   'echo x > %s/private/%s.txt && echo %s-WROTE-PRIVATE' % (run, marker, marker)]))
            from PIL import Image
            Image.new('RGB', (8, 8), 'red').save(run / 'private/secret.png')
            Image.new('RGB', (8, 8), 'blue').save(run / 'public/view.png')

            def add_file(path): return '*** Begin Patch\n*** Add File: %s\n+x\n*** End Patch\n' % path
            shell = lambda script: ('exec_command', {'cmd': 'sh ' + str(run / script), 'login': False})
            steps = {'go': [shell('probe.sh'),
                            ('apply_patch', add_file(run / 'workspace/patched.txt')),
                            ('apply_patch', add_file(run / 'private/patched.txt')),
                            ('apply_patch', add_file(run / 'public/inputs/patched.txt')),
                            ('apply_patch', add_file(run / '.agents/skills/mine/SKILL.md')),
                            ('apply_patch', add_file(run / 'public/results/Controller-notes.md')),
                            ('apply_patch', add_file(run / 'workspace/notes/Controller.md')),
                            ('apply_patch', add_file(run / 'root-patch.txt')),
                            ('apply_patch', add_file(home / 'patched.txt')),
                            ('view_image', {'path': str(run / 'private/secret.png')}),
                            ('view_image', {'path': str(run / 'public/view.png')})],
                     'go-child': [shell('probe-child.sh')]}
            requests = []
            server = ThreadingHTTPServer(('127.0.0.1', 0), responses_stub(requests, steps))
            threading.Thread(target=server.serve_forever, daemon=True).start()
            try:
                out = t / 'out'; (run / 'private/inputs').mkdir(parents=True, exist_ok=True); out.mkdir()
                stub = dict(STUB, base_url='http://127.0.0.1:%d' % server.server_port)
                with patch('robofrontier.engines.codex.launch.hidden_skills', lambda: hidden_skills(home=home, repo=repo)):
                    launch = launch_config(stub, out, run_dir=run)
                (out / 'launch.json').write_text(json.dumps(launch)); (out / 'run.txt').write_text(str(run / 'workspace'))
                # Persisted threads (needed for fork) go to a throwaway Codex home, never the user's.
                env = dict(os.environ, CODEX_HOME=str(t / 'codex-home'), HOME=str(home)); (t / 'codex-home').mkdir()
                done = subprocess.run(['node', '-e', DRIVER, str(ROOT), str(out)], text=True, capture_output=True,
                                      timeout=180, env=env)
            finally:
                server.shutdown(); server.server_close()
            self.assertEqual(done.returncode, 0, done.stderr[-800:])
            # What the model received from each tool call, in call order.
            seen = {}
            for body in requests:
                for item in body.get('input', []):
                    if isinstance(item, dict) and item.get('type') in OUTPUT_TYPES:
                        seen.setdefault(item['call_id'], json.dumps(item['output']))
            seen = list(seen.values())
            self.assertEqual(len(seen), 12, seen)
            patch_scratch, patch_private, patch_frozen, patch_agents, patch_evidence, patch_skill, patch_root, patch_outside, view_private, view_public = seen[1:11]
            self.assertIn('Success', patch_scratch)
            self.assertTrue((run / 'workspace/patched.txt').is_file())
            for rejected in (patch_private, patch_frozen, patch_agents, patch_evidence, patch_root, patch_outside): self.assertIn('rejected', rejected)
            for stray in ('root.txt', 'root-patch.txt'): self.assertFalse((run / stray).exists(), stray)
            self.assertIn('Success', patch_skill)
            self.assertTrue((run / 'workspace/notes/Controller.md').is_file())
            self.assertFalse((run / 'public/results/Controller-notes.md').exists())
            self.assertFalse((run / '.agents').exists())
            self.assertFalse((run / 'private/patched.txt').exists())
            self.assertFalse((run / 'public/inputs/patched.txt').exists())
            sent = json.dumps(requests)
            for loaded in ('RUN-AGENTS-MD', 'REPO-AGENTS-MD', 'REPO-SKILL-LISTED', 'PERSONAL-SKILL-LISTED'): self.assertNotIn(loaded, sent)
            self.assertIn('skill-creator', sent)
            self.assertFalse((home / 'patched.txt').exists())
            self.assertIn('Operation not permitted', view_private)
            self.assertNotIn('input_image', view_private)
            self.assertIn('input_image', view_public)
            for text, marker in ((seen[0], 'PARENT'), (seen[11], 'CHILD')):
                role = marker.lower()
                self.assertIn('PUBLIC-TASK', text, role)
                self.assertIn(marker + '-WROTE-SCRATCH', text)
                self.assertNotIn(marker + '-WROTE-PRIVATE', text)
                self.assertNotIn(marker + '-WROTE-ROOT', text)
                for secret in ('OWN-ANSWER', 'OTHER-ANSWER', 'REPO-ANSWER', 'ENV-SECRET', 'HOME-SECRET'):
                    self.assertNotIn(secret, text, role)
                self.assertFalse((run / ('private/%s.txt' % marker)).exists())


if __name__ == '__main__': unittest.main()
