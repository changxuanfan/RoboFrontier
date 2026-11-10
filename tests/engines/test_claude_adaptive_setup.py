"""Trusted setup integration against the real delegation store, no provider calls."""
import json
from pathlib import Path
import threading
import unittest

from engines import test_claude_fork_setup as fixtures
from robofrontier.engines.claude.adaptive_setup import AdaptiveForkSetup, child_prompt
from robofrontier.engines.claude.budget import BudgetLedger
from robofrontier.engines.claude.session_host import ClaudeSessionHost


class AdaptiveSetupTests(unittest.TestCase):
    runner = fixtures.ForkSetupTests.runner
    gate = fixtures.ForkSetupTests.gate
    def setUp(self):
        fixtures.ForkSetupTests.setUp(self)
        # The fixture claims ownership itself; restore to the state before the host claims.
        batch=self.d.batch('batch'); batch['claimed_by']=None; self.d.save(batch)
        self.parent.actor='Controller'
        self.parent.budget_ledger=self.ledger
    def tearDown(self):
        for host in self.hosts:
            host.wait(3)
            self.assertFalse(host.worker and host.worker.is_alive(), 'Child turn did not finish before cleanup')
        fixtures.ForkSetupTests.tearDown(self)
    def child(self,*args,**kwargs):
        host=ClaudeSessionHost.fork_delegate(*args,runner=self.runner,_verifier=lambda _:[],**kwargs)
        self.hosts.append(host)
        return host
    def coordinator(self, child_budget_usd=.2, **kwargs):
        return AdaptiveForkSetup(self.store,self.parent,self.ledger,'owner',child_budget_usd=child_budget_usd,
                                 child_factory=self.child,**kwargs)

    def test_fork_at_pending_call_then_bind_activate_and_open_the_gate(self):
        original=self.runner
        def forked(*args,**kwargs):
            # The child already has its delegate message, but no authority and a closed gate.
            self.assertEqual(self.store.agent(self.actor)['delegation_state'],'creating')
            self.assertFalse(Path(kwargs['gate']['open']).exists())
            return original(*args,**kwargs)
        self.runner=forked
        host=self.coordinator(); result=host.establish('batch')
        self.assertEqual(result['status'],'active')
        self.assertEqual(result['actors'],[self.actor])
        child=self.d.batch('batch')['children'][0]
        self.assertTrue(child['verified']); self.assertEqual(child['start_status'],'sent')
        self.assertEqual(self.d.batch('batch')['source_provenance']['source_thread_id'],fixtures.PARENT)
        self.assertIsNone(self.d.batch('batch').get('snapshot_thread_id'))
        self.assertEqual(self.store.agent(self.actor)['delegation_state'],'active')
        self.assertEqual(self.store.action_robot(self.actor,'A'),'A')
        with self.assertRaises(ValueError): self.store.action_robot('Controller','A')
        self.assertTrue(Path(self.gate()['open']).exists())
        self.assertEqual(host.hosts[self.actor].wait(3)['status'],'idle')
        # One model turn per child: the fork itself, whose first input is the delegate message.
        self.assertEqual(len(self.calls),1)
        self.assertEqual(self.calls[0]['fork_from'],fixtures.PARENT)
        self.assertEqual(self.calls[0]['session_id'],child['thread_id'])
        self.assertEqual(self.calls[0]['max_budget_usd'],.2)
        self.assertEqual(self.ledger.snapshot()['reported_spend_usd'],'0.01')
        with self.assertRaises(ValueError): host.establish('batch')

    def test_frozen_delegate_message_is_the_first_input(self):
        frozen=self.run/'private/inputs/bootstrap/delegate.md'; frozen.parent.mkdir(parents=True)
        frozen.write_text('Role {{ACTOR}} with scope {{SCOPE}}\n')
        self.assertEqual(self.coordinator().establish('batch')['status'],'active')
        child=self.d.batch('batch')['children'][0]
        self.assertEqual(json.loads((self.folder/(child['thread_id']+'.jsonl')).read_text().splitlines()[-1])
                         ['message']['content'], child_prompt(self.actor,child,self.run))
        self.assertTrue(child_prompt(self.actor,child,self.run).startswith('Role '+self.actor+' with scope {"robots":["A"]'))

    def test_uncapped_fork_and_child_continue_without_cost_reports(self):
        self.ledger.close()
        self.ledger = BudgetLedger.create(self.run/'private/state/uncapped-budget.sqlite')
        self.parent.budget_ledger = self.ledger
        original = self.runner
        def no_cost(*args, **kwargs):
            record = original(*args, **kwargs)
            record['summary']['total_cost_usd'] = None
            return record
        self.runner = no_cost
        host = self.coordinator(child_budget_usd=None)
        self.assertEqual(host.establish('batch')['status'], 'active')
        self.assertEqual(host.hosts[self.actor].wait(3)['status'], 'idle')
        self.assertIsNone(self.calls[0]['max_budget_usd'])
        self.assertIsNone(self.calls[0]['timeout'])
        state = self.ledger.snapshot()
        self.assertEqual(state['status'], 'tracking')
        self.assertEqual(state['unreported_cost_count'], 1)
        self.assertIsNone(state['limit_usd'])

    def test_failed_fork_keeps_reserved_robot_known_child_id_and_a_closed_gate(self):
        def lost(*args,**kwargs): raise OSError('lost acknowledgement')
        self.runner=lost
        result=self.coordinator().establish('batch')
        self.assertEqual(result['status'],'needs_review')
        self.assertTrue(self.store.get('dispatch_paused'))
        batch=self.d.batch('batch')
        self.assertEqual(batch['status'],'needs_review')
        self.assertEqual(batch['children'][0]['thread_id'],self.hosts[0].session_id)
        self.assertFalse(batch['children'][0]['verified'])
        self.assertEqual(self.d.owners()['A'],self.actor)
        with self.assertRaises(ValueError): self.store.action_robot('Controller','A')
        with self.assertRaises(ValueError): self.store.action_robot(self.actor,'A')
        self.assertTrue(Path(self.gate()['closed']).exists())
        self.assertEqual(self.ledger.snapshot()['status'],'uncertain')

    def test_stop_interrupts_a_fork_turn_and_never_opens_its_gate(self):
        entered=threading.Event(); results=[]
        def waiting(*args,**kwargs):
            entered.set(); self.assertTrue(kwargs['cancel_event'].wait(3))
            return {'process':'cancelled','exit_code':-9,'summary':{'turn_status':'unknown'}}
        self.runner=waiting
        setup=self.coordinator()
        worker=threading.Thread(target=lambda:results.append(setup.establish('batch')))
        worker.start(); self.assertTrue(entered.wait(3)); setup.request_stop(); worker.join(3)
        self.assertFalse(worker.is_alive()); self.assertEqual(results[0]['status'],'needs_review')
        self.assertTrue(self.store.get('dispatch_paused'))
        self.assertFalse(Path(self.gate()['open']).exists()); self.assertTrue(Path(self.gate()['closed']).exists())
        self.assertEqual(self.ledger.snapshot()['status'],'uncertain')


