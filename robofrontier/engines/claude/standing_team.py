"""Native Claude standing teams over the shared runtime mailbox and scheduler.

Every initial role owns an independent native session. Bind the complete team,
START once, and only then send task prompts. This engineering host never forks a
role, assigns a robot strategy, replays an uncertain turn or certifies a score.
"""
from pathlib import Path
import time
import uuid

from .bootstrap import bootstrap_prompt
from .budget import BudgetExhausted
from .session_host import ClaudeSessionHost
from ...runtime.pipeline_client import client_call
from ...runtime.setup import verify_inputs
from ...runtime.cli import execute
from ...runtime.store import RuntimeStore


class _TeamStatus:
    """Let the existing supervisor inspect/stop a whole fixed team as one owner."""
    def __init__(self, hosts):
        self.hosts = hosts

    def observe(self):
        observations = {actor: host.observe() for actor, host in self.hosts.items()}
        states = {value['status'] for value in observations.values()}
        state = ('unknown' if states - {'idle', 'active', 'error'} else
                 'error' if 'error' in states else 'active' if 'active' in states else 'idle')
        return {'status': state, 'roles': observations}

    def recover_capacity(self, store):
        if any(h.observe()['status'] not in ('idle', 'active', 'error') for h in self.hosts.values()):
            return False
        recovering = set()
        for actor, host in self.hosts.items():
            if hasattr(host, 'recover_capacity') and host.recover_capacity(store):
                recovering.add(actor)
        errors = {actor for actor, host in self.hosts.items() if host.observe()['status'] == 'error'}
        # Recovery in one role must not hide an unrelated failed role.
        return (bool(errors) and errors <= recovering and
                all(h.observe()['status'] in ('idle', 'active', 'error') for h in self.hosts.values()))

    def wait(self, timeout=5):
        deadline = time.monotonic() + timeout
        for host in self.hosts.values():
            if hasattr(host, 'wait'):
                host.wait(timeout=max(0, deadline-time.monotonic()))


