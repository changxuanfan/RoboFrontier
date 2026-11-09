"""Experimental single-run launcher; never admits a scored benchmark batch.

Starting this module may call a paid model. It is deliberately not wired into
benchmark run commands. An engineering draft can be consumed once, never replayed.
"""
import fcntl
from functools import partial
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.parse import urlsplit

from robofrontier.claude.policy_host import CentralizedPolicyHost
from robofrontier.claude.adaptive_policy_host import AdaptivePolicyHost
from robofrontier.claude.budget import BudgetLedger
from robofrontier import run_layout
from robofrontier.claude.session_host import ClaudeSessionHost
from robofrontier.claude.runner import build_env
from robofrontier.claude.native_home import config_directory
from robofrontier.claude.supervisor import CentralizedSupervisor
from robofrontier.claude.standing_team import StandingTeamPolicyHost
from robofrontier.run_seal import seal_run
from robofrontier.run_setup import verify_inputs, write_json
from robofrontier.task_config import ROOT


def _ledger(run, total_budget_usd, resuming):
    """The run's shared cost ledger: reopened, never replaced, when the run continues.

    Turns cut off by the unexpected exit have ended with an unknown cost; without a task
    cap they are settled as unreported, under a cap they become uncertain and block."""
    path = run_layout.path(run, 'budget_ledger', 'claude')
    if resuming and path.exists():
        ledger = BudgetLedger(path); ledger.settle_interrupted()
        return ledger
    return BudgetLedger.create(path, total_budget_usd)


# Supervisor results where the host itself ended the policy's last turn.
HOST_STOPS = ('wall_limit', 'stop_requested', 'world_ended')


def _positive(value, name, limit):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 < value <= limit:
        raise ValueError('Invalid ' + name)


def _concurrent_roles(run, topology):
    """The most roles that can hold a budget reservation at once."""
    roles = json.loads((run/'public/inputs/roles.json').read_text())['roles']
    if topology == 'adaptive':
        # The Controller's turn stays reserved while it waits for its delegates, at most one
        # per arm (delegate scopes hold disjoint robots).
        return 1 + len(roles['Controller']['robots'])
    return sum(1 for info in roles.values() if info['kind'] != 'manager')


def _check_shared_budget(run, topology, turn_budget_usd, total_budget_usd):
    """Refuse, before any claim, a task cap that concurrent roles could exhaust by reserving.

    A turn without its own allowance reserves the whole remainder, so one role would deny
    every other; with an allowance, the roles' reservations together must fit the cap."""
    if total_budget_usd is None or topology == 'centralized':
        return
    if turn_budget_usd is None:
        raise ValueError('A task budget for a multi-role run needs a per-turn budget')
    roles = _concurrent_roles(run, topology)
    if roles * turn_budget_usd > total_budget_usd:
        raise ValueError('Task budget %.4g is below %d concurrent roles x per-turn budget %.4g'
                         % (total_budget_usd, roles, turn_budget_usd))


def _evaluation_present(run):
    """A finished world requires a readable evaluator result, not task success."""
    try:
        evaluation=json.loads((run/'private/outputs/evaluation.json').read_text())
        return isinstance(evaluation, dict) and isinstance(evaluation.get('task_success'), bool)
    except (OSError, ValueError, TypeError):
        return False


