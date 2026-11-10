"""Single-use, unqualified engineering batches; not a scored benchmark runner."""
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import fcntl
import json
from pathlib import Path
import re
import time

from robofrontier.claude.engineering_run import _check_shared_budget, _positive, run_engineering
from robofrontier.claude.runner import build_env
from robofrontier.claude.native_home import config_directory
from robofrontier import run_layout
from robofrontier.run_setup import verify_inputs, write_json
from robofrontier.launch_schedule import LaunchSchedule
from robofrontier.run_segments import try_continue

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')


def _b(folder, key):
    return run_layout.batch_path(folder, key)


def _r(run, key):
    return run_layout.path(run, key, 'claude')


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


def _stop_all(folder, jobs):
    _touch(_b(folder, 'stop'))
    for job in jobs: _touch(_r(job['run_directory'], 'stop'))


def _jobs(folder):
    folder = Path(folder).resolve()
    batch = json.loads((folder / 'batch.json').read_text())
    if batch.get('schema') != 'robofrontier.claude-draft.v1' or batch.get('status') != 'prepared_not_qualified' or batch.get('execution_available') is not False:
        raise ValueError('Expected a completed unqualified engineering draft batch')
    jobs = batch.get('jobs')
    if not isinstance(jobs, list) or not jobs: raise ValueError('Batch has no jobs')
    seen = set()
    for job in jobs:
        name, case = job.get('profile'), job.get('case_id')
        if not isinstance(name, str) or not ID.fullmatch(name) or not isinstance(case, str) or not ID.fullmatch(case):
            raise ValueError('Invalid profile or case name')
        expected = (folder / name / case).resolve()
        if not expected.is_relative_to(folder) or Path(job['run_directory']).resolve() != expected or expected in seen:
            raise ValueError('Unexpected or duplicate run directory')
        if not expected.is_dir(): raise ValueError('Run directory missing')
        seen.add(expected)
    return jobs


# Supervisor results that mean the physical world stopped under a live host.
WORLD_DIED = ('owner_unavailable', 'world_interrupted')


def _run_once_continued(runner, run_dir, base_env, continuing=False, **options):
    """One run, continued once in a new segment after an unexpected exit (docs/running/run-segments.md).

    With `continuing`, a run that had started before the batch process died is first
    prepared for its next segment; a run that never started starts normally.
    """
    from robofrontier.runtime_store import RuntimeStore
    segments = []
    if continuing:
        store = RuntimeStore(Path(run_dir) / 'private/state/runtime.sqlite')
        try: lifecycle = store.get('lifecycle')
        finally: store.close()
        if lifecycle not in ('prepared', 'resuming'):
            continued, why = try_continue(run_dir, 'batch process exited')
            segments.append({'reason': 'batch process exited', 'continued': continued, 'why': why})
            if not continued:
                return {'status': 'needs_review', 'reason': 'not_continued', 'segments': segments}
    while True:
        result = runner(run_dir, base_env, **options)
        # Only a world that died continues. The host's own wall limit, a STOP, a finish or
        # any other end it chose is final, even if its seal could not be recorded.
        if result.get('reason') not in WORLD_DIED: break
        continued, why = try_continue(run_dir, 'engine run ended: ' + str(result.get('reason')))
        segments.append({'reason': result.get('reason'), 'continued': continued, 'why': why})
        if not continued: break
    result['segments'] = segments
    return result


