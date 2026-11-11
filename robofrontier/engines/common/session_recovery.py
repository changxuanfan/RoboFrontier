"""Bounded capacity recovery; never resubmits robot requests or recreates forks."""
import json
import time

from robofrontier.runtime import layout as run_layout

from robofrontier.runtime.bootstrap import MAX_CAPACITY_RETRIES
EXHAUSTED_REASON = 'Model capacity recovery attempts exhausted'
BASE_DELAY_SECONDS = 10
MAX_DELAY_SECONDS = 60
# The same policy as the Codex host (robofrontier/engines/codex/codex_policy_host.js): 10/20/40 s plus a
# 0-5 s jitter fixed by the session ID, so many runs do not retry together.
JITTER_SECONDS = 5


def capacity_delay(attempt, session_id):
    jitter = sum(map(ord, str(session_id))) % (JITTER_SECONDS*1000) / 1000
    return min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * 2**attempt) + jitter
CAPACITY_CODES = frozenset(('rate_limit', 'rate_limit_error', 'overloaded_error', 'server_overloaded'))


def usage_limit_of(events):
    """The plan usage limit a failed turn's API error message or result names (runtime/quota.py), or None.

    Only the CLI's own error records count: an assistant message marked as an API error, and the
    result record; never the model's text."""
    from robofrontier.runtime.quota import usage_limit
    texts = []
    for event in events:
        if event.get('type') == 'assistant' and event.get('isApiErrorMessage') is True:
            for block in (event.get('message') or {}).get('content') or []:
                if isinstance(block, dict) and isinstance(block.get('text'), str): texts.append(block['text'])
        elif event.get('type') == 'result' and (event.get('is_error') or event.get('subtype') != 'success'):
            if isinstance(event.get('result'), str): texts.append(event['result'])
    for text in reversed(texts):
        found = usage_limit(text)
        if found: return found
    return None


def capacity_code(events):
    """Only structured CLI/API error fields count, never model text or stderr. A plan's usage
    limit is not a capacity error: it waits for its reset (recover_quota)."""
    if usage_limit_of(events): return None
    for event in reversed(events):
        if event.get('type') == 'assistant' and event.get('isApiErrorMessage') is True:
            code = event.get('error')
        elif event.get('type') == 'error' and isinstance(event.get('error'), dict):
            code = event['error'].get('type')
        else:
            continue
        if isinstance(code, dict): code = code.get('type')
        return code if isinstance(code, str) and code in CAPACITY_CODES else None
    return None


