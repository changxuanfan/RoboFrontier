"""Real Claude CLI, runtime and MCP over loopback synthetic model/world only."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import unittest

from fake_pipeline import FakeWorld, fake_capture
from robofrontier.engines.claude.adaptive_policy_host import AdaptivePolicyHost
from robofrontier.engines.claude.adaptive_setup import AdaptiveForkSetup, child_prompt
from robofrontier.engines.claude.fork_setup import create_fork
from robofrontier.engines.claude.budget import BudgetLedger
from robofrontier.engines.claude.native_home import history_directory
from robofrontier.engines.claude.provenance import first_input, history, transcript_rows
from robofrontier.engines.claude.robot_mcp import RobotBridge
from robofrontier.runtime.setup import prepare_run
from robofrontier.runtime.service import RuntimeService

ROOT=Path(__file__).resolve().parents[2]
# Runs the Codex route's own dispatcher with a fake native adapter and prints the first
# message it sends the child (argv: repository, run directory, child scope).
CODEX_FIRST_MESSAGE='''
const [root,runDir,given]=process.argv.slice(1),child=JSON.parse(given);
const {runMetaDispatcher}=require(root+'/robofrontier/engines/codex/meta_dispatcher.js');
const batch={id:'b',source_thread_id:'parent',status:'creating',claimed_by:null,
  children:[{actor:child.actor,robots:child.robots,goal:child.goal,done_when:child.done_when,constraints:child.constraints}]};
let forks=0,prompt=null;
const tools={exec_command:async({cmd})=>{
  let value={recorded:true};
  if(cmd.includes(' snapshot '))value={lifecycle:'running',paused:false,config:{poll_interval_s:0,model:'m',effort:'high',engine:'codex'},
    agents:{Controller:{kind:'controller',thread_id:'parent'}},delegations:batch.status==='creating'?[batch]:[]};
  else if(cmd.includes(' delegate-claim '))value={delegation:structuredClone(batch)};
  else if(cmd.includes(' delegate-activate '))batch.status='active';
  else if(cmd.includes(' delegate-started '))value={recorded:true,status:'active'};
  else if(cmd.includes(' plan '))value={commands:[]};
  return {exit_code:0,output:JSON.stringify(value)};
}};
const adapter={observe:async p=>({thread:{id:p.threadId,status:{type:'idle'}},latestTurn:{id:'t0',status:'completed'}}),
  fork:async p=>({threadId:'thread-'+(++forks),sourceThreadId:p.threadId,status:'created'}),
  send:async p=>{prompt=p.prompt;return {threadId:p.threadId};}};
runMetaDispatcher({runDir,python:'/fake',cwd:'/fake',tools,adapter,maxCycles:1}).then(()=>process.stdout.write(prompt));
'''


class StubModel(http.server.BaseHTTPRequestHandler):
    requests=[]
    asked=threading.Event(); asked_at=None
    def log_message(self,*args): pass
    def reply_text(self, body, text, blocks): return 'done'
    def choose_tool(self, names, text, blocks, has_result):
        if names and not has_result:
            if 'Your current runtime role is Delegate_' in text:
                return {'op':'return_task','data':{'outcome':'completed','result':'synthetic evidence'}}, 'toolu_return'
            if 'wake_id=' in text or 'experiment has STARTED' in text or 'experiment has started' in text or not text:
                return {'op':'delegate','data':{'scopes':[{'robots':['A'],'goal':'synthetic','done_when':'synthetic'}]}}, 'toolu_delegate'
            return {'op':'ready','data':{}}, 'toolu_ready'
        return None, None
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.request_body=body
        self.requests.append(body)
        names=[x['name'] for x in body.get('tools',[]) if 'robot' in x.get('name','')]
        messages=body.get('messages',[])
        # The CLI adds its own notices (sandbox description, budget, idle reminder) as
        # text blocks or whole user messages; the script reacts only to host prompts and
        # tool results, so it reads the latest message that has any.
        notice=lambda x:isinstance(x,dict) and x.get('type')=='text' and str(x.get('text','')).startswith(
            ('## Bash command sandbox','USD budget','The user hasn'))
        text,blocks='',[]
        for message in reversed(messages):
            content=message.get('content',[])
            if isinstance(content,str):
                if not content.startswith(('USD budget','The user hasn')): text=content; break
                continue
            blocks=[x for x in content if not notice(x)]
            if blocks:
                text=' '.join(str(x.get('text','')) for x in blocks if isinstance(x,dict)); break
        # Claude may coalesce a prior tool result and a new wake in one user
        # message. Only a final tool-result block means the tool just returned.
        has_result=bool(blocks and isinstance(blocks[-1],dict) and blocks[-1].get('type')=='tool_result')
        tool, ident=self.choose_tool(names,text,blocks,has_result)
        if ident=='toolu_return' and not StubModel.asked.is_set():
            StubModel.asked_at=time.time(); StubModel.asked.set()
        content=[{'type':'tool_use','id':ident,'name':names[0],'input':tool}] if tool else [{'type':'text','text':self.reply_text(body,text,blocks)}]
        reason='tool_use' if tool else 'end_turn'
        message={'id':'msg_stub','type':'message','role':'assistant','model':'claude-opus-5-5',
                 'content':content,'stop_reason':reason,'stop_sequence':None,'usage':{'input_tokens':10,'output_tokens':4}}
        if body.get('stream'):
            events=[('message_start',{'type':'message_start','message':{**message,'content':[],'stop_reason':None}})]
            for idx,item in enumerate(content):
                initial={'type':'tool_use','id':item['id'],'name':item['name'],'input':{}} if tool else {'type':'text','text':''}
                delta={'type':'input_json_delta','partial_json':json.dumps(item['input'])} if tool else {'type':'text_delta','text':item['text']}
                events += [('content_block_start',{'type':'content_block_start','index':idx,'content_block':initial}),
                           ('content_block_delta',{'type':'content_block_delta','index':idx,'delta':delta}),
                           ('content_block_stop',{'type':'content_block_stop','index':idx})]
            events += [('message_delta',{'type':'message_delta','delta':{'stop_reason':reason,'stop_sequence':None},'usage':{'output_tokens':4}}),
                       ('message_stop',{'type':'message_stop'})]
            raw=''.join('event: '+name+'\ndata: '+json.dumps(data)+'\n\n' for name,data in events).encode(); kind='text/event-stream'
        else: raw=json.dumps(message).encode(); kind='application/json'
        self.send_response(200); self.send_header('Content-Type',kind); self.send_header('Content-Length',str(len(raw)))
        self.end_headers()
        try: self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError): pass  # The supervisor may stop an in-flight turn.


@unittest.skipUnless(shutil.which('claude'),'Claude CLI is not installed')
class AdaptiveIntegrationTests(unittest.TestCase):
    def test_cli_runtime_delegate_fork_and_return(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); config=json.loads((ROOT/'configs/harnesses/policy.json').read_text())
            config.update(engine='claude',topology='adaptive',model='claude-opus-5-5',effort='high')
            config_path=root/'config.json'; config_path.write_text(json.dumps(config))
            run=prepare_run(root/'run',harness_path=config_path)
            model=http.server.ThreadingHTTPServer(('127.0.0.1',0),StubModel)
            profile={'model':'claude-opus-5-5','effort':'high','env_key':'FAKE_KEY',
                     'base_url':f'http://127.0.0.1:{model.server_port}'}
            prompt=run/'public/inputs/claude-controller.md'; prompt.write_text((ROOT/'prompts/archive/claude/controller.md').read_text())
            launch=run/'private/inputs/claude.json'; launch.write_text(json.dumps({'profile':profile}))
            manifest_path=run/'private/inputs/manifest.json'; manifest=json.loads(manifest_path.read_text())
            for path in (prompt,launch): manifest['input_sha256'][str(path.relative_to(run))]=hashlib.sha256(path.read_bytes()).hexdigest()
            manifest_path.write_text(json.dumps(manifest))
            service=RuntimeService(run,FakeWorld,fake_capture); done=threading.Event(); ops=[]
            class World(http.server.BaseHTTPRequestHandler):
                def log_message(self,*args): pass
                def do_POST(self):
                    data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
                    if self.path!='/op' or service.tokens.get(data['actor'])!=self.headers.get('X-Token'):
                        self.send_error(403); return
                    ops.append((time.time(),data['actor'],data['op']))
                    with service.lock:
                        job=service.accept(data['actor'],data['op'],data['data'],data['call_id'],data.get('ack_delivery'))
                        service.pump()
                    if not job['done'].wait(40):
                        result={'call_id':job['id'],'execution_status':'pending'}
                    else: result=job['result']
                    raw=json.dumps(result).encode(); self.send_response(200); self.end_headers()
                    try: self.wfile.write(raw)
                    except (BrokenPipeError,ConnectionResetError): pass
            world=http.server.ThreadingHTTPServer(('127.0.0.1',0),World)
            for server in (model,world): threading.Thread(target=server.serve_forever,daemon=True).start()
            def pump():
                while not done.wait(.01):
                    with service.lock: service.pump()
            pump_thread=threading.Thread(target=pump,daemon=True); pump_thread.start()
            for actor in ('Meta','Controller'):
                conn=run/'private/state/connections'/(actor+'.json'); data=json.loads(conn.read_text())
                data['url']=f'http://127.0.0.1:{world.server_port}'; conn.write_text(json.dumps(data))
            ledger=BudgetLedger.create(run/'private/state/budget.sqlite',2)
            env={'PATH':os.environ.get('PATH',''),'FAKE_KEY':'synthetic'}
            errors=[]
            def fork(*args,**kwargs):
                try: result=create_fork(*args,**kwargs)
                except Exception as error:
                    errors.append(str(error)); raise
                # Hold setup until the child has asked for its tool, so the gate is what stops it.
                StubModel.asked.wait(10); time.sleep(1)
                return result
            def setup(*args,**kwargs): return AdaptiveForkSetup(*args,fork_factory=fork,**kwargs)
            host=AdaptivePolicyHost(run,profile,env,ledger,turn_budget_usd=.5,setup_factory=setup)
            StubModel.requests.clear(); StubModel.asked.clear(); StubModel.asked_at=None
            try:
                host.bind_and_bootstrap()
                self.assertEqual(service.store.get('lifecycle'), 'running')
                deadline=time.monotonic()+12
                while time.monotonic()<deadline:
                    host.cycle()
                    batches=service.store.get('delegations',{})
                    if batches and next(iter(batches.values()))['status'] in ('finished','needs_review'): break
                    if service.store.get('dispatch_paused'): break
                    time.sleep(.05)
                batches=service.store.get('delegations',{})
                self.assertTrue(batches, {'parent':host.host.observe(),'last':host.host.last_result,
                    'requests':[(len(r.get('tools',[])), str(r.get('messages',[])[-1].get('content',''))[:500]) for r in StubModel.requests]})
                batch=next(iter(batches.values()))
                self.assertTrue(list((run/'private/state/claude-tool-bindings').glob('*.json')))
                claims=list((run/'private/claude-forks').glob('*.json')) if (run/'private/claude-forks').exists() else []
                self.assertEqual(batch['status'],'finished',{'batch':batch,'setup':host.dispatcher.setup_result,
                    'claims':[json.loads(p.read_text()) for p in claims], 'errors':errors,
                    'transcripts':[(p.name,[(r.get('type'),r.get('message',{}).get('content')) for r in map(json.loads,p.read_text().splitlines()) if r.get('type')=='assistant']) for p in (run/'private/claude-config/projects').glob('*/*.jsonl')]})
                self.assertEqual(service.store.get('robot_owners')['A'],'Controller')
                self.assertEqual(len(host.setup.hosts),1)
                # No tool-free setup turn: every model request offered the role's tools.
                self.assertTrue(all(req.get('tools') for req in StubModel.requests))
                child=batch['children'][0]['actor']
                # The child asked for return_task before activation; the gate held it until then.
                activated=next(e['created_at'] for e in service.store.events() if e['kind']=='DELEGATION_ACTIVATED')
                self.assertLess(StubModel.asked_at,activated)
                self.assertGreater(min(t for t,actor,_ in ops if actor==child),activated)
                # Its first input is the frozen delegate message, exactly as the Codex dispatcher fills it.
                codex=subprocess.run(['node','-e',CODEX_FIRST_MESSAGE,str(ROOT),str(run),json.dumps(batch['children'][0])],
                                     capture_output=True,text=True,timeout=30,check=True).stdout
                self.assertTrue(codex.startswith('Your current runtime role is '+child))
                self.assertEqual(child_prompt(child,batch['children'][0],run),codex)
                config_dir=history_directory(run); session=batch['children'][0]['thread_id']
                copy=history(transcript_rows(config_dir,session),session)
                self.assertEqual(first_input(copy[batch['source_provenance']['source_ordinal']:]),codex)
                # The model receives it after the parent's history, which ends at the delegate call.
                text=lambda c: c if isinstance(c,str) else ''.join(b.get('text','') for b in c if b.get('type')=='text')
                first=next(r for r in StubModel.requests if any(text(m['content'])==codex for m in r['messages']))
                conversation=[m for m in first['messages'] if m.get('role')!='system']
                self.assertEqual(text(conversation[-1]['content']),codex)
                self.assertIn('toolu_delegate',json.dumps(conversation[:-1]))
                bridge=RobotBridge(run,run/'private/state/connections/Controller.json')
                response=bridge.call({'op':'work','data':{'delegate_id':child}})
                report=json.loads(response['content'][0]['text'])['delegate_report']
                self.assertEqual(report['actor'],child)
                self.assertEqual(report['delegation_id'],batch['id'])
                self.assertEqual(report['result'],'synthetic evidence')
            finally:
                host.stop(); host.close(); done.set(); pump_thread.join(3)
                for server in (world,model): server.shutdown(); server.server_close()
                service.close(); ledger.close()


if __name__=='__main__': unittest.main()
