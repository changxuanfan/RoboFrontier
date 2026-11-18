"""What tests read from a Claude batch folder, and the stop request `roboteam stop` makes."""

import fcntl
import json
from pathlib import Path

from roboteam.launch import claude_batch
from roboteam.runtime.run import layout


def batch_state(folder):
    """The batch's recorded status, whether its supervisor still holds the lock, and each run's markers."""
    folder = Path(folder).resolve()
    jobs = claude_batch._jobs(folder)
    state_file = layout.batch_path(folder, 'engineering_status')
    state = json.loads(state_file.read_text()) if state_file.exists() else {'status': 'not_started'}
    lock_path = layout.batch_path(folder, 'engineering_lock')
    live = False
    if lock_path.exists():
        with lock_path.open('r') as lock:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                live = True
            else:
                fcntl.flock(lock, fcntl.LOCK_UN)
    state['supervisor_live'] = live
    state['stop_requested'] = layout.batch_path(folder, 'stop').exists()
    state['runs'] = []
    for run in (Path(job['run_directory']) for job in jobs):
        status = layout.path(run, 'engineering_status')
        state['runs'].append(
            {
                'detail': json.loads(status.read_text()) if status.exists() else None,
                'claim_record_present': layout.path(run, 'engineering_claim').exists(),
                'stop_requested': layout.path(run, 'stop').exists(),
            }
        )
    return state


def request_stop(folder):
    """Mark the batch and every run as stopped, after validating every run path."""
    folder = Path(folder).resolve()
    claude_batch._stop_all(folder, claude_batch._jobs(folder))