class StandingTeamPolicyHost:
    def __init__(self, run_dir, profile, base_env, ledger, *, turn_budget_usd=None,
                 host_factory=ClaudeSessionHost, client=client_call, verifier=verify_inputs, resume=False):
        self.run = Path(run_dir).resolve()
        if not Path(ledger.path).resolve().is_relative_to(self.run/'private'):
            raise ValueError('A run-local shared budget ledger is required')
        self.store = RuntimeStore(self.run/'private/state/runtime.sqlite')
        self.hosts = {}
        try:
            cfg = self.store.get('config')
            if (cfg.get('engine') != 'claude' or cfg.get('topology') not in ('hierarchical', 'peer')
                    or cfg.get('startup_protocol') != 'direct_team_v3'):
                raise ValueError('Expected a direct-team Claude standing-team engineering run')
            if cfg.get('model') != profile.get('model') or cfg.get('effort') != profile.get('effort'):
                raise ValueError('Profile differs from frozen runtime configuration')
            agents = {a: v for a, v in self.store.agents().items() if v['kind'] != 'manager'}
            # A run continued after an unexpected exit (docs/running/continuation.md) keeps every
            # role's session; any other bound or started world is never restarted.
            self.resuming = resume
            if resume:
                if self.store.get('lifecycle') != 'resuming' or not agents or not all(a['thread_id'] for a in agents.values()):
                    raise ValueError('No prepared segment to resume')
            elif self.store.get('lifecycle') != 'prepared' or not agents or any(a['thread_id'] for a in agents.values()):
                raise ValueError('A previously bound or started world cannot be restarted')
            changed = verifier(self.run)
            if changed:
                raise ValueError('Frozen inputs changed: ' + ', '.join(changed))
            self.prompts = {a: bootstrap_prompt(self.run, topology=cfg['topology'], actor=a,
                                               startup_protocol='direct_team_v3') for a in agents}
            self.hosts = {a: host_factory(self.run, a, profile, base_env,
                                          max_budget_usd=turn_budget_usd, budget_ledger=ledger) for a in agents}
            if any(h.actor != a for a, h in self.hosts.items()):
                raise ValueError('Native host identity differs from its standing role')
            if resume:
                for actor, host in self.hosts.items(): host.adopt(agents[actor]['thread_id'])
            ids = [h.session_id for h in self.hosts.values()]
            if len(set(ids)) != len(ids):
                raise ValueError('Every initial role needs a distinct native session')
            self.host = _TeamStatus(self.hosts)
            self.client = client
            self.owner = 'claude-team-' + uuid.uuid4().hex
            self.bind_attempted = False
            self.bound = False
            self.dispatcher = self  # Existing supervisor's admin/seal interface.
        except BaseException:
            self.store.close()
            raise

    def admin(self, op, data=None):
        return execute(self.store, op, data or {}, self.owner, time.time())

    def bind_and_bootstrap(self):
        if self.bind_attempted:
            raise ValueError('Never repeat standing-team role binding or bootstrap')
        self.bind_attempted = True
        connection = self.run/'private/state/connections/Meta.json'
        for actor, host in self.hosts.items():
            if self.store.agent(actor)['thread_id']:
                raise ValueError('Role was already bound; review instead of rebinding')
            result = self.client(connection, 'bind', {'actor': actor, 'thread_id': host.session_id},
                                 'bind-'+uuid.uuid4().hex, log_call_id=False)
            if not result.get('bound') or self.store.agent(actor)['thread_id'] != host.session_id:
                raise ValueError('Role binding outcome unknown; review instead of retrying')
        result = self.admin('request-start')
        if not result.get('started') or self.store.get('lifecycle') != 'running':
            raise ValueError('Direct team START was not confirmed')
        self.bound = True
        acknowledgements = {}
        for actor, host in self.hosts.items():
            ack = host.send(self.prompts[actor])
            if ack.get('threadId') != host.session_id:
                raise ValueError('Initial role acknowledgement mismatch; review instead of retrying')
            acknowledgements[actor] = ack
        return acknowledgements

    def resume_segment(self):
        """Resume the prepared segment and send each working role its frozen resume message."""
        if not self.resuming or self.bind_attempted:
            raise ValueError('Not a prepared segment')
        self.bind_attempted = True
        reply = self.admin('request-resume')
        if not reply.get('resumed') or self.store.get('lifecycle') != 'running':
            raise ValueError('World did not confirm the resumed segment')
        self.bound = True
        for actor, text in reply['messages'].items():
            if actor in self.hosts: self.hosts[actor].send(text)
        return reply

    def _valid_observation(self, actor, value):
        return (isinstance(value, dict) and
                value.get('thread_id') == self.store.agent(actor)['thread_id'] and
                value.get('status') in ('active', 'idle', 'error') and
                isinstance(value.get('turn_id'), str) and bool(value['turn_id']))

    def _pause_role(self, actor):
        self.admin('session-unavailable', {'actor': actor, 'thread_id': self.hosts[actor].session_id,
                                           'reason': 'Claude standing role state requires review'})
        self.admin('pause', {'reason': 'Claude standing role state unavailable or failed'})
        return False

    def _observe(self, actor):
        host = self.hosts[actor]
        if not self._valid_observation(actor, host.observe()):
            return self._pause_role(actor)
        recovering = hasattr(host, 'recover_capacity') and host.recover_capacity(self.store)
        value = host.observe()
        if not self._valid_observation(actor, value) or value['status'] == 'error' and not recovering:
            return self._pause_role(actor)
        self.admin('observe-sessions', {'observations': [{
            'actor': actor, 'thread_id': value['thread_id'], 'status': value['status'],
            'turn_id': value['turn_id'], 'observed_at': time.time(), 'source': 'claude.host',
            'turn_status': 'failed' if value['status'] == 'error' else None}]})
        return value['status'] != 'error'

    def cycle(self):
        if not self.bound:
            raise ValueError('Standing team has not been bound')
        snapshot = self.admin('snapshot')
        if snapshot['paused'] or snapshot['lifecycle'] != 'running':
            return {'dispatched': [], 'paused': snapshot['paused'], 'lifecycle': snapshot['lifecycle']}
        # Inspect the complete team before any recovery can launch a model turn.
        for actor, host in self.hosts.items():
            if not self._valid_observation(actor, host.observe()):
                self._pause_role(actor)
                return {'dispatched': [], 'paused': True}
        available = {a: self._observe(a) for a in self.hosts}
        if self.store.get('dispatch_paused', False):
            return {'dispatched': [], 'paused': True}
        sent = []
        for command in self.admin('plan')['commands']:
            actor = command['actor']
            if actor not in self.hosts:
                raise ValueError('Scheduler selected a role outside the frozen team')
            if not available[actor] or not self._observe(actor):
                if self.store.get('dispatch_paused', False):
                    return {'dispatched': sent, 'paused': True}
                continue
            claimed = self.admin('claim', {'wake_id': command['wake_id']})['command']
            if not claimed:
                continue
            try:
                host = self.hosts[actor]
                if claimed['thread_id'] != host.session_id:
                    raise ValueError('Wake session differs from bound standing role')
                ack = host.send(claimed['prompt'])
                if ack.get('threadId') != claimed['thread_id']:
                    raise ValueError('Standing role acknowledgement mismatch')
            except BudgetExhausted:
                # Refused before any launch: the wake was not sent, and the task cap is spent.
                self.admin('dispatch-result', {'wake_id': claimed['wake_id'], 'outcome': 'cancelled',
                                               'result': {'error': 'budget_exhausted'}})
                self.admin('pause', {'reason': 'Claude task budget exhausted'})
                return {'dispatched': sent, 'paused': True}
            except Exception:
                self.admin('dispatch-result', {'wake_id': claimed['wake_id'], 'outcome': 'uncertain',
                                               'result': {'error': 'Claude role dispatch requires review'}})
                self.admin('pause', {'reason': 'Claude role dispatch outcome uncertain'})
                return {'dispatched': sent, 'paused': True}
            self.admin('dispatch-result', {'wake_id': claimed['wake_id'], 'outcome': 'sent',
                                           'result': {'accepted': True}})
            sent.append(claimed['wake_id'])
        return {'dispatched': sent, 'paused': self.store.get('dispatch_paused', False)}

    def stop(self):
        errors = []
        for host in self.hosts.values():
            try:
                host.stop()
            except Exception as error:
                errors.append(type(error).__name__)
        # One absolute deadline for every standing role (runner.STOP_WAIT_S).
        from robofrontier.engines.claude.runner import STOP_WAIT_S
        deadline = time.monotonic() + STOP_WAIT_S
        for host in self.hosts.values():
            try:
                host.wait(timeout=max(0, deadline - time.monotonic()))
            except Exception as error:
                errors.append(type(error).__name__)
        if errors or any(h.observe()['status'] == 'active' for h in self.hosts.values()):
            raise RuntimeError('At least one standing role did not stop; review before closure')
        return {'stop_requested': True, 'roles': len(self.hosts)}

    def close(self):
        if any(h.observe()['status'] == 'active' for h in self.hosts.values()):
            raise ValueError('Stop and wait for every standing role before closing')
        for host in self.hosts.values():
            if hasattr(host, 'close_process'): host.close_process()
        self.store.close()