def recover(host, store, now=None, *, history_available=None):
    """Return True while safely waiting/retrying; False leaves ordinary error handling.

    Caller keeps polling its original deadline and STOP. Successful retries stay
    in the same native session. Unknown process outcomes and uncertain costs under
    explicit caps never enter this path.
    """
    now = time.monotonic() if now is None else now
    with host.lock:
        if (host.state == 'error' and host.retryable_capacity and host.capacity_retry_count >= host.max_capacity_retries
                and not getattr(host, 'capacity_exhausted', False) and store.get('lifecycle') == 'running'):
            # Used up: pause the run, as the Codex host does (codex_policy_host.js retryCapacity).
            from robofrontier.runtime.cli import execute
            host.capacity_exhausted = True
            execute(store, 'pause', {'reason': EXHAUSTED_REASON, 'actor': host.actor, 'thread_id': host.session_id},
                    'claude-recovery', time.time())
            host.event('capacity_recovery_exhausted', retries=host.capacity_retry_count)
            return False
        notice = host.run/'private/inputs/bootstrap/capacity-resume.md'
        if (host.state != 'error' or not host.retryable_capacity or not notice.is_file()
                or host.capacity_retry_count >= host.max_capacity_retries
                or host.cancel_event.is_set() or run_layout.path(host.run, 'stop', getattr(host, 'engine', 'claude')).exists()
                or store.get('lifecycle') != 'running' or store.get('dispatch_paused', False)):
            return False
        try:
            if not (history_available or host.history_available)(): return False
        except ValueError:
            return False
        actions = store.actions(host.actor).values()
        if any(a['status'] == 'uncertain' and not (a.get('isolated') or a.get('local_recovery')) for a in actions): return False
        from robofrontier.runtime.scheduling import blocks_model_recovery
        busy = any(blocks_model_recovery(a) for a in store.actions(host.actor).values())
        busy = busy or bool(store.db.execute("SELECT 1 FROM calls WHERE actor=? AND status='accepted' LIMIT 1",
                                            (host.actor,)).fetchone())
        # A delegate batch still being forked must not be retried through this mechanism.
        if any(b['status'] == 'creating' for b in store.get('delegations', {}).values()): return False
        if host.capacity_retry_due is None:
            host.capacity_retry_due = now + capacity_delay(host.capacity_retry_count, host.session_id)
            host.event('capacity_wait', retry_number=host.capacity_retry_count+1,
                       error_code=(host.last_result or {}).get('summary', {}).get('capacity_error_code'),
                       max_retries=host.max_capacity_retries,
                       delay_s=host.capacity_retry_due-now)
        if busy or now < host.capacity_retry_due: return True
        host.capacity_retry_count += 1
        host.capacity_retry_due = None
        host.retryable_capacity = False
        host.state = 'idle'  # Proven failure; this is a resume, never a new session.
        host.event('capacity_retry', retry_number=host.capacity_retry_count)
        try:
            host.send(notice.read_text())
        except Exception:
            host.state = 'unknown'
            raise
        return True


def recover_model_loss(host, store):
    """Resume a session whose CLI died mid-turn while the world kept running.

    The robot calls that turn started keep running in the world, so the same session
    resumes once this role has no action in flight, with the frozen restart notice the
    Codex route also sends. The run allows MAX_MODEL_RESTARTS in total.
    """
    from robofrontier.runtime.bootstrap import MAX_MODEL_RESTARTS
    notice = host.run/'private/inputs/bootstrap/model-restart.md'
    with host.lock:
        if (host.state != 'error' or not getattr(host, 'cli_lost', False) or not notice.is_file()
                or host.cancel_event.is_set() or run_layout.path(host.run, 'stop', getattr(host, 'engine', 'claude')).exists()
                or store.get('lifecycle') != 'running' or store.get('dispatch_paused', False)):
            return False
        if host.budget_status not in ('tracking', 'not_set'): return False
        from robofrontier.runtime.scheduling import blocks_model_recovery
        busy = any(blocks_model_recovery(a) for a in store.actions(host.actor).values())
        busy = busy or bool(store.db.execute("SELECT 1 FROM calls WHERE actor=? AND status='accepted' LIMIT 1",
                                            (host.actor,)).fetchone())
        if busy: return True
        restart = store.claim_model_restart(host.actor, getattr(host, 'engine', 'claude'), MAX_MODEL_RESTARTS)
        if restart is None:
            return False
        host.cli_lost = False
        host.state = 'idle'  # The same session resumes; it is never recreated.
        host.event('model_host_restart', attempt=restart)
        try:
            host.send(notice.read_text())
        except Exception:
            host.state = 'unknown'
            raise
        return True


# A failed turn's structured API error that names a lost connection (the CLI's typed `api_error`
# kinds for a connection failure, an unanswered request, a stalled stream and a sleeping host).
# It has no HTTP status: a status means the API answered.
NETWORK_API_ERRORS = frozenset(('connection_failed', 'no_response', 'stream_idle_timeout', 'computer_slept'))
# How long a network failure waits for the world's outage or egress pause to notice it (three
# failed probes take about 15-35 s); without one it is an ordinary failed turn. The same margin
# bounds how far a failure may come before a pause (runtime_cli network-recovery).
NETWORK_WAIT_S = 30.
NETWORK_WINDOW_S = 30.


