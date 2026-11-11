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
from .driver import ForkUnacknowledged
from .provenance import pending, verify
from robofrontier.batch.metrics import host_event

# How long a delegate's first input may take to appear in its native history.
INPUT_ACK_S = 30


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
        run, parent = Path(self.parent.run), self.parent
        try:
            binding = json.loads(binding_path(run, batch_id).read_text())
            if binding['session_id'] != parent.session_id or binding['call_id'] != batch_id:
                raise ValueError('Pending call does not belong to this parent')
            for child in batch['children']:
                actor = child['actor']
                self.boundary(batch_id, actor)
                # The row forked from is the delegate call bound when it arrived.
                pending(parent.runner.home, parent.session_id, binding)
                # A write-ahead intent bars automatic retry if the RPC outcome is lost.
                receipt = run/'private/state/antigravity-forks'/(actor+'.json')
                if receipt.exists():
                    raise ValueError('Fork already attempted; never refork automatically')
                write_json(receipt, {'status': 'attempting', 'batch_id': batch_id, 'binding': binding})
                began = time.monotonic()
                try:
                    sid = parent.runner.fork(binding['step'])
                except ForkUnacknowledged as error:
                    # The child exists: keep its ID for review before failing the batch.
                    write_json(receipt, {'status': 'unacknowledged', 'batch_id': batch_id,
                                         'child_session': error.child, 'binding': binding})
                    delegates.created(batch_id, actor, error.child, self.owner)
                    raise
                write_json(receipt, {'status': 'created', 'batch_id': batch_id, 'child_session': sid, 'binding': binding})
                # Identity is durable even if history verification fails.
                delegates.created(batch_id, actor, sid, self.owner)
                self.boundary(batch_id, actor)
                proof = verify(parent.runner.home, parent.session_id, sid, binding['step'], binding=binding,
                    snapshot=run/'private/engine/fork-snapshots'/sid)
                delegates.bind(batch_id, actor, sid, proof, self.owner)
                seconds = time.monotonic() - began
                write_json(receipt, {'status': 'verified', 'batch_id': batch_id, 'child_session': sid,
                                     'binding': binding, 'proof': proof, 'fork_seconds': seconds})
                host_event(run, 'fork_created', actor=actor, session_id=sid, parent=parent.session_id,
                           duration_s=seconds)
                with self.launch_lock:
                    self.boundary(batch_id, actor)
                    host = AntigravitySessionHost(run, actor, parent.profile, parent.base_env,
                        budget_ledger=self.ledger, _validated_delegate=True, native_session=sid)
                    self.hosts[actor] = host
            with self.launch_lock:
                if self.cancel_event.is_set():
                    raise ValueError('Fork setup stopped')
                # The runtime refuses this once the setup deadline has passed or the run
                # is paused or ending (Delegations.activate), whatever was true above.
                self.admin('delegate-activate', {'id': batch_id})
            for child in batch['children']:
                actor = child['actor']
                with self.launch_lock:
                    if self.cancel_event.is_set():
                        raise ValueError('Fork setup stopped')
                    # No child model turn is sent before the entire batch is active.
                    host = self.hosts[actor]
                    turn = host.send(delegate_prompt(run, actor, child))
                # "sent" means the child's own history holds the input, as Codex waits for
                # its send acknowledgement and Claude reads the forked transcript.
                left = Delegations(self.store).batch(batch_id)['setup_deadline'] - time.time()
                delivered = host.runner.input_delivered(f"{actor}-{turn['turnId']}.jsonl",
                    max(0, min(INPUT_ACK_S, left)), alive=lambda host=host: host.observe()['status'] == 'active')
                recorded = self.admin('delegate-started', {'id': batch_id, 'actor': actor,
                                                           'outcome': 'sent' if delivered else 'uncertain'})
                if recorded['status'] == 'needs_review':
                    raise ValueError('Initial delegate input delivery uncertain')
            return {'status': 'active', 'actors': list(self.hosts)}
        except Exception as error:
            self.request_stop()
            try:
                delegates.uncertain(batch_id, 'Antigravity fork outcome requires review; never refork', self.owner)
            finally:
                self.store.put('dispatch_paused', True)
            return {'status': 'needs_review', 'error_type': type(error).__name__}

    def request_stop(self):
        """Stop every child; one child's failure never leaves the others running."""
        self.cancel_event.set()
        with self.launch_lock:
            for actor, host in self.hosts.items():
                for step in (host.stop, host.close_process):
                    try:
                        step()
                    except Exception as error:
                        try:
                            host_event(Path(self.parent.run), 'delegate_cleanup_failed', actor=actor,
                                       step=step.__name__, error_type=type(error).__name__)
                        except Exception:
                            pass


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
