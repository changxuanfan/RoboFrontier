"""Shared role lifecycle, accounting and conservative recovery for native CLI engines."""
import json
import math
from decimal import Decimal, InvalidOperation
from pathlib import Path
import sys
import threading
import time
import uuid
from robofrontier.runtime.setup import write_json
from robofrontier.engines.common.native import PreLaunchCancelled
from robofrontier.engines.common.session_recovery import MAX_CAPACITY_RETRIES, recover, recover_model_loss, recover_network, recover_quota
from robofrontier.runtime import layout as run_layout

class SessionHost:
    """Own one policy role's CLI turns; lifecycle events are never task results."""
    def __init__(self, run_dir, actor, profile, base_env, *, python=sys.executable,
                 binary='claude', turn_timeout=None, max_budget_usd=None, total_budget_usd=None,
                 budget_ledger=None, runner=None, _validated_delegate=False,
                 max_capacity_retries=MAX_CAPACITY_RETRIES, engine, mcp, session_id):
        self.engine = engine
        self.run = Path(run_dir).resolve()
        self.actor = actor
        self.profile = dict(profile)
        self.base_env = dict(base_env)
        self.binary = binary
        self.turn_timeout = turn_timeout
        self.max_budget_usd = max_budget_usd
        if budget_ledger is not None and total_budget_usd is not None:
            raise ValueError('Shared ledger cannot be combined with a local total budget')
        self.budget_ledger = budget_ledger
        if total_budget_usd is not None:
            if isinstance(total_budget_usd, bool): raise ValueError('Invalid total budget')
            try: total_budget = Decimal(str(total_budget_usd))
            except InvalidOperation as error: raise ValueError('Invalid total budget') from error
            if not total_budget.is_finite() or total_budget <= 0: raise ValueError('Invalid total budget')
        else:
            total_budget = None
        self.total_budget = total_budget
        self.reported_spend = Decimal('0')
        self.unreported_cost_count = 0
        self.budget_status = 'tracking' if total_budget is not None or budget_ledger is not None else 'not_set'
        # Runs with the frozen policy contract keep one CLI process per session, as the
        # Codex app-server does; earlier runs start one process per turn.
        if runner is None:
            raise ValueError('A native engine runner is required')
        self.runner = runner
        self.mcp = mcp
        self.session_id = session_id
        self.fork_from = self.gate = None  # Set by fork_delegate for the first turn only.
        self.lock = threading.RLock()
        self.state = 'new'
        self.turn_id = None
        self.last_result = None
        self.worker = None
        self.cancel_event = threading.Event()
        if type(max_capacity_retries) is not int or not 0 <= max_capacity_retries <= 10:
            raise ValueError('Capacity retries must be 0..10')
        self.max_capacity_retries = max_capacity_retries
        self.capacity_retry_count = 0
        self.cli_lost = False
        self.capacity_retry_due = None
        self.retryable_capacity = False
        # Wall time the last turn was found failed, and the failed turn whose network
        # continuation was already decided (recovery.recover_network).
        self.failed_at = None
        self.network_handled = None

    def write_summary(self, path, value):
        write_json(path, value)

    def event(self, event, **fields):
        from robofrontier.batch.metrics import host_event
        host_event(self.run, event, actor=self.actor, session_id=self.session_id, turn_id=self.turn_id, **fields)

    def recover_capacity(self, store, now=None):
        """Resume after a capacity failure, a lost CLI, a usage limit or a network outage; False
        leaves ordinary handling."""
        return (recover(self, store, now) or recover_model_loss(self, store) or recover_quota(self, store)
                or recover_network(self, store))

    def send(self, prompt):
        """Start an initial or resumed turn, returning once thread launch is known.

        A failed thread start restores the previous state. Any uncertainty after
        the worker starts blocks further turns and requires operator review.
        """
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('A nonempty prompt is required')
        with self.lock:
            if self.state not in ('new', 'idle'):
                raise ValueError('Role session is active or requires review')
            previous = self.state
            turn_id = str(uuid.uuid4())
            turn_budget = self.max_budget_usd
            if self.budget_ledger is not None:
                turn_budget = self.budget_ledger.reserve(turn_id, self.actor, self.max_budget_usd)
            if self.total_budget is not None:
                remaining = self.total_budget - self.reported_spend
                if self.budget_status != 'tracking' or remaining <= 0:
                    raise ValueError('Task budget exhausted or cost unknown')
                turn_budget = min(float(remaining), turn_budget) if turn_budget is not None else float(remaining)
            self.state, self.turn_id = 'active', turn_id
            worker = threading.Thread(target=self._run, args=(prompt, previous, turn_id, turn_budget), daemon=True)
            self.worker = worker
            try:
                worker.start()
            except Exception:
                self.state, self.turn_id, self.worker = previous, None, None
                if self.budget_ledger is not None:
                    self.budget_ledger.abandon_before_launch(turn_id)
                raise
            return {'threadId': self.session_id, 'turnId': turn_id}

    def _run(self, prompt, previous, turn_id, turn_budget):
        before_launch = False
        fork = {'fork_from': self.fork_from, 'gate': self.gate} if previous == 'new' and self.fork_from else {}
        try:
            record = self.runner(
                self.profile, self.profile['model'], self.profile['effort'], self.mcp,
                prompt, self.run, self.base_env,
                session_id=self.session_id if previous == 'new' else None,
                resume=self.session_id if previous == 'idle' else None,
                timeout=self.turn_timeout, max_budget_usd=turn_budget,
                binary=self.binary, events_name=f'{self.actor}-{turn_id}.jsonl',
                cancel_event=self.cancel_event, actor=self.actor, **fork)
            summary = record.get('summary') or {}
            if record.get('process') != 'exited' or record.get('exit_code') != 0:
                state = 'error' if summary.get('turn_status') == 'failed' else 'unknown'
            elif summary.get('session_id') != self.session_id:
                state = 'unknown'
            elif summary.get('turn_status') == 'ended' and not summary.get('malformed_lines'):
                state = 'idle'
            elif summary.get('turn_status') == 'failed':
                state = 'error'
            else:
                state = 'unknown'
        except PreLaunchCancelled:
            before_launch = True
            record = {'process': 'not_launched', 'error_type': 'PreLaunchCancelled'}
            state = 'unknown'
        except Exception as error:
            # Do not record exception text: provider errors can contain credentials.
            record = {'process': 'unknown', 'error_type': type(error).__name__}
            state = 'unknown'
        with self.lock:
            if self.cancel_event.is_set():
                state = 'unknown'
            summary = record.get('summary') or {}
            # The CLI died mid-turn (not a stop or deadline): it exited without a result. In
            # a run prepared with a restart notice that is a failed turn the session may resume.
            self.cli_lost = (not self.cancel_event.is_set()
                             and (record.get('process') == 'process_exited'
                                  or record.get('process') == 'exited' and record.get('exit_code') not in (0, None))
                             and summary.get('turn_status') not in ('ended', 'failed')
                             and (self.run/'private/inputs/bootstrap/model-restart.md').is_file())
            if self.cli_lost: state = 'error'
            retryable = (state == 'error' and record.get('process') == 'exited'
                         and summary.get('session_id') == self.session_id
                         and summary.get('turn_status') == 'failed'
                         and summary.get('result_subtype') == 'error_during_execution'
                         and not summary.get('malformed_lines') and bool(summary.get('capacity_error_code')))
            if self.budget_ledger is not None:
                summary = record.get('summary') or {}
                # A lost CLI's turn has ended; only its cost is unknown (counted as unreported).
                known = self.cli_lost or (not self.cancel_event.is_set() and record.get('process') == 'exited'
                         and (record.get('exit_code') == 0 or retryable)
                         and summary.get('session_id') == self.session_id
                         and summary.get('turn_status') in ('ended', 'failed')
                         and not summary.get('malformed_lines'))
                try:
                    if before_launch:
                        self.budget_ledger.abandon_before_launch(turn_id)
                        shared = self.budget_ledger.snapshot()
                    else:
                        shared = self.budget_ledger.settle(turn_id, summary.get('total_cost_usd'), outcome_known=known)
                    self.budget_status = shared['status']
                    self.reported_spend = Decimal(shared['reported_spend_usd'])
                    self.unreported_cost_count = shared['unreported_cost_count']
                    if shared['status'] == 'uncertain': state = 'unknown'
                    if shared['status'] == 'exhausted' and not any(r['status'] == 'reserved' for r in shared['reservations']):
                        if state == 'idle': state = 'error'
                except Exception:
                    self.budget_status = 'cost_unknown'
                    state = 'unknown'
            if self.budget_ledger is None and not before_launch:
                cost = (record.get('summary') or {}).get('total_cost_usd')
                try:
                    amount = Decimal(str(cost)) if not isinstance(cost, bool) else Decimal('NaN')
                    if not amount.is_finite() or amount < 0 or (self.total_budget is not None and amount == 0): raise InvalidOperation
                except (InvalidOperation, ValueError):
                    self.unreported_cost_count += 1
                    if self.total_budget is not None:
                        self.budget_status = 'cost_unknown'
                        state = 'unknown'
                else:
                    self.reported_spend += amount
                    if self.total_budget is not None and self.reported_spend >= self.total_budget:
                        self.budget_status = 'exhausted'
                        if state == 'idle': state = 'error'
            accounting = {'status': self.budget_status, 'reported_spend_usd': str(self.reported_spend),
                          'unreported_cost_count': self.unreported_cost_count,
                          'limit_usd': str(self.total_budget) if self.total_budget is not None else
                                       shared['limit_usd'] if self.budget_ledger is not None and 'shared' in locals() else None,
                          'source': 'cli_reported_estimate_not_provider_bill'}
            self.last_result = record
            try:
                self.write_summary(run_layout.path(self.run, 'engine_turns', self.engine) / f'{self.actor}-{turn_id}-summary.json',
                           {'actor': self.actor, 'session_id': self.session_id, 'turn_id': turn_id,
                            'status': state, 'record': record, 'cost_accounting': accounting})
            except Exception:
                # An unrecorded turn cannot be resumed safely.
                state = 'unknown'
            self.state = state
            self.failed_at = time.time() if state == 'error' else None
            self.retryable_capacity = retryable and state == 'error'
            if state == 'idle':
                self.capacity_retry_count = 0
                self.capacity_retry_due = None

    def adopt(self, session_id):
        """Continue an existing session of this role (a run continued after an unexpected
        exit, docs/running/continuation.md): the next turn resumes it instead of creating one."""
        with self.lock:
            if self.state != 'new': raise ValueError('Only a new host can adopt a session')
            self.session_id = str(session_id); self.state = 'idle'
        return self

    def observe(self):
        """Return bounded process evidence, not an assertion of physical success."""
        with self.lock:
            summary = (self.last_result or {}).get('summary') or {}
            subtype = summary.get('result_subtype')
            if subtype not in ('success', 'error_max_budget_usd', 'error_max_turns',
                               'error_during_execution', 'error_max_structured_output_retries'):
                subtype = None
            cost = summary.get('total_cost_usd')
            if isinstance(cost, bool) or not isinstance(cost, (int, float)) or not math.isfinite(cost) or cost < 0:
                cost = None
            return {'actor': self.actor, 'thread_id': self.session_id,
                    'status': self.state, 'turn_id': self.turn_id, 'budget_status': self.budget_status,
                    'reported_spend_usd': str(self.reported_spend),
                    'unreported_cost_count': self.unreported_cost_count,
                    'retryable_capacity': self.retryable_capacity,
                    'capacity_retry_count': self.capacity_retry_count,
                    'last_result_subtype': subtype, 'last_turn_reported_cost_usd': cost}

    def wait(self, timeout=None):
        with self.lock:
            worker = self.worker
        if worker:
            worker.join(timeout)
        return self.observe()

    def close_process(self):
        """Close a persistent CLI process, if any; its transcript stays resumable."""
        if hasattr(self.runner, 'close'): self.runner.close()

    def stop(self):
        """Request termination of an active turn; physical state still needs sealing."""
        with self.lock:
            self.cancel_event.set()
            if self.state in ('new', 'idle'):
                self.state = 'unknown'
            return self.observe()