def api_error(events):
    """The last structured API error of a turn, or None. Only typed CLI fields count."""
    for event in reversed(events):
        if event.get('type') != 'assistant': continue
        if event.get('isApiErrorMessage') is not True and event.get('is_api_error_message') is not True: continue
        kind, status, error = (event.get('api_error', event.get('apiError')),
                               event.get('api_error_status', event.get('apiErrorStatus')), event.get('error'))
        return {'error': error if isinstance(error, str) else None, 'api_error': kind if isinstance(kind, str) else None,
                'status': status if isinstance(status, int) and not isinstance(status, bool) else None}
    return None


def failure_kind(summary):
    """'network', 'other' or None (not told by the turn's own record) for a failed turn."""
    error = summary.get('api_error')
    if isinstance(error, dict):
        if error.get('status') is None and error.get('api_error') in NETWORK_API_ERRORS: return 'network'
        # An untyped server error without HTTP status is how the CLI reports other lost connections.
        if error.get('status') is None and error.get('api_error') is None and error.get('error') == 'server_error': return None
        return 'other'
    if summary.get('capacity_error_code'): return 'other'
    if summary.get('result_subtype') not in (None, 'success', 'error_during_execution'): return 'other'
    return None


def recover_quota(host, store, now=None):
    """A turn that failed on the plan's usage limit: the world pauses until the reset, then the
    same session continues once with the frozen quota notice (runtime/quota.py), as the Codex
    host does (codex_policy_host.js retryQuota). Returns True while asking, waiting or resending."""
    from robofrontier.runtime.cli import execute
    wall = time.time() if now is None else now
    notice = host.run/'private/inputs/bootstrap/quota-resume.md'
    with host.lock:
        limit = ((host.last_result or {}).get('summary') or {}).get('usage_limit')
        if (host.state != 'error' or not limit or not notice.is_file() or getattr(host, 'quota_handled', None) == host.turn_id
                or host.cancel_event.is_set() or run_layout.path(host.run, 'stop', getattr(host, 'engine', 'claude')).exists()
                or store.get('lifecycle') != 'running'):
            return False
        ids = {'actor': host.actor, 'thread_id': host.session_id}
        failed_at = getattr(host, 'failed_at', None) or wall
        if getattr(host, 'quota_turn', None) != host.turn_id:
            execute(store, 'quota-pause', {**ids, 'resets_at': limit.get('resets_at'), 'text': limit.get('text')}, host.actor, wall)
            host.quota_turn = host.turn_id
            host.event('quota_pause_requested', resets_at=limit.get('resets_at'), failed_turn_id=host.turn_id)
            return True
        recovery = store.get('egress_recovery')
        if (store.get('quota_pause') or store.get('dispatch_paused', False) or not recovery
                or not str(recovery.get('claim', '')).startswith('quota-') or recovery['resumed_at'] < failed_at):
            return True  # the world is paused, or has not yet paused, for the limit
        from robofrontier.runtime.scheduling import blocks_model_recovery
        if (any(blocks_model_recovery(a) for a in store.actions(host.actor).values())
                or store.db.execute("SELECT 1 FROM calls WHERE actor=? AND status IN ('accepted','running','uncertain') "
                                    "AND op IN ('move','gripper','action_batch','delegate') LIMIT 1", (host.actor,)).fetchone()):
            return True
        claim = execute(store, 'network-recovery', {**ids, 'failed_turn_id': host.turn_id, 'error_observed_at': failed_at},
                        host.actor, wall)
        if claim.get('review_required'):
            host.quota_handled = host.turn_id
            execute(store, 'network-recovery-uncertain', ids, host.actor, wall)
            host.event('quota_continuation_uncertain', failed_turn_id=host.turn_id)
            return True
        if not claim.get('allowed'): return False
        failed_turn = host.turn_id
        host.quota_handled = failed_turn
        host.state = 'idle'  # Proven failure; the same session continues, never a new one.
        try:
            host.send(notice.read_text())
        except Exception:
            host.state = 'error'
            execute(store, 'network-recovery-uncertain', ids, host.actor, wall)
            return True
        host.event('quota_continuation', failed_turn_id=failed_turn)
        return True


