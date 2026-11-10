"""Host-recorded Claude delegate forks, taken at the parent's pending `delegate` call.

As on Codex, a child's history ends at the parent's delegate call and its first input
is the frozen delegate message. Claude Code creates a fork only by running its first
turn, so that turn is the fork: `--resume PARENT --fork-session` with the delegate
message as its prompt. Until the runtime activates the batch, a gate holds every tool
call of the child (see `runner.gate_settings`). Setup opens it only after the child's
copied history is verified; nothing here binds, activates or grants a robot.
"""
from robofrontier.engines.claude.native_home import history_directory
import hashlib
import json
import os
from pathlib import Path
import re
import time

from robofrontier.engines.claude.provenance import (ForkDiverged, copied_history_length, first_input, fork_provenance,
                                          history, transcript_rows)
from robofrontier.runtime.delegation import Delegations
from robofrontier.batch.metrics import host_event
from robofrontier.runtime.setup import write_json
from robofrontier.engines.claude.request_identity import matches_binding

ACTOR = re.compile(r'Delegate_[a-f0-9]{12}\Z')


def pending_history(store, parent, batch_id, actor, owner, cancel_event=None, timeout=10):
    """Return the parent's history once its native transcript holds the pending call.

    The runtime can accept the MCP call before Claude flushes its assistant
    message; a fork of the older prefix would not end at the delegate call.
    No model call has been launched while waiting here.
    """
    config = history_directory(Path(parent.run).resolve())
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cancel_event is not None and cancel_event.is_set():
            raise ValueError('Fork setup was cancelled')
        _boundary(store, parent, batch_id, actor, owner)
        try:
            source = history(transcript_rows(config, parent.session_id), parent.session_id)
        except ValueError:
            source = []  # File creation or a concurrent append may still be in progress.
        for row in reversed(source):
            msg = row.get('message') or {}
            content = msg.get('content') if isinstance(msg, dict) else None
            if not isinstance(content, list): continue
            for item in content:
                if not isinstance(item, dict) or item.get('type') != 'tool_use': continue
                data = item.get('input')
                if (isinstance(data, dict) and data.get('op') == 'delegate'
                        and item.get('name') == 'mcp__robot__robot'
                        and (data.get('call_id') == batch_id or matches_binding(
                            parent.run, batch_id, parent.session_id, row, item))):
                    return source
        time.sleep(.05)
    raise ValueError('Pending delegation was not recorded in the native transcript')


def _boundary(store, parent_host, batch_id, actor, owner):
    cfg = store.get('config')
    if cfg.get('engine') != 'claude' or cfg.get('topology') != 'adaptive':
        raise ValueError('Expected an adaptive Claude run')
    if store.get('lifecycle') != 'running' or store.get('dispatch_paused', False):
        raise ValueError('Run is not active')
    batch = Delegations(store).batch(batch_id)
    if batch['status'] != 'creating' or batch['claimed_by'] != owner or time.time() >= batch['setup_deadline']:
        raise ValueError('Delegation ownership or creation boundary changed')
    if batch['parent'] != 'Controller' or batch['source_thread_id'] != parent_host.session_id:
        raise ValueError('Parent session does not match delegation')
    if parent_host.observe()['status'] != 'active': raise ValueError('Parent is not at an active tool turn')
    call = store.call(batch_id, 'Controller')
    if call['op'] != 'delegate' or call['status'] != 'accepted':
        raise ValueError('Parent delegation tool call is not pending')
    child = next((c for c in batch['children'] if c['actor'] == actor), None)
    if child is None or child['thread_id'] is not None or child['status'] != 'creating':
        raise ValueError('Child is not an uncreated scope')
    return batch


def fork_gate(run, actor, deadline):
    """The gate of one delegate's first process: marker files and an epoch deadline."""
    folder = Path(run).resolve()/'private/claude-forks'
    return {'open': str(folder/(actor+'.gate-open')), 'closed': str(folder/(actor+'.gate-closed')),
            'deadline': deadline}


