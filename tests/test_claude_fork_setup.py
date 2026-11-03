import json
from pathlib import Path
import tempfile
import threading
import time
import unittest

from robofrontier import run_layout
from robofrontier.claude.budget import BudgetLedger
from robofrontier.claude.fork_setup import close_gate, create_fork, fork_gate, open_gate, pending_history
from robofrontier.claude.session_host import ClaudeSessionHost
from robofrontier.delegation import Delegations
from robofrontier.runtime_store import RuntimeStore

PARENT='11111111-1111-4111-8111-111111111111'
PROMPT='Your current runtime role is the delegate.\n'
PROFILE={'model':'fake','effort':'high','env_key':'FAKE'}


class Parent:
    session_id=PARENT; binary='claude'; profile=PROFILE; base_env={}
    def __init__(self,run): self.run=run; self.state='active'
    def observe(self): return {'status':self.state}


class ForkSetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.run=Path(self.tmp.name)/'run'
        self.run.mkdir(); self.store=RuntimeStore(self.run/'private/state/runtime.sqlite')
        cfg=json.loads((Path(__file__).resolve().parents[1]/'configs/harnesses/policy.json').read_text())
        cfg.update(engine='claude',topology='adaptive',model='fake',effort='high')
        self.store.initialize('run',cfg,['A','B']); self.store.update_agent('Controller',thread_id=PARENT,ready=True)
        self.store.start(); self.store.begin_call('batch','Controller','delegate',{'scopes':[]})
        self.d=Delegations(self.store)
        batch=self.d.create('Controller','batch',getattr(self,'test_scopes',[{'robots':['A'],'goal':'g','done_when':'d'}]))
        self.actor=batch['children'][0]['actor']; self.d.claim('batch','owner')
        self.parent=Parent(self.run); self.folder=self.run/'private/claude-config/projects/-run'
        self.folder.mkdir(parents=True)
        self.row={'type':'assistant','uuid':'m1','sessionId':PARENT,'message':{'role':'assistant','content':[
            {'type':'tool_use','id':'toolu_delegate','name':'mcp__robot__robot','input':{'op':'delegate','call_id':'batch'}}]}}
        (self.folder/(PARENT+'.jsonl')).write_text(json.dumps(self.row)+'\n')
        roles=self.run/'public/inputs/roles.json'; roles.parent.mkdir(parents=True)
        roles.write_text(json.dumps({'roles':{'Controller':{'kind':'controller'}}}))
        for child in batch['children']:
            conn=self.run/'private/state/connections'/(child['actor']+'.json'); conn.parent.mkdir(parents=True,exist_ok=True)
            conn.write_text(json.dumps({'schema_version':3,'run_id':'run','actor':child['actor'],'token':'fake'}))
        launch=self.run/'private/inputs/claude.json'; launch.parent.mkdir(parents=True)
        launch.write_text(json.dumps({'profile':PROFILE}))
        self.ledger=BudgetLedger.create(self.run/'private/state/budget.sqlite',1)
        self.calls=[]; self.hosts=[]
    def tearDown(self):
        for host in self.hosts: host.wait(3)
        self.ledger.close(); self.store.close(); self.tmp.cleanup()
    def runner(self,*args,**kw):
        """A fork as the CLI writes it: the parent's rows, the CLI's own rows for the
        unanswered call, then the first input. A resumed turn only reports."""
        self.calls.append(kw)
        child=kw.get('session_id') or kw['resume']
        if kw.get('fork_from'):
            source=(self.folder/(kw['fork_from']+'.jsonl')).read_text().splitlines()
            rows=[{**json.loads(row),'sessionId':child} for row in source]
            rows+=[{'type':'user','uuid':'c1','sessionId':child,'message':{'role':'user','content':[
                       {'type':'tool_result','tool_use_id':'toolu_delegate','is_error':True,'content':'interrupted'}]}},
                   {'type':'assistant','uuid':'c2','sessionId':child,'message':{'role':'assistant','content':[
                       {'type':'text','text':'No response requested.'}]}},
                   {'type':'user','uuid':'c3','sessionId':child,'message':{'role':'user','content':args[4]}}]
            (self.folder/(child+'.jsonl')).write_text(''.join(json.dumps(row)+'\n' for row in rows))
        return {'process':'exited','exit_code':0,'summary':{'session_id':child,'turn_status':'ended',
                'malformed_lines':0,'total_cost_usd':.01}}
    def gate(self, actor=None):
        return fork_gate(self.run,actor or self.actor,self.d.batch('batch')['setup_deadline'])
    def host(self, runner=None, actor=None, **kwargs):
        actor=actor or self.actor
        kwargs={'budget_ledger':self.ledger,'max_budget_usd':.1,'fork_from':PARENT,'gate':self.gate(actor),
                'runner':runner or self.runner,'_verifier':lambda _: [],**kwargs}
        host=ClaudeSessionHost.fork_delegate(self.run,actor,PROFILE,{},**kwargs)
        self.hosts.append(host)
        return host
    def source(self):
        return pending_history(self.store,self.parent,'batch',self.actor,'owner',timeout=0.5)
    def create(self, runner=None, prompt=PROMPT, **kwargs):
        return create_fork(self.store,self.parent,'batch',self.actor,'owner',host=self.host(runner),
                           prompt=prompt,source=self.source(),**kwargs)

    def test_records_identity_before_the_fork_turn_and_grants_nothing(self):
        def checked(*args,**kwargs):
            claim=json.loads((self.run/'private/claude-forks'/(self.actor+'.json')).read_text())
            self.assertEqual(claim['status'],'claimed'); self.assertEqual(claim['child_session'],kwargs['session_id'])
            self.assertEqual(kwargs['fork_from'],PARENT); self.assertEqual(kwargs['gate'],self.gate())
            self.assertEqual(args[4],PROMPT)  # The fork's first input is the delegate message.
            return self.runner(*args,**kwargs)
        output=self.create(checked)
        self.assertEqual(output['status'],'history_verified_gated')
        self.assertEqual(output['proof']['source_thread_id'],PARENT)
        self.assertEqual(output['proof']['source_last_uuid'],'m1')
        self.assertEqual(output['proof']['source_ordinal'],1)
        self.assertEqual(self.d.batch('batch')['children'][0]['thread_id'],None)
        self.assertEqual(self.store.agent(self.actor)['delegation_state'],'creating')
        self.assertFalse(Path(self.gate()['open']).exists())
        with self.assertRaises(FileExistsError): self.create()
        self.assertEqual(len(self.calls),1)
        events=[json.loads(line) for line in run_layout.path(self.run,'host_log','claude').read_text().splitlines()]
        created=[e for e in events if e['event']=='fork_created']
        self.assertEqual(created[0]['session_id'],output['child_session'])

    def test_compacted_history_verifies_delegate_input_at_child_boundary(self):
        from tests.test_claude_compacted_fork import child_copy, compacted_source
        source = compacted_source()
        source[-1]['message'] = self.row['message']  # The saved boundary is a pending delegate call.
        source = [{**item, 'sessionId': PARENT} for item in source]
        transcript = self.folder/(PARENT+'.jsonl')
        transcript.write_text(''.join(json.dumps(item)+'\n' for item in source))
        def compacted_runner(*args, **kwargs):
            child = kwargs['session_id']
            inherited = child_copy(source)
            inherited = [{**item, 'sessionId': child} for item in inherited]
            inherited.append({'type':'user', 'uuid':'child-prompt', 'sessionId':child,
                              'message':{'role':'user', 'content':args[4]}})
            (self.folder/(child+'.jsonl')).write_text(''.join(json.dumps(item)+'\n' for item in inherited))
            return {'process':'exited','exit_code':0,'summary':{'session_id':child,'turn_status':'ended',
                    'malformed_lines':0,'total_cost_usd':.01}}
        output = self.create(compacted_runner)
        self.assertEqual(output['status'], 'history_verified_gated')
        self.assertEqual(output['proof']['source_ordinal'], len(source))
        self.assertFalse(Path(self.gate()['open']).exists())

    def test_generated_delegate_id_is_bound_to_native_tool_use(self):
        from robofrontier.claude.request_identity import bind_delegate
        item = self.row['message']['content'][0]
        item['id'] = 'native-delegate'
        item['input'].pop('call_id')
        (self.folder/(PARENT+'.jsonl')).write_text(json.dumps(self.row)+'\n')
        bind_delegate(self.run, 'Controller', item['input'], 'batch', timeout=0)
        self.assertEqual(self.create()['status'], 'history_verified_gated')

    def test_ambiguous_native_delegation_is_rejected_before_submission(self):
        from robofrontier.claude.request_identity import bind_delegate
        item = self.row['message']['content'][0]
        item['id'] = 'native-1'; item['input'].pop('call_id')
        self.row['message']['content'].append({**item, 'id': 'native-2'})
        (self.folder/(PARENT+'.jsonl')).write_text(json.dumps(self.row)+'\n')
        with self.assertRaisesRegex(ValueError, 'Ambiguous'):
            bind_delegate(self.run, 'Controller', item['input'], 'batch', timeout=0)
        self.assertEqual(self.calls, [])

    def test_failed_fork_turn_is_saved_and_never_repeated(self):
        def lost(*args,**kwargs): raise OSError('lost acknowledgement')
        with self.assertRaisesRegex(ValueError,'fork turn failed'): self.create(lost)
        claim=json.loads((self.run/'private/claude-forks'/(self.actor+'.json')).read_text())
        self.assertEqual(claim['status'],'uncertain'); self.assertEqual(claim['error_type'],'ValueError')
        with self.assertRaises(FileExistsError): self.create()
        self.assertEqual(self.calls,[])

    def test_parent_changed_before_the_fork_fails_closed(self):
        source=self.source()
        with (self.folder/(PARENT+'.jsonl')).open('a') as f:
            f.write(json.dumps({**self.row,'uuid':'m2'})+'\n')
        with self.assertRaisesRegex(ValueError,'beyond the fork point'):
            create_fork(self.store,self.parent,'batch',self.actor,'owner',host=self.host(),prompt=PROMPT,source=source)
        self.assertEqual(json.loads((self.run/'private/claude-forks'/(self.actor+'.json')).read_text())['status'],'uncertain')

    def test_a_different_first_input_is_never_verified(self):
        def other(*args,**kwargs): return self.runner(*args[:4],'Something else',*args[5:],**kwargs)
        batch=self.d.batch('batch'); batch['setup_deadline']=time.time()+.5; self.d.save(batch)
        with self.assertRaisesRegex(ValueError,'not verified|boundary changed'): self.create(other)
        self.assertEqual(json.loads((self.run/'private/claude-forks'/(self.actor+'.json')).read_text())['status'],'uncertain')

    def test_requires_pending_parent_delegation(self):
        source=self.source(); self.parent.state='idle'
        with self.assertRaisesRegex(ValueError,'active tool turn'):
            create_fork(self.store,self.parent,'batch',self.actor,'owner',host=self.host(),prompt=PROMPT,source=source)
        self.assertFalse((self.run/'private/claude-forks'/(self.actor+'.json')).exists())

    def test_waits_for_pending_tool_call_to_be_flushed_before_fork(self):
        transcript=self.folder/(PARENT+'.jsonl')
        transcript.write_text('')
        def flush():
            time.sleep(.1)
            transcript.write_text(json.dumps(self.row)+'\n')
        worker=threading.Thread(target=flush); worker.start()
        try: self.assertEqual(self.create()['status'],'history_verified_gated')
        finally: worker.join()
        self.assertEqual(len(self.calls),1)

    def test_fork_turn_is_a_child_turn_on_the_shared_ledger(self):
        self.ledger.reserve('parent-turn','Controller',.95)
        self.assertEqual(self.create()['status'],'history_verified_gated')
        self.assertEqual(self.calls[0]['max_budget_usd'],.05)
        self.hosts[-1].wait(3)
        self.assertEqual(self.ledger.snapshot()['reported_spend_usd'],'0.01')
        self.assertEqual(self.ledger.snapshot()['reserved_usd'],'0.95')

    def test_cancelled_before_launch_starts_no_turn(self):
        cancel=threading.Event(); cancel.set()
        with self.assertRaisesRegex(ValueError,'cancelled'): self.create(cancel_event=cancel)
        self.assertEqual(self.calls,[])
        self.assertEqual(self.ledger.snapshot()['reservations'],[])
        claim=json.loads((self.run/'private/claude-forks'/(self.actor+'.json')).read_text())
        self.assertEqual(claim['status'],'uncertain')

    def test_delegate_host_forks_only_an_uncreated_scope_of_its_parent(self):
        with self.assertRaises(ValueError):
            ClaudeSessionHost(self.run,self.actor,PROFILE,{})
        with self.assertRaisesRegex(ValueError,'uncreated scope'): self.host(fork_from='other')
        with self.assertRaisesRegex(ValueError,'profile'):
            ClaudeSessionHost.fork_delegate(self.run,self.actor,{**PROFILE,'model':'other'},{},budget_ledger=self.ledger,
                                            max_budget_usd=.1,fork_from=PARENT,gate=self.gate(),_verifier=lambda _: [])
        host=self.host(); host.fork_from=None
        with self.assertRaisesRegex(ValueError,'host does not fork'):
            create_fork(self.store,self.parent,'batch',self.actor,'owner',host=host,prompt=PROMPT,source=self.source())
        # Its MCP configuration is bound to the delegate's own connection.
        args=json.loads(host.mcp.read_text())['mcpServers']['robot']['args']
        self.assertEqual(args[args.index('--connection')+1],
                         str((self.run/'private/state/connections'/(self.actor+'.json')).resolve()))

    def test_later_turns_resume_the_child_without_fork_or_gate(self):
        result=self.create(); host=self.hosts[-1]
        self.assertEqual(host.wait(3)['status'],'idle')
        host.send('Next wake'); self.assertEqual(host.wait(3)['status'],'idle')
        self.assertEqual(self.calls[1]['resume'],result['child_session'])
        self.assertNotIn('fork_from',self.calls[1]); self.assertNotIn('gate',self.calls[1])

    def test_gate_markers(self):
        gate=self.gate(); Path(gate['open']).parent.mkdir(parents=True,exist_ok=True)
        open_gate(gate); self.assertTrue(Path(gate['open']).exists())
        close_gate(gate)
        self.assertFalse(Path(gate['open']).exists()); self.assertTrue(Path(gate['closed']).exists())


if __name__=='__main__': unittest.main()