def _active_time(run):
    from robofrontier.runtime.clock import WALL_CLOCK, run_clock
    task = run/'private/inputs/task.json'
    try: return run_clock(json.loads(task.read_text()).get('run_protocol') or {}) != WALL_CLOCK
    except (OSError, ValueError, AttributeError): return False


def recover_network(host, store, now=None, *, active_time=None):
    """Resend once a turn that failed on the network during an outage or egress pause.

    Runs whose protocol counts active time only (clock active_time_v1), as the Codex host does
    (codex_policy_host.js retryCapacity): after the world resumes it records `egress_recovery`;
    a failed turn of this role seen within that pause (NETWORK_WINDOW_S either side) that is a
    network failure, or whose record does not say what failed, is continued once per role and
    pause in the same session with the frozen network notice, once the role has no robot work
    in flight. No request or action is replayed. A second failure in the same pause, or a turn
    that failed for another reason within it, holds the run for review
    (runtime_cli network-recovery-uncertain). A network failure seen before any pause waits up
    to NETWORK_WAIT_S for one. Returns True while waiting, resending or holding."""
    from robofrontier.runtime.cli import execute
    wall = time.time() if now is None else now
    notice = host.run/'private/inputs/bootstrap/network-resume.md'
    with host.lock:
        failed_at = getattr(host, 'failed_at', None)
        if (host.state != 'error' or failed_at is None or getattr(host, 'cli_lost', False)
                or getattr(host, 'network_handled', None) == host.turn_id
                or host.cancel_event.is_set() or run_layout.path(host.run, 'stop', getattr(host, 'engine', 'claude')).exists()
                or not notice.is_file() or not (active_time or _active_time)(host.run)
                or store.get('lifecycle') != 'running' or store.get('dispatch_paused', False)
                or host.budget_status not in ('tracking', 'not_set')):
            return False
        summary = (host.last_result or {}).get('summary') or {}
        kind = failure_kind(summary)
        if summary.get('capacity_error_code'): return False  # capacity has its own bounded retries
        recovery = store.get('egress_recovery')
        within = bool(recovery and recovery['paused_at'] - NETWORK_WINDOW_S <= failed_at
                      <= recovery['resumed_at'] + NETWORK_WINDOW_S)
        if not within:
            return kind == 'network' and wall - failed_at < NETWORK_WAIT_S
        ids = {'actor': host.actor, 'thread_id': host.session_id}

        def hold(why):
            host.network_handled = host.turn_id
            execute(store, 'network-recovery-uncertain', ids, host.actor, wall)
            host.event('network_continuation_uncertain', reason=why, failed_turn_id=host.turn_id)
            return True

        if kind == 'other': return hold('turn failed for another reason during a network outage')
        from robofrontier.runtime.scheduling import blocks_model_recovery
        if (any(blocks_model_recovery(a) for a in store.actions(host.actor).values())
                or store.db.execute("SELECT 1 FROM calls WHERE actor=? AND status IN ('accepted','running','uncertain') "
                                    "AND op IN ('move','gripper','action_batch','delegate') LIMIT 1", (host.actor,)).fetchone()):
            return True
        claim = execute(store, 'network-recovery', {**ids, 'failed_turn_id': host.turn_id, 'error_observed_at': failed_at},
                        host.actor, wall)
        if claim.get('review_required'): return hold('second failure in the same outage, or outside its window')
        if not claim.get('allowed'): return False
        failed_turn = host.turn_id
        host.network_handled = failed_turn
        host.state = 'idle'  # Proven failure; the same session continues, never a new one.
        try:
            host.send(notice.read_text())
        except Exception:
            host.state = 'error'
            return hold('network continuation could not be sent')
        host.event('network_continuation', failed_turn_id=failed_turn, failure=kind or 'unclassified')
        return True
