import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

from roboteam.harness.claude.systems.adaptive import AdaptivePolicyHost
from roboteam.harness.claude.session.budget import BudgetLedger
from roboteam.runtime.world.store import RuntimeStore


class FakeHost:
    def __init__(self,run,actor,model_entry,env,*,max_budget_usd,budget_ledger):
        self.actor=actor; self.run=run; self.model_entry=model_entry; self.base_env=env; self.budget_ledger=budget_ledger
        self.session_id='parent-id'; self.state='new'; self.turn=None; self.prompts=[]
    def send(self,prompt): self.prompts.append(prompt); self.state='active'; self.turn='turn'; return {'threadId':self.session_id}
    def observe(self): return {'actor':self.actor,'thread_id':self.session_id,'status':self.state,'turn_id':self.turn}
    def stop(self): self.state='unknown'
    def wait(self,timeout=None): return self.observe()


class AdaptiveHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.run=Path(self.tmp.name)/'run'; public=self.run/'public/inputs'
        public.mkdir(parents=True)
        (public/'task.json').write_text(json.dumps({'family_materials':[]}))
        (public/'roles.json').write_text(json.dumps({'system':'adaptive','roles':{'Controller':{'kind':'controller'}}}))
        self.model_entry={'model':'fake','effort':'high','env_key':'FAKE'}
        launch=self.run/'private/inputs/claude.json'; launch.parent.mkdir(parents=True)
        launch.write_text(json.dumps({'model_entry':self.model_entry}))
        frozen=self.run/'private/inputs/bootstrap/Controller.md'; frozen.parent.mkdir()
        frozen.write_text('frozen adaptive start')
        cfg=json.loads((Path(__file__).resolve().parents[3]/'roboteam/runtime/run/defaults.json').read_text())
        cfg.update(startup_protocol='direct_controller', harness='claude',system='adaptive',model='fake',effort='high')
        store=RuntimeStore(self.run/'private/state/runtime.sqlite'); store.initialize('run',cfg,['A']); store.close()
        self.ledger=BudgetLedger.create(self.run/'private/state/budget.sqlite',1); self.calls=[]
        def client(conn,op,data,call_id,**kwargs):
            self.calls.append(op); store=RuntimeStore(self.run/'private/state/runtime.sqlite')
            store.update_agent(data['actor'],thread_id=data['thread_id']); store.close(); return {'bound':True}
        self.client=client
    def tearDown(self): self.ledger.close(); self.tmp.cleanup()
    def make(self):
        return AdaptivePolicyHost(self.run,self.model_entry,{},self.ledger,turn_budget_usd=.2,
                                  host_factory=FakeHost,client=self.client,verifier=lambda _:[])
    def test_direct_start_binding_and_multi_role_stop(self):
        host=self.make()
        def start(dispatcher,op,data=None):
            self.assertEqual((op,host.host.prompts),('request-start',[]))
            host.store.start(); return {'started':True}
        try:
            with mock.patch('roboteam.harness.claude.systems.adaptive.AdaptiveDispatcher.admin',start):
                host.bind_and_bootstrap()
            self.assertEqual(host.host.prompts,['frozen adaptive start'])
            self.assertEqual(host.store.get('lifecycle'),'running')
            with self.assertRaisesRegex(ValueError,'Never repeat'): host.bind_and_bootstrap()
            child=FakeHost(self.run,'Delegate_test',self.model_entry,{},max_budget_usd=.2,budget_ledger=self.ledger)
            child.state='active'; host.setup.hosts['Delegate_test']=child
            self.assertEqual(host.stop()['roles'],2)
            self.assertEqual(child.state,'unknown'); self.assertEqual(host.host.state,'unknown')
        finally: host.close()
    def test_model_entry_and_input_mismatch_rejected(self):
        with self.assertRaisesRegex(ValueError,'Model entry differs'):
            AdaptivePolicyHost(self.run,{**self.model_entry,'model':'other'},{},self.ledger,turn_budget_usd=.2,
                               host_factory=FakeHost,verifier=lambda _:[])
        with self.assertRaisesRegex(ValueError,'Frozen inputs changed'):
            AdaptivePolicyHost(self.run,self.model_entry,{},self.ledger,turn_budget_usd=.2,
                               host_factory=FakeHost,verifier=lambda _:['changed'])


if __name__=='__main__': unittest.main()