def run_engineering(run_dir, base_env, *, turn_budget_usd=None, total_budget_usd=None, wall_limit_s=86400, startup_timeout_s=120,
                    poll_s=0.5, owner_factory=subprocess.Popen, policy_factory=CentralizedPolicyHost,
                    adaptive_policy_factory=AdaptivePolicyHost, standing_policy_factory=StandingTeamPolicyHost,
                    clock=time.monotonic, sleep=time.sleep):
    """Run one explicit engineering draft and conservatively retain uncertain state.

    Optional budgets are best-effort limits based on CLI-reported cost, not billing.
    The caller must authorize model calls before invoking this function.
    """
    for val, name in ((turn_budget_usd, 'per-turn budget'), (total_budget_usd, 'task budget')):
        if val is not None: _positive(val, name, 1000)
    for val, name, limit in ((wall_limit_s, 'wall limit', 86400),
                             (startup_timeout_s, 'startup timeout', 86400),
                             (poll_s, 'poll interval', 60)):
        _positive(val, name, limit)
    run = Path(run_dir).resolve()
    launch = json.loads((run / 'private/inputs/claude.json').read_text())
    manifest = json.loads((run / 'private/inputs/manifest.json').read_text())
    if launch.get('schema') != 'robofrontier.claude-launch-draft.v1' or launch.get('qualified') is not False or launch.get('execution_available') is not False:
        raise ValueError('Only unqualified engineering drafts are accepted')
    if manifest.get('status') != 'engineering draft; not qualified or runnable' or manifest.get('engine') != 'claude':
        raise ValueError('Expected a frozen Claude engineering draft')
    changed = verify_inputs(run)
    if changed: raise ValueError('Frozen inputs changed: ' + ', '.join(changed))
    profile = launch['profile']
    config = json.loads((run / 'private/inputs/harness.json').read_text())
    topology = config.get('topology')
    if topology not in ('centralized', 'adaptive', 'hierarchical', 'peer') or config.get('engine') != 'claude':
        raise ValueError('Expected a supported Claude engineering draft')
    if profile.get('auth_mode') != 'native_login' and not base_env.get(profile['env_key']):
        raise ValueError('Missing credential variable: ' + profile['env_key'])
    if profile.get('auth_mode') == 'native_login':
        build_env(profile, base_env, config_directory(run, profile))
    if run_layout.path(run, 'stop', 'claude').exists(): raise ValueError('Run was stopped before launch')
    _check_shared_budget(run, topology, turn_budget_usd, total_budget_usd)
    # A run continued after an unexpected exit (docs/running/run-segments.md) starts again only
    # from a prepared segment; its claim stays and its sessions are resumed.
    from robofrontier.runtime_store import RuntimeStore
    state_store = RuntimeStore(run / 'private/state/runtime.sqlite')
    try: resuming = state_store.get('lifecycle') == 'resuming'
    finally: state_store.close()
    host_factory = partial(ClaudeSessionHost, max_budget_usd=turn_budget_usd, total_budget_usd=total_budget_usd)
    policy = None
    ledger = None
    policy_closed = False
    owner = None
    result = None
    claimed = False
    claim = run_layout.path(run, 'engineering_claim', 'claude')
    status = run_layout.path(run, 'engineering_status', 'claude')
    lock_path = run_layout.path(run, 'engineering_lock', 'claude')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = lock_path.open('a+')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        # Recheck under the lock; a claim survives crashes and bars all retries.
        if claim.exists() and not resuming: raise ValueError('Run already claimed; never restart the world')
        if run_layout.path(run, 'stop', 'claude').exists(): raise ValueError('Run was stopped before launch')
        if verify_inputs(run): raise ValueError('Frozen inputs changed before launch')
        if topology == 'centralized':
            # The run's persistent ledger, as for every topology, so a model restart or a
            # continued segment keeps the costs already spent.
            ledger = _ledger(run, total_budget_usd, resuming)
            host_factory = partial(ClaudeSessionHost, max_budget_usd=turn_budget_usd, budget_ledger=ledger)
            policy = policy_factory(run, profile, base_env, host_factory=host_factory,
                                    **({'resume': True} if resuming else {}))
        if not resuming:
            with claim.open('x') as out:
                os.fchmod(out.fileno(), 0o600)
                json.dump({'claimed_at': time.time(), 'pid': os.getpid(), 'mode': 'engineering'}, out)
                out.flush(); os.fsync(out.fileno())
        claimed = True
        if topology == 'adaptive':
            ledger = _ledger(run, total_budget_usd, resuming)
            policy = adaptive_policy_factory(run, profile, base_env, ledger,
                                             turn_budget_usd=turn_budget_usd,
                                             **({'resume': True} if resuming else {}))
        elif topology in ('hierarchical', 'peer'):
            ledger = _ledger(run, total_budget_usd, resuming)
            policy = standing_policy_factory(run, profile, base_env, ledger,
                                              turn_budget_usd=turn_budget_usd,
                                              **({'resume': True} if resuming else {}))
        write_json(status, {'status': 'starting', 'claimed_at': time.time(), 'scored': False,
                            'turn_budget_usd': turn_budget_usd, 'task_budget_usd': total_budget_usd,
                            'wall_limit_s': wall_limit_s, 'startup_timeout_s': startup_timeout_s})
        # Do not pass model credentials to the physical owner.
        owner_env = {k: v for k, v in base_env.items() if k in (
            'PATH', 'HOME', 'LANG', 'LC_ALL', 'TMPDIR', 'DISPLAY', 'MUJOCO_GL',
            'PYOPENGL_PLATFORM', 'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER',
            'CUDA_VISIBLE_DEVICES', 'MUJOCO_EGL_DEVICE_ID',
            'PYTHONPATH', 'DYLD_LIBRARY_PATH', 'LD_LIBRARY_PATH')}
        owner_log = run_layout.path(run, 'owner_log', 'claude')
        owner_log.parent.mkdir(parents=True, exist_ok=True)
        with owner_log.open('a') as log:
            owner = owner_factory([sys.executable, '-m', 'robofrontier.pipeline', '--run-dir', str(run), '--hidden'],
                                  cwd=ROOT, env=owner_env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                                  start_new_session=True)
        write_json(status, {'status': 'waiting_for_owner', 'owner_pid': owner.pid, 'scored': False})
        deadline = clock() + startup_timeout_s
        connection = run / 'private/state/connections/Meta.json'
        while True:
            if owner.poll() is not None: raise RuntimeError('Physical owner exited before publishing its connection')
            if run_layout.path(run, 'stop', 'claude').exists(): raise RuntimeError('Stop requested during owner startup')
            if clock() >= deadline: raise TimeoutError('Physical owner startup timed out')
            info = json.loads(connection.read_text())
            if info.get('url') and policy.store.get('execution_owner_attached'):
                url = urlsplit(info['url'])
                if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.path or url.query or url.fragment:
                    raise ValueError('Expected the owner local loopback endpoint')
                break
            sleep(poll_s)
        write_json(status, {'status': 'running', 'owner_pid': owner.pid, 'scored': False})
        supervisor = CentralizedSupervisor(policy, lambda: owner.poll() is None,
                                            stop_requested=lambda: run_layout.path(run, 'stop', 'claude').exists(),
                                            startup_timeout_s=startup_timeout_s, wall_limit_s=wall_limit_s,
                                            poll_s=poll_s, clock=clock, sleep=sleep)
        result = supervisor.run()
    except Exception as error:
        if not claimed:
            raise
        result = {'reason': 'launch_error', 'error_type': type(error).__name__, 'sealed': False}
        if owner is not None and policy is not None and policy.store.get('execution_owner_attached'):
            try: result['seal'] = seal_run(policy.store, 30)
            except Exception as seal_error: result['seal_error_type'] = type(seal_error).__name__
        # A still-live owner is not force-killed: its state must be reviewed.
    finally:
        budget_status = None
        budget_review_required = False
        try:
            if policy is not None: policy.close()
            policy_closed = True
        except Exception:
            if result is not None: result['policy_close_error'] = True
        if ledger is not None:
            try:
                # A turn the host cut off itself (wall limit, stop, ended world) has ended; without
                # a task cap its unknown cost is recorded as unreported, not a reason for review.
                if result is not None and result.get('reason') in HOST_STOPS: ledger.settle_interrupted()
                budget = ledger.snapshot()
                budget_status = budget['status']
                budget_review_required = (budget_status == 'uncertain' or
                                          any(row['status'] == 'reserved' for row in budget['reservations']))
            except Exception:
                budget_status = 'unavailable'
                budget_review_required = True
        elif policy is not None and hasattr(policy, 'host'):
            try:
                budget_status = policy.host.observe().get('budget_status')
                budget_review_required = budget_status in ('cost_unknown', 'uncertain')
            except Exception:
                budget_status = 'unavailable'
                budget_review_required = True
        if ledger is not None and policy_closed:
            ledger.close()
        if result is not None:
            if owner is not None and (result.get('seal') or {}).get('sealed') and owner.poll() is None:
                try: owner.wait(timeout=5)
                except (subprocess.TimeoutExpired, AttributeError): pass
            owner_alive = bool(owner and owner.poll() is None)
            video_required = config.get('record_realtime_video', False) is True
            video_readable = (result.get('seal') or {}).get('video', {}).get('readable') is True
            evaluation_required = result.get('reason') == 'world_ended'
            evaluation_present = _evaluation_present(run) if evaluation_required else None
            closed = ((result.get('seal') or {}).get('sealed') and not owner_alive
                      and (result.get('seal') or {}).get('unresolved_action_ids') == []
                      and not result.get('policy_close_error') and not result.get('error_type')
                      and not result.get('seal_error_type')
                      and not budget_review_required
                      and (not video_required or video_readable)
                      and (not evaluation_required or evaluation_present)
                      and (not evaluation_required or result.get('finish_turns_drained') is True
                           or result.get('ended_by') == 'wall_limit')
                      and result.get('reason') in ('world_ended', 'stop_requested', 'wall_limit'))
            result.update(status='finished' if closed else 'needs_review', owner_alive=owner_alive, scored=False,
                          budget_status=budget_status, budget_review_required=budget_review_required,
                          video_required=video_required, evaluation_required=evaluation_required,
                          evaluation_present=evaluation_present)
            write_json(status, result)
        fcntl.flock(lock, fcntl.LOCK_UN); lock.close()
    return result