def open_gate(gate):
    Path(gate['open']).touch()


def close_gate(gate):
    Path(gate['closed']).touch()
    Path(gate['open']).unlink(missing_ok=True)


def _digest(rows):
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def create_fork(store, parent_host, batch_id, actor, owner, *, host, prompt, source,
                cancel_event=None, poll_s=.05):
    """Start one delegate forked at the pending call and verify its copied history.

    `host` is the child's unstarted host (`ClaudeSessionHost.fork_delegate`) and
    `source` the parent history at the pending call (`pending_history`). The child's
    ID is durable before its first, potentially paid, model call. On any failure the
    claim is left `uncertain`; a fork is never retried. The result grants nothing:
    the child's gate stays closed until setup opens it after activation.
    """
    if not isinstance(actor, str) or not ACTOR.fullmatch(actor): raise ValueError('Invalid delegate actor')
    if getattr(host, 'actor', None) != actor or getattr(host, 'fork_from', None) != parent_host.session_id:
        raise ValueError('Delegate host does not fork this parent')
    if not isinstance(prompt, str) or not prompt.strip(): raise ValueError('A delegate message is required')
    batch = _boundary(store, parent_host, batch_id, actor, owner)
    if not source: raise ValueError('Parent transcript has no messages')
    run = Path(parent_host.run).resolve()
    config = history_directory(run)
    digest = _digest(source)
    child = host.session_id
    claim = run/'private/claude-forks'/(actor+'.json')
    claim.parent.mkdir(parents=True, exist_ok=True)
    entry = {'status': 'claimed', 'batch_id': batch_id, 'actor': actor, 'owner': owner,
             'parent_session': parent_host.session_id, 'source_session': parent_host.session_id,
             'child_session': child, 'parent_history_sha256': digest,
             'first_input_sha256': hashlib.sha256(prompt.encode()).hexdigest(),
             'claimed_at': time.time(), 'tool_permissions': 'gated'}
    # Durable identity and intent precede the first potentially paid model call.
    with claim.open('x') as out:
        os.fchmod(out.fileno(), 0o600)
        json.dump(entry, out); out.flush(); os.fsync(out.fileno())
    try:
        _boundary(store, parent_host, batch_id, actor, owner)
        if cancel_event is not None and cancel_event.is_set():
            raise ValueError('Fork setup cancelled before launch')
        began = time.monotonic()
        if host.send(prompt).get('threadId') != child:
            raise ValueError('Delegate fork acknowledgement has wrong session')
        # The CLI writes the copied history as the turn starts. Until it is complete,
        # reads may see a missing file, a partial line or a shorter copy.
        while True:
            if cancel_event is not None and cancel_event.is_set():
                raise ValueError('Fork setup cancelled')
            if host.observe()['status'] not in ('active', 'idle'):
                raise ValueError('Delegate fork turn failed')
            try:
                proof = fork_provenance(parent_host.session_id, child, config, at=source)
                copy = history(transcript_rows(config, child), child)
            except ForkDiverged:
                raise
            except ValueError:
                proof = copy = None
            if proof is not None and first_input(copy[copied_history_length(source, copy):]) == prompt:
                break
            if time.time() >= batch['setup_deadline']:
                raise ValueError('Delegate fork history was not verified before the setup deadline')
            time.sleep(poll_s)
        _boundary(store, parent_host, batch_id, actor, owner)
        entry.update(status='history_verified_gated', verified_at=time.time(), proof=proof,
                     fork_seconds=time.monotonic()-began)
        write_json(claim, entry)
        host_event(run, 'fork_created', actor=actor, session_id=child, parent=parent_host.session_id,
                   duration_s=entry['fork_seconds'])
        return entry
    except Exception as error:
        entry.update(status='uncertain', error_type=type(error).__name__, completed_at=time.time())
        try: write_json(claim, entry)
        except OSError: pass
        raise