def _preflight(jobs, env, verifier, continuing=False, budgets=(None, None)):
    for job in jobs:
        run = Path(job['run_directory'])
        if _r(run, 'stop').exists() or (_r(run, 'engineering_claim').exists() and not continuing):
            raise ValueError('A run is stopped or already claimed')
        changed = verifier(run)
        if changed: raise ValueError('Frozen inputs changed: ' + ', '.join(changed))
        launch = json.loads((run / 'private/inputs/claude.json').read_text())
        config = json.loads((run / 'private/inputs/harness.json').read_text())
        profile = launch['profile']
        if (launch.get('schema') != 'robofrontier.claude-launch-draft.v1' or launch.get('qualified') is not False
                or launch.get('execution_available') is not False or config.get('engine') != 'claude'
                or config.get('topology') not in ('centralized', 'adaptive', 'hierarchical', 'peer') or config.get('model') != profile.get('model')
                or config.get('effort') != profile.get('effort')):
            raise ValueError('Run does not match the engineering launch profile')
        _check_shared_budget(run, config['topology'], *budgets)
        if profile.get('auth_mode') != 'native_login' and not env.get(profile.get('env_key')):
            raise ValueError('Missing provider credential variable')
        if profile.get('provider') != 'anthropic' and not profile.get('base_url'):
            raise ValueError('Third-party provider base URL is missing')
        # Validate authentication for every job before claiming or launching any.
        # The returned environment is deliberately discarded and never logged.
        home = config_directory(run, profile)
        if profile.get('auth_mode') == 'native_login' and home.is_relative_to(run.parents[1]):
            raise ValueError('Keep the native authentication home outside the evidence batch')
        build_env(profile, env, home)


def status_batch(folder):
    folder = Path(folder).resolve()
    jobs = _jobs(folder)
    state_file = _b(folder, 'engineering_status')
    state = json.loads(state_file.read_text()) if state_file.exists() else {'status': 'not_started'}
    lock_path = _b(folder, 'engineering_lock')
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
    state['stop_requested'] = _b(folder, 'stop').exists()
    if not state_file.exists() and _b(folder, 'engineering_claim').exists():
        state['status'] = 'starting' if live else 'claim_without_status_needs_review'
    elif not state_file.exists() and _b(folder, 'stop').exists():
        state['status'] = 'stopped_before_start'
    if state.get('status') == 'running' and not live:
        state['status'] = 'supervisor_lost_needs_review'
    state['runs'] = []
    for job in jobs:
        run = Path(job['run_directory'])
        path = _r(run, 'engineering_status')
        state['runs'].append({'profile': job['profile'], 'case_id': job['case_id'],
                              'detail': json.loads(path.read_text()) if path.exists() else None,
                              'claim_record_present': _r(run, 'engineering_claim').exists(),
                              'stop_requested': _r(run, 'stop').exists()})
    return state


def stop_batch(folder):
    folder = Path(folder).resolve()
    jobs = _jobs(folder)  # Validate every path before changing any stop marker.
    _stop_all(folder, jobs)
    return {'stop_requested': True, 'jobs': len(jobs), 'note': 'Request only; inspect status and sealing outcome.'}


