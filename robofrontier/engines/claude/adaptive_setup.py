"""Experimental host-controlled adaptive fork setup; not an admission endpoint.

The caller is the trusted process which owns the active parent and shared budget.
This module does not start a world, schedule subsequent wakes, or qualify a batch.
"""
from robofrontier.engines.claude.native_home import history_directory
import json
import math
from pathlib import Path
import threading
import time

from robofrontier.engines.claude.fork_setup import _boundary, close_gate, create_fork, fork_gate, open_gate, pending_history
from robofrontier.engines.claude.provenance import fork_provenance
from robofrontier.engines.claude.session_host import ClaudeSessionHost
from robofrontier.runtime.delegation import Delegations
from robofrontier.runtime.cli import execute
from robofrontier.runtime.bootstrap import delegate_prompt


def child_prompt(actor, child, run=None):
    # Runs prepared with robofrontier/runtime/bootstrap.py send the frozen delegate message.
    frozen = delegate_prompt(run, actor, child) if run is not None else None
    if frozen is not None:
        return frozen
    scope = {key: child[key] for key in ('robots', 'goal', 'done_when', 'constraints') if key in child}
    return ('Your current runtime role is ' + actor + '. This assignment replaces the inherited parent role, '
            'connection and finish authority. The parent task evidence restrictions remain in force. '
            'Use only your bound robot MCP tool and assigned robots; inherited pending calls are history, '
            'not work to replay. You cannot create delegates or finish the team run. '
            'Carry out the bounded scope, communicate through the role protocol, and call return_task '
            'with outcome and evidence when handing back. Save a waiting state if you must pause. '
            'The assigned scope is: ' + json.dumps(scope, ensure_ascii=False))


