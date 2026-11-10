"""Experimental adaptive policy host for an already-owned physical world.

Not exposed as a benchmark launcher. The caller creates the world and a shared
budget ledger, explicitly starts supervision, and seals the world afterwards.
"""
import json
from pathlib import Path
import time
import uuid

from robofrontier.engines.claude.adaptive_dispatch import AdaptiveDispatcher
from robofrontier.engines.claude.adaptive_setup import AdaptiveForkSetup
from robofrontier.engines.claude.bootstrap import bootstrap_prompt
from robofrontier.engines.claude.session_host import ClaudeSessionHost
from robofrontier.runtime.pipeline_client import client_call
from robofrontier.runtime.setup import verify_inputs
from robofrontier.runtime.store import RuntimeStore


class AdaptivePolicyHost:
    def __init__(self, run_dir, profile, base_env, ledger, *, turn_budget_usd,
                 host_factory=ClaudeSessionHost, setup_factory=AdaptiveForkSetup,
                 client=client_call, verifier=verify_inputs, resume=False):
        self.run=Path(run_dir).resolve()
        if not Path(ledger.path).resolve().is_relative_to(self.run/'private'):
            raise ValueError('A run-local shared budget ledger is required')
        self.store=RuntimeStore(self.run/'private/state/runtime.sqlite')
        try:
            cfg=self.store.get('config')
            if not cfg or cfg.get('engine')!='claude' or cfg.get('topology')!='adaptive':
                raise ValueError('Expected adaptive Claude engineering run')
            launch=json.loads((self.run/'private/inputs/claude.json').read_text())
            if cfg.get('model')!=profile.get('model') or cfg.get('effort')!=profile.get('effort') or launch.get('profile')!=profile:
                raise ValueError('Profile differs from frozen run')
            # A run continued after an unexpected exit (docs/running/run-segments.md) keeps its sessions.
            self.resuming=resume; self.profile=profile; self.base_env=base_env; self.host_factory=host_factory
            if resume:
                if self.store.get('lifecycle')!='resuming' or not self.store.agent('Controller')['thread_id']:
                    raise ValueError('No prepared segment to resume')
            elif self.store.get('lifecycle')!='prepared' or self.store.agent('Controller')['thread_id']:
                raise ValueError('A previously bound or started world cannot be restarted')
            changed=verifier(self.run)
            if changed: raise ValueError('Frozen inputs changed: '+', '.join(changed))
            self.prompt=bootstrap_prompt(self.run,topology='adaptive',startup_protocol=cfg.get('startup_protocol','ready_barrier_v1'))
            self.host=host_factory(self.run,'Controller',profile,base_env,
                                   max_budget_usd=turn_budget_usd,budget_ledger=ledger)
            if resume: self.host.adopt(self.store.agent('Controller')['thread_id'])
            self.ledger=ledger; self.setup_factory=setup_factory; self.client=client
            self.turn_budget_usd=turn_budget_usd
            self.bound=False; self.bind_attempted=False; self.setup=None; self.dispatcher=None
        except Exception:
            self.store.close(); raise

    def bind_and_bootstrap(self):
        if self.bind_attempted or self.store.agent('Controller')['thread_id']:
            raise ValueError('Never repeat a role binding')
        self.bind_attempted=True
        conn=self.run/'private/state/connections/Meta.json'
        reply=self.client(conn,'bind',{'actor':'Controller','thread_id':self.host.session_id},
                          'bind-'+uuid.uuid4().hex,log_call_id=False)
        if not reply.get('bound') or self.store.agent('Controller')['thread_id']!=self.host.session_id:
            raise ValueError('Role binding outcome unknown; review instead of retrying')
        self.bound=True
        self.setup=self.setup_factory(self.store,self.host,self.ledger,'claude-meta-'+uuid.uuid4().hex,
                                      child_budget_usd=self.turn_budget_usd)
        self.dispatcher=AdaptiveDispatcher(self.store,self.setup)
        if self.store.get('config').get('startup_protocol') == 'direct_controller_v2':
            reply=self.dispatcher.admin('request-start')
            if not reply.get('started'): raise ValueError('Direct START was not confirmed')
        return self.host.send(self.prompt)

    def resume_segment(self):
        """Reopen the Controller and every active delegate, resume the world, and send each
        its frozen resume message. Delegates keep their own sessions; none is forked again."""
        if not self.resuming or self.dispatcher: raise ValueError('Not a prepared segment')
        self.bound=True
        self.setup=self.setup_factory(self.store,self.host,self.ledger,'claude-meta-'+uuid.uuid4().hex,
                                      child_budget_usd=self.turn_budget_usd)
        for actor,agent in self.store.agents().items():
            if agent['kind']=='delegate' and agent.get('delegation_state')=='active' and agent['thread_id']:
                self.setup.hosts[actor]=self.host_factory(self.run,actor,self.profile,self.base_env,
                                                          max_budget_usd=self.turn_budget_usd,budget_ledger=self.ledger,
                                                          _validated_delegate=True).adopt(agent['thread_id'])
        self.dispatcher=AdaptiveDispatcher(self.store,self.setup)
        reply=self.dispatcher.admin('request-resume')
        if not reply.get('resumed'): raise ValueError('World did not confirm the resumed segment')
        for actor,text in reply['messages'].items():
            host=self.dispatcher.host(actor)
            if host is not None: host.send(text)
        return reply

    def start_when_ready(self):
        if not self.bound or not self.dispatcher: raise ValueError('Controller has not been bound')
        if not self.dispatcher.observe('Controller') or self.host.observe()['status']!='idle' or not self.store.agent('Controller')['ready']:
            raise ValueError('Controller must be READY and its startup turn idle')
        reply=self.dispatcher.admin('request-start')
        if not reply.get('started'): raise ValueError('World did not confirm START')
        return reply

    def cycle(self):
        if not self.dispatcher: raise ValueError('Controller has not been bound')
        return self.dispatcher.cycle()

    def stop(self):
        """Request all role turns stop before the caller seals the world."""
        errors=[]
        if self.setup:
            try: self.setup.request_stop()
            except Exception as error: errors.append(type(error).__name__)
        hosts=[self.host]+list(self.setup.hosts.values() if self.setup else [])
        for host in hosts:
            try: host.stop()
            except Exception as error: errors.append(type(error).__name__)
        # One absolute deadline for every role: an interrupted persistent turn has
        # INTERRUPT_GRACE_S to end, then its process closes (runner.STOP_WAIT_S).
        from robofrontier.engines.claude.runner import STOP_WAIT_S
        deadline=time.monotonic()+STOP_WAIT_S
        if self.dispatcher and not self.dispatcher.wait_setup(timeout=max(0,deadline-time.monotonic())):
            errors.append('ForkSetupStillActive')
        for host in hosts:
            if hasattr(host,'wait'):
                try: host.wait(timeout=max(0,deadline-time.monotonic()))
                except Exception as error: errors.append(type(error).__name__)
        if errors or any(host.observe()['status']=='active' for host in hosts):
            raise RuntimeError('At least one role did not stop; review before closure')
        return {'stop_requested':True,'roles':len(hosts)}

    def close(self):
        if self.dispatcher and not self.dispatcher.wait_setup(timeout=0):
            raise ValueError('Wait for fork setup before closing')
        hosts=[self.host]+list(self.setup.hosts.values() if self.setup else [])
        if any(host.observe()['status']=='active' for host in hosts):
            raise ValueError('Stop and wait for every role before closing')
        for host in hosts:
            if hasattr(host,'close_process'): host.close_process()
        self.store.close()