def run_batch(folder, base_env, *, parallel, turn_budget_usd=None, total_budget_usd=None, wall_limit_s=86400,
              startup_timeout_s=120, runner=run_engineering, verifier=verify_inputs, stop_requested=lambda: False,
              startup_interval_s=.3, continuing=False):
    """Run drafts once. Caller explicitly authorizes potential paid model calls.

    `continuing` picks up a batch whose process died: unfinished runs continue in their
    next segment (at most once each) and runs that never started start now.
    """
    folder = Path(folder).resolve()
    if type(parallel) is not int or not 1 <= parallel <= 36: raise ValueError('Parallel must be 1..36')
    if turn_budget_usd is not None: _positive(turn_budget_usd, 'per-turn budget', 1000)
    if total_budget_usd is not None: _positive(total_budget_usd, 'per-task budget', 1000)
    _positive(wall_limit_s, 'wall limit', 86400)
    _positive(startup_timeout_s, 'startup timeout', 86400)
    jobs = _jobs(folder)
    schedule = LaunchSchedule(startup_interval_s)
    lock_path = _b(folder, 'engineering_lock')
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        claim = _b(folder, 'engineering_claim')
        state_path = _b(folder, 'engineering_status')
        if continuing:
            state = json.loads(state_path.read_text())
            if not claim.exists() or state.get('status') != 'running':
                raise ValueError('Only a batch whose process stopped while running can continue')
            unfinished = [i for i, j in enumerate(state['jobs']) if j['status'] in ('queued', 'starting')]
            jobs = [jobs[i] for i in unfinished]
        elif claim.exists(): raise ValueError('Batch already claimed; never restart')
        if _b(folder, 'stop').exists() or stop_requested(): raise ValueError('Batch was stopped before launch')
        _preflight(jobs, base_env, verifier, continuing, (turn_budget_usd, total_budget_usd))
        if _b(folder, 'stop').exists() or stop_requested(): raise ValueError('Batch was stopped before launch')
        if continuing:
            state.setdefault('continued_at', []).append(time.time())
            positions = unfinished
        else:
            with claim.open('x') as out:
                import os
                os.fchmod(out.fileno(), 0o600)
                json.dump({'claimed_at': time.time(), 'pid': os.getpid()}, out)
                out.flush(); os.fsync(out.fileno())
            state = {'schema': 'robofrontier.claude-engineering-status.v1', 'status': 'running',
                     'started_at': time.time(), 'parallel': parallel, 'scored': False,
                     'turn_budget_usd': turn_budget_usd, 'task_budget_usd': total_budget_usd, 'wall_limit_s': wall_limit_s,
                     'startup_timeout_s': startup_timeout_s,
                     'jobs': [{'profile': j['profile'], 'case_id': j['case_id'], 'status': 'queued'} for j in jobs]}
            positions = list(range(len(jobs)))
        write_json(state_path, state)
        next_job = 0
        pending = {}
        with ThreadPoolExecutor(max_workers=parallel) as pool:
            while next_job < len(jobs) or pending:
                stopping = _b(folder, 'stop').exists() or stop_requested()
                if stopping:
                    _stop_all(folder, jobs)
                while not stopping and next_job < len(jobs) and len(pending) < parallel:
                    # A stop request can arrive while other jobs are being submitted.
                    if _b(folder, 'stop').exists() or stop_requested():
                        stopping = True
                        _stop_all(folder, jobs)
                        break
                    local = next_job; index = positions[local]
                    future = schedule.launch(lambda: pool.submit(
                        _run_once_continued, runner, jobs[local]['run_directory'], base_env, continuing=continuing,
                        turn_budget_usd=turn_budget_usd, total_budget_usd=total_budget_usd,
                        wall_limit_s=wall_limit_s, startup_timeout_s=startup_timeout_s),
                        stopped=lambda:_b(folder, 'stop').exists() or stop_requested())
                    if future is None:
                        stopping = True
                        _stop_all(folder, jobs)
                        break
                    next_job += 1
                    state['jobs'][index]['status'] = 'starting'
                    write_json(state_path, state)
                    pending[future] = index
                if stopping and next_job < len(jobs):
                    for local in range(next_job, len(jobs)): state['jobs'][positions[local]]['status'] = 'stopped_before_start'
                    next_job = len(jobs); write_json(state_path, state)
                if not pending: break
                done, _ = wait(pending, timeout=.25, return_when=FIRST_COMPLETED)
                for future in done:
                    index = pending.pop(future)
                    try:
                        result = future.result()
                        state['jobs'][index]['status'] = 'closed' if result.get('status') == 'finished' else 'needs_review'
                        state['jobs'][index]['reason'] = 'wall_backstop' if result.get('wall_backstop') else result.get('reason')
                        if result.get('segments'): state['jobs'][index]['segments'] = result['segments']
                    except Exception as error:
                        state['jobs'][index].update(status='needs_review', error_type=type(error).__name__)
                    write_json(state_path, state)
        # A task recovered by hand (robofrontier/claude/recover_task.py) closes before the batch does.
        from robofrontier.claude.recover_task import wait_for_recoveries
        waiting = [{'run_directory': jobs[local]['run_directory'], 'status': state['jobs'][index]['status']}
                   for local, index in enumerate(positions)]
        wait_for_recoveries(waiting)
        for entry, index in zip(waiting, positions):
            if 'recovery' in entry: state['jobs'][index].update(status=entry['status'], recovery=entry['recovery'])
        if any(j['status'] == 'needs_review' for j in state['jobs']):
            state['status'] = 'needs_review'
        elif any(j['status'] == 'stopped_before_start' or j.get('reason') == 'stop_requested'
                 for j in state['jobs']):
            state['status'] = 'stopped'
        else:
            state['status'] = 'closed'
        state['finished_at'] = time.time()
        write_json(state_path, state)
        return state
