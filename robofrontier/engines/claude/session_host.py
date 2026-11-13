"""Role-bound Claude session lifecycle. This is not a benchmark launcher.

The supervisor creates one host per role. Native turns are asynchronous so the
physical owner and deterministic scheduler can keep progressing. Unknown turn
outcomes are terminal for this host: never issue another turn automatically.
"""
import json
import math
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path
import re
import sys
import threading
import time
import uuid

from robofrontier.engines.claude.runner import PersistentSession, PreLaunchCancelled, policy_settings, run_turn
from robofrontier.runtime.setup import verify_inputs, write_json
from robofrontier.engines.claude.recovery import MAX_CAPACITY_RETRIES, recover, recover_model_loss, recover_network, recover_quota
from robofrontier.runtime import layout as run_layout

ACTOR_NAME = re.compile(r'[A-Za-z][A-Za-z0-9_-]{0,63}')


def role_mcp_config(run_dir, actor, python=sys.executable, *, _validated_delegate=False):
    """Write a host-owned connection bound to exactly one existing policy role."""
    run = Path(run_dir).resolve()
    if not isinstance(actor, str) or not ACTOR_NAME.fullmatch(actor) or actor == 'Meta':
        raise ValueError('Expected a policy role name')
    roles = json.loads((run / 'public/inputs/roles.json').read_text())['roles']
    if actor not in roles:
        if not _validated_delegate:
            raise ValueError('Role is not in the frozen policy team')
        from robofrontier.runtime.store import RuntimeStore
        path = run / 'private/state/runtime.sqlite'
        if not path.is_file(): raise ValueError('Runtime state missing')
        store = RuntimeStore(path)
        try:
            agent = store.agent(actor)
            # A delegate being created is held by its fork gate until activation.
            if agent['kind'] != 'delegate' or agent.get('delegation_state') not in ('creating', 'active'):
                raise ValueError('Delegate is not active')
        finally: store.close()
    elif roles[actor].get('kind') == 'manager':
        raise ValueError('Role is not in the frozen policy team')
    connection = run / 'private/state/connections' / (actor + '.json')
    info = json.loads(connection.read_text())
    if info.get('actor') != actor or info.get('run_id') != run.name or info.get('schema_version') != 3:
        raise ValueError('Role connection does not match this run')
    target = run_layout.path(run, 'engine_mcp', 'claude') / (actor + '.json')
    # A model never chooses the actor or a connection path. The server binds it.
    project = Path(__file__).resolve().parents[3]
    write_json(target, {'mcpServers': {'robot': {
        # Absolute but not resolved: a virtual environment's python is a link to the base
        # interpreter, and following it loses the environment that installs this project.
        # Claude Code does not pass the PYTHONPATH below to the server on every host.
        'command': os.path.abspath(python),
        'args': ['-m', 'robofrontier.engines.claude.robot_mcp', '--run-dir', str(run), '--connection', str(connection)],
        'env': {'PYTHONPATH': str(project)},
    }}})
    return target


from robofrontier.engines.common.session_host import SessionHost


class ClaudeSessionHost(SessionHost):
    """Claude setup around the shared role lifecycle."""
    def __init__(self, run_dir, actor, profile, base_env, *, python=sys.executable, runner=None, **options):
        runner = runner or (PersistentSession() if policy_settings(Path(run_dir)) is not None else run_turn)
        mcp = role_mcp_config(run_dir, actor, python,
                              _validated_delegate=options.get('_validated_delegate', False))
        super().__init__(run_dir, actor, profile, base_env, python=python, runner=runner,
                         engine='claude', mcp=mcp, session_id=str(uuid.uuid4()), **options)

    def recover_capacity(self, store, now=None):
        return (recover(self, store, now) or recover_model_loss(self, store) or recover_quota(self, store)
                or recover_network(self, store))

    def history_available(self):
        from .native_home import history_directory
        from .provenance import history, transcript_rows
        return bool(history(transcript_rows(history_directory(self.run), self.session_id), self.session_id))

    def write_summary(self, path, value):
        write_json(path, value)

    @classmethod
    def fork_delegate(cls, run_dir, actor, profile, base_env, *, budget_ledger, max_budget_usd, fork_from, gate,
                      _verifier=verify_inputs, **kwargs):
        """A host whose first turn forks `fork_from` into this delegate's new session.

        The parent is blocked at its pending `delegate` call, so the child's history
        ends there and its first input is the prompt given to `send`. `gate` (see
        `runner.gate_settings`) holds every tool call of that first process until the
        runtime activates the delegate. This is an engineering primitive, not an
        adaptive admission switch; its local evidence assumes the host and runtime are
        trusted by the OS user.
        """
        from robofrontier.engines.claude.fork_setup import ACTOR
        from robofrontier.runtime.store import RuntimeStore
        run = Path(run_dir).resolve()
        if not isinstance(actor, str) or not ACTOR.fullmatch(actor): raise ValueError('Invalid delegate actor')
        if budget_ledger is None or not Path(budget_ledger.path).resolve().is_relative_to(run/'private'):
            raise ValueError('A run-local shared budget ledger is required')
        if _verifier(run): raise ValueError('Frozen inputs changed')
        launch = json.loads((run/'private/inputs/claude.json').read_text())
        if launch.get('profile') != profile:
            raise ValueError('Delegate profile differs from frozen launch profile')
        store_path = run/'private/state/runtime.sqlite'
        if not store_path.is_file(): raise ValueError('Runtime state missing')
        store = RuntimeStore(store_path)
        try:
            config = store.get('config')
            if (config.get('engine') != 'claude' or config.get('topology') != 'adaptive'
                    or config.get('model') != profile.get('model') or config.get('effort') != profile.get('effort')
                    or store.get('lifecycle') != 'running' or store.get('dispatch_paused', False)):
                raise ValueError('Run or profile cannot fork a delegate')
            agent = store.agent(actor)
            if (agent.get('kind') != 'delegate' or agent.get('delegation_state') != 'creating' or agent['thread_id']
                    or store.agent('Controller')['thread_id'] != fork_from):
                raise ValueError('Delegate is not an uncreated scope of this parent')
        finally: store.close()
        host = cls(run, actor, profile, base_env, budget_ledger=budget_ledger,
                   max_budget_usd=max_budget_usd, _validated_delegate=True, **kwargs)
        host.fork_from, host.gate = fork_from, gate
        return host