class AdaptiveBatchTests(unittest.TestCase):
    runner = fixtures.ForkSetupTests.runner
    gate = fixtures.ForkSetupTests.gate
    child = AdaptiveSetupTests.child
    coordinator = AdaptiveSetupTests.coordinator
    tearDown = AdaptiveSetupTests.tearDown
    def setUp(self):
        self.test_scopes=[{'robots':['A'],'goal':'first','done_when':'done'},
                          {'robots':['B'],'goal':'second','done_when':'done'}]
        AdaptiveSetupTests.setUp(self)

    def test_every_child_forks_from_the_parent_at_the_same_call(self):
        self.assertEqual(self.coordinator().establish('batch')['status'],'active')
        batch=self.d.batch('batch')
        self.assertTrue(all(child['verified'] for child in batch['children']))
        self.assertEqual({c['fork_from'] for c in self.calls},{fixtures.PARENT})
        self.assertEqual(batch['source_provenance']['source_last_uuid'],'m1')
        for host in self.hosts: self.assertEqual(host.wait(3)['status'],'idle')
        self.assertEqual(self.ledger.snapshot()['reported_spend_usd'],'0.02')

    def test_parent_append_between_children_fails_closed(self):
        original=self.runner
        def mutate(*args,**kwargs):
            result=original(*args,**kwargs)
            if len(self.calls)==1:
                with (self.folder/(fixtures.PARENT+'.jsonl')).open('a') as out:
                    out.write(json.dumps({**self.row,'uuid':'later'})+'\n')
            return result
        self.runner=mutate
        result=self.coordinator().establish('batch')
        self.assertEqual(result['status'],'needs_review')
        self.assertTrue(self.store.get('dispatch_paused'))
        for child in self.d.batch('batch')['children']:
            self.assertTrue(Path(self.gate(child['actor'])['closed']).exists())
            self.assertFalse(Path(self.gate(child['actor'])['open']).exists())


if __name__=='__main__': unittest.main()
