"""Use the same policy hosts and scheduler as Claude, with native Antigravity forks."""
import json
from pathlib import Path
import threading
import time

from robofrontier.engines.common.policy_host import CentralizedPolicyHost as SharedCentralized
from robofrontier.engines.common.adaptive_policy_host import AdaptivePolicyHost as SharedAdaptive
from robofrontier.engines.common.standing_team import StandingTeamPolicyHost as SharedStanding
from robofrontier.runtime.bootstrap import delegate_prompt
from robofrontier.runtime.cli import execute
from robofrontier.runtime.delegation import Delegations
from robofrontier.runtime.setup import write_json
from .session_host import AntigravitySessionHost
from .robot_mcp import binding_path
from .provenance import verify


class ForkSetup:
    def __init__(self, store, parent, ledger, owner, *, child_budget_usd=None):
        if store.get('config').get('engine') != 'antigravity' or parent.actor != 'Controller':
            raise ValueError('Expected an Antigravity Controller')
        if parent.budget_ledger is not ledger or child_budget_usd is not None:
            raise ValueError('Expected one shared unlimited accounting ledger')
        self.store, self.parent, self.ledger, self.owner = store, parent, ledger, owner
        self.hosts = {}
        self.cancel_event = threading.Event()
        self.launch_lock = threading.RLock()

    def admin(self, op, data):
        return execute(self.store, op, data, self.owner, time.time())

    def boundary(self, batch_id, actor):
        batch = Delegations(self.store).batch(batch_id)
        call = self.store.call(batch_id, 'Controller')
        child = next(c for c in batch['children'] if c['actor'] == actor)
        if (self.cancel_event.is_set() or self.store.get('lifecycle') != 'running'
                or self.store.get('dispatch_paused', False) or batch['status'] != 'creating'
                or batch['claimed_by'] != self.owner or time.time() >= batch['setup_deadline']
                or batch['source_thread_id'] != self.parent.session_id
                or self.parent.observe()['status'] != 'active' or call['op'] != 'delegate'
                or call['status'] != 'accepted' or child['status'] != 'creating'):
            raise ValueError('Delegation ownership, pending call or creation state changed')

    def establish(self, batch_id):
        delegates = Delegations(self.store)
        batch = self.admin('delegate-claim', {'id': batch_id})['delegation']
        try:
            binding = json.loads(binding_path(self.parent.run, batch_id).read_text())
            if binding['session_id'] != self.parent.session_id or binding['call_id'] != batch_id:
                raise ValueError('Pending call does not belong to this parent')
            for child in batch['children']:
                actor = child['actor']
                self.boundary(batch_id, actor)
                # A write-ahead intent bars automatic retry if the RPC outcome is lost.
                receipt = Path(self.parent.run)/'private/state/antigravity-forks'/(actor+'.json')
                if receipt.exists():
                    raise ValueError('Fork already attempted; never refork automatically')
                write_json(receipt, {'status': 'attempting', 'batch_id': batch_id, 'binding': binding})
                sid = self.parent.runner.fork(binding['step'])
                write_json(receipt, {'status': 'created', 'batch_id': batch_id, 'child_session': sid, 'binding': binding})
                # Identity is durable even if history verification fails.
                delegates.created(batch_id, actor, sid, self.owner)
                self.boundary(batch_id, actor)
                proof = verify(self.parent.runner.home, self.parent.session_id, sid, binding['step'],
                    snapshot=Path(self.parent.run)/'private/engine/fork-snapshots'/sid)
                delegates.bind(batch_id, actor, sid, proof, self.owner)
                write_json(receipt, {'status': 'verified', 'batch_id': batch_id, 'child_session': sid,
                                     'binding': binding, 'proof': proof})
                with self.launch_lock:
                    self.boundary(batch_id, actor)
                    host = AntigravitySessionHost(self.parent.run, actor, self.parent.profile, self.parent.base_env,
                        budget_ledger=self.ledger, _validated_delegate=True, native_session=sid)
                    self.hosts[actor] = host
            with self.launch_lock:
                if self.cancel_event.is_set():
                    raise ValueError('Fork setup stopped')
                self.admin('delegate-activate', {'id': batch_id})
                for child in batch['children']:
                    actor = child['actor']
                    # No child model turn is sent before the entire batch is active.
                    self.hosts[actor].send(delegate_prompt(self.parent.run, actor, child))
                    self.admin('delegate-started', {'id': batch_id, 'actor': actor, 'outcome': 'sent'})
            return {'status': 'active', 'actors': list(self.hosts)}
        except Exception as error:
            self.request_stop()
            try:
                delegates.uncertain(batch_id, 'Antigravity fork outcome requires review; never refork', self.owner)
            finally:
                self.store.put('dispatch_paused', True)
            return {'status': 'needs_review', 'error_type': type(error).__name__}

    def request_stop(self):
        self.cancel_event.set()
        with self.launch_lock:
            for host in self.hosts.values():
                host.stop()
                host.close_process()


class CentralizedPolicyHost(SharedCentralized):
    engine = 'antigravity'
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('host_factory', AntigravitySessionHost)
        super().__init__(*args, **kwargs)


class AdaptivePolicyHost(SharedAdaptive):
    engine = 'antigravity'
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('host_factory', AntigravitySessionHost)
        kwargs.setdefault('setup_factory', ForkSetup)
        super().__init__(*args, **kwargs)


class StandingTeamPolicyHost(SharedStanding):
    engine = 'antigravity'
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('host_factory', AntigravitySessionHost)
        super().__init__(*args, **kwargs)


def factories():
    return CentralizedPolicyHost, AdaptivePolicyHost, StandingTeamPolicyHost