class AdaptiveForkSetup:
    def __init__(self, store, parent, ledger, owner, *, child_budget_usd,
                 fork_factory=create_fork, child_factory=ClaudeSessionHost.fork_delegate):
        cfg = store.get('config')
        if cfg.get('engine') != 'claude' or cfg.get('topology') != 'adaptive':
            raise ValueError('Expected adaptive Claude runtime')
        if parent.actor != 'Controller' or store.agent('Controller')['thread_id'] != parent.session_id:
            raise ValueError('Parent host does not match runtime')
        if parent.budget_ledger is not ledger:
            raise ValueError('Parent and children must share the exact task budget ledger')
        if not Path(ledger.path).resolve().is_relative_to(Path(parent.run).resolve()/'private'):
            raise ValueError('Task budget ledger must belong to the run')
        if child_budget_usd is not None and (isinstance(child_budget_usd,bool) or not isinstance(child_budget_usd,(int,float))
                                             or not math.isfinite(child_budget_usd) or child_budget_usd <= 0):
            raise ValueError('Child budget must be a positive finite number or None')
        self.store=store; self.parent=parent; self.ledger=ledger; self.owner=owner
        self.child_budget_usd=child_budget_usd
        self.fork_factory=fork_factory; self.child_factory=child_factory
        self.hosts={}
        self.cancel_event=threading.Event()
        self.launch_lock=threading.RLock()

    def request_stop(self):
        """Prevent new child turns and stop every child, including one still being forked."""
        self.cancel_event.set()
        with self.launch_lock:
            for host in list(self.hosts.values()): host.stop()

    def admin(self, op, data):
        return execute(self.store, op, data, self.owner, time.time())

    def establish(self, batch_id):
        """Claim, fork every child at the pending call, verify, activate, then open the gates.

        Errors preserve reservations and pause the run; a child whose gate is still
        closed is stopped and never runs a tool.
        """
        delegates=Delegations(self.store)
        batch=self.admin('delegate-claim', {'id':batch_id})['delegation']
        gates={}; opened=set()
        try:
            # Every child copies the parent's history as it is at the pending call.
            source=pending_history(self.store,self.parent,batch_id,batch['children'][0]['actor'],self.owner,
                                   self.cancel_event)
            for child in batch['children']:
                actor=child['actor']
                gates[actor]=fork_gate(self.parent.run,actor,batch['setup_deadline'])
                with self.launch_lock:
                    if self.cancel_event.is_set(): raise ValueError('Fork setup cancelled')
                    host=self.child_factory(self.parent.run,actor,self.parent.profile,self.parent.base_env,
                                            budget_ledger=self.ledger,max_budget_usd=self.child_budget_usd,
                                            fork_from=self.parent.session_id,gate=gates[actor])
                    self.hosts[actor]=host
                result=self.fork_factory(self.store,self.parent,batch_id,actor,self.owner,host=host,
                                         prompt=child_prompt(actor,child,host.run),source=source,
                                         cancel_event=self.cancel_event)
                if self.cancel_event.is_set(): raise ValueError('Fork setup cancelled')
                _boundary(self.store,self.parent,batch_id,actor,self.owner)
                # The known ID is committed before any further fallible checks.
                with self.store.transaction():
                    self.store.lease(self.owner,time.time(),self.store.get('config')['manager_lease_s'])
                    delegates.created(batch_id,actor,result['child_session'],self.owner)
                claim_path=Path(self.parent.run)/'private/claude-forks'/(actor+'.json')
                claim=json.loads(claim_path.read_text())
                if claim != result or result.get('status') != 'history_verified_gated':
                    raise ValueError('Trusted fork record is incomplete or changed')
                if (result['actor'] != actor or result['batch_id'] != batch_id or result['owner'] != self.owner
                        or result['parent_session'] != self.parent.session_id
                        or result['source_session'] != self.parent.session_id
                        or result['child_session'] != host.session_id
                        or result['proof']['source_sha256'] != result['parent_history_sha256']
                        or fork_provenance(result['source_session'],result['child_session'],
                                           history_directory(self.parent.run),at=source) != result['proof']):
                    raise ValueError('Trusted fork record does not match requested scope')
                with self.store.transaction():
                    self.store.lease(self.owner,time.time(),self.store.get('config')['manager_lease_s'])
                    delegates.bind(batch_id,actor,result['child_session'],result['proof'],self.owner)
            with self.launch_lock:
                if self.cancel_event.is_set(): raise ValueError('Fork setup cancelled')
                self.admin('delegate-activate', {'id':batch_id})
            for child in delegates.batch(batch_id)['children']:
                actor=child['actor']
                with self.launch_lock:
                    if self.cancel_event.is_set(): raise ValueError('Fork setup cancelled')
                    open_gate(gates[actor]); opened.add(actor)
                # The delegate message was its first input; from here it may act on it.
                self.admin('delegate-started', {'id':batch_id,'actor':actor,'outcome':'sent'})
            return {'status':'active','actors':list(self.hosts)}
        except Exception as error:
            # A child not yet released must never run a tool.
            for actor,gate in gates.items():
                if actor in opened: continue
                try: close_gate(gate)
                except OSError: pass
                host=self.hosts.get(actor)
                if host is not None:
                    try: host.stop()
                    except Exception: pass
            # Even a failed fork may have created its explicitly allocated ID.
            for child in delegates.batch(batch_id)['children']:
                path=Path(self.parent.run)/'private/claude-forks'/(child['actor']+'.json')
                if not path.is_file(): continue
                try:
                    saved=json.loads(path.read_text()); ident=saved.get('child_session')
                    if ident and saved.get('batch_id')==batch_id and saved.get('actor')==child['actor']:
                        delegates.created(batch_id,child['actor'],ident,self.owner)
                except Exception: pass
            try:
                delegates.uncertain(batch_id,'Claude fork setup or child start requires engineering review',self.owner)
            finally:
                # Preserve paused state even if writing the delegation outcome fails.
                self.store.put('dispatch_paused',True)
            return {'status':'needs_review','error_type':type(error).__name__,'actors':list(self.hosts)}
