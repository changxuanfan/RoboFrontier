"""Bounded capacity recovery; never resubmits robot requests or recreates forks."""
from robofrontier.claude.native_home import history_directory
import json
import time

from robofrontier.claude.provenance import history, transcript_rows
from robofrontier import run_layout

MAX_CAPACITY_RETRIES = 3
BASE_DELAY_SECONDS = 10
MAX_DELAY_SECONDS = 60
# The same policy as the Codex host (robofrontier/codex/codex_policy_host.js): 10/20/40 s plus a
# 0-5 s jitter fixed by the session ID, so many runs do not retry together.
JITTER_SECONDS = 5


def capacity_delay(attempt, session_id):
    jitter = sum(map(ord, str(session_id))) % (JITTER_SECONDS*1000) / 1000
    return min(MAX_DELAY_SECONDS, BASE_DELAY_SECONDS * 2**attempt) + jitter
CAPACITY_CODES = frozenset(('rate_limit', 'rate_limit_error', 'overloaded_error', 'server_overloaded'))
CONTINUE_PROMPT = ('The previous model turn ended with a confirmed capacity or rate-limit error. '
                   'Continue the same running task and saved work. Inspect pending and original job IDs '
                   'before further actions; do not replay submitted motion or recreate delegates. '
                   'The experiment has already STARTED; continue without another START. '
                   'The original task deadline still applies.')


def capacity_code(events):
    """Only structured CLI/API error fields count, never model text or stderr."""
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


def recover(host, store, now=None):
    """Return True while safely waiting/retrying; False leaves ordinary error handling.

    Caller keeps polling its original deadline and STOP. Successful retries stay
    in the same native session. Unknown process outcomes and uncertain costs under
    explicit caps never enter this path.
    """
    now = time.monotonic() if now is None else now
    with host.lock:
        if (host.state != 'error' or not host.retryable_capacity
                or host.capacity_retry_count >= host.max_capacity_retries
                or host.cancel_event.is_set() or run_layout.path(host.run, 'stop', 'claude').exists()
                or store.get('lifecycle') != 'running' or store.get('dispatch_paused', False)):
            return False
        try:
            if not history(transcript_rows(history_directory(host.run), host.session_id), host.session_id): return False
        except ValueError:
            return False
        actions = store.actions(host.actor).values()
        if any(a['status'] == 'uncertain' and not (a.get('isolated') or a.get('local_recovery')) for a in actions): return False
        from robofrontier.scheduling import blocks_model_recovery
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
            host.send(CONTINUE_PROMPT)
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
    from robofrontier.policy_bootstrap import MAX_MODEL_RESTARTS
    notice = host.run/'private/inputs/bootstrap/model-restart.md'
    with host.lock:
        if (host.state != 'error' or not getattr(host, 'cli_lost', False) or not notice.is_file()
                or host.cancel_event.is_set() or run_layout.path(host.run, 'stop', 'claude').exists()
                or store.get('lifecycle') != 'running' or store.get('dispatch_paused', False)):
            return False
        if host.budget_status not in ('tracking', 'not_set'): return False
        from robofrontier.scheduling import blocks_model_recovery
        busy = any(blocks_model_recovery(a) for a in store.actions(host.actor).values())
        busy = busy or bool(store.db.execute("SELECT 1 FROM calls WHERE actor=? AND status='accepted' LIMIT 1",
                                            (host.actor,)).fetchone())
        if busy: return True
        restart = store.claim_model_restart(host.actor, 'claude', MAX_MODEL_RESTARTS)
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
