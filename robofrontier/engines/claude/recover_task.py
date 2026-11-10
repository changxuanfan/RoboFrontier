"""Explicit recovery of one Claude engineering task whose host closed while its world lived.

Default: read-only eligibility report. --execute seals the paused world if it is still
alive, validates the approximate pose restore on a private clone, ends any delegation
whose native setup never started, prepares the next segment in the same run and runs
the original frozen runner from the original source checkout. The same trial and the
same native sessions continue; no physical call is replayed, no delegate is reforked,
and the recovery is never repeated automatically (docs/running/claude-task-recovery.md).
"""
import argparse
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

from robofrontier.runtime import layout as run_layout, segments as run_segments
from robofrontier.engines.codex.recover_task import RecoveryBlocked, readonly, validate_physical_restore
from robofrontier.runtime.setup import verify_inputs, write_json
from robofrontier.runtime.store import RuntimeStore

# Host ends that leave a live world without a model host. Normal ends (finish, wall
# limit, STOP, budget close) and launch errors are never recovered here.
RECOVERABLE_REASONS = ('dispatch_paused', 'session_error', 'session_unknown')
REASON = 'manual recovery after the Claude host closed with its world paused'
FAILED_SETUP = ('Manual recovery: native delegate setup never started; its robots returned to the parent. '
                'No fork was repeated.')


def _ledger(db, interrupted=()):
    """The task's own calls and actions; the seal's observe/shutdown calls are not task calls.
    `interrupted`: unfinished calls/actions of a world that closed by itself, which the next
    segment settles as failed."""
    skip = set(interrupted)
    rows = [list(row) for row in db.execute("SELECT * FROM calls WHERE NOT (actor='Meta' AND id LIKE 'seal-%') ORDER BY id")
            if row[0] not in skip]
    actions = [list(row) for row in db.execute('SELECT * FROM actions ORDER BY id') if row[0] not in skip]
    return hashlib.sha256(json.dumps([rows, actions], sort_keys=True).encode()).hexdigest()


def _lock_free(path):
    if not path.exists(): return True
    with path.open('a+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return False
        fcntl.flock(lock, fcntl.LOCK_UN)
        return True


def _batch(run):
    folder = run.parent.parent
    batch = json.loads((folder/'batch.json').read_text())
    if batch.get('schema') != 'robofrontier.claude-draft.v1':
        raise RecoveryBlocked('Run is not part of a Claude engineering batch')
    jobs = [i for i, job in enumerate(batch['jobs']) if Path(job['run_directory']).resolve() == run]
    if len(jobs) != 1: raise RecoveryBlocked('Run is not uniquely listed in its batch')
    return folder, jobs[0]


def live_sessions(threads, processes=None):
    """Native CLI processes still naming one of these sessions (a live host must not be doubled)."""
    if processes is None:
        processes = subprocess.run(['ps', '-Ao', 'pid=,command='], capture_output=True, text=True, check=True).stdout
    found = []
    for line in processes.splitlines():
        if 'claude' not in line: continue
        if any(thread in line for thread in threads): found.append(line.split(None, 1)[0])
    return found


def unstarted_reviews(store):
    """Delegations held for review whose children never started: no gate opened, no call made."""
    from robofrontier.runtime.delegation import Delegations
    batches = []
    for batch in Delegations(store).batches().values():
        if batch['status'] != 'needs_review': continue
        actors = [child['actor'] for child in batch['children']]
        if any(child.get('start_status') != 'pending' or child.get('status') == 'active' for child in batch['children']):
            raise RecoveryBlocked('A delegation under review had started a child; review it by hand')
        marks = ','.join('?'*len(actors))
        if store.db.execute(f'SELECT 1 FROM calls WHERE actor IN ({marks}) LIMIT 1', actors).fetchone():
            raise RecoveryBlocked('A delegate under review made a call; review it by hand')
        batches.append(batch)
    return batches


def fail_unstarted_reviews(store):
    """End each never-started delegation under review as failed and return its robots.

    The same record `Delegations.fail_creating` leaves before a segment, for a batch whose
    native setup deadline passed. Its fork may exist on disk; it is kept and never resumed."""
    from robofrontier.runtime.delegation import Delegations
    delegations = Delegations(store); failed = []
    with store.transaction():
        batches = unstarted_reviews(store); owners = delegations.owners()
        for batch in batches:
            for child in batch['children']:
                child.update(status='finished', outcome='failed', start_status='not_started',
                             returned_at=time.time(), reason=FAILED_SETUP)
                for robot in child['robots']: owners[robot] = batch['parent']
                store.update_agent(child['actor'], delegation_state='finished', work_state='available',
                                   ready=False, next_check=None)
            batch.update(status='finished', outcome='failed', reason=FAILED_SETUP,
                         review_reason=batch.get('reason')); delegations.save(batch)
            event = {'event': 'delegation_failed', 'id': batch['id'],
                     'robots': [r for child in batch['children'] for r in child['robots']], 'reason': FAILED_SETUP}
            store.signal(batch['parent'], event); store.event('DELEGATION_FAILED', 'Meta', event)
            failed.append(batch['id'])
        store.put('robot_owners', owners)
    return failed


def inspect(run, source, *, processes=None, own=False, upgrade_from=None):
    """Read-only eligibility. `own`: the caller holds this run's recovery lock.

    `upgrade_from`: the checkout the run is frozen on, when `source` is a newer runtime it is
    to be upgraded to (runtime_upgrade). Only that explicit operator path continues a run that
    has already continued or was recovered before."""
    run, source = Path(run).resolve(), Path(source).resolve()
    frozen = Path(upgrade_from).resolve() if upgrade_from is not None else source
    folder, index = _batch(run)
    previous = run/'private/state/control/recovery.json'
    if previous.exists():
        record = json.loads(previous.read_text())
        # An attempt that stopped at a check before changing the run may be tried again;
        # one that prepared the segment, or is still running, never is.
        if not own and not _lock_free(previous.parent/'recovery.lock'):
            raise RecoveryBlocked('A recovery of this run is in progress')
        if record.get('prepared') and (upgrade_from is None or record.get('phase') not in ('closed', 'needs_review')):
            raise RecoveryBlocked('This run was already recovered once; never repeat it automatically')
    if run_layout.batch_path(folder, 'stop').exists() or run_layout.path(run, 'stop', 'claude').exists():
        raise RecoveryBlocked('Stop requested')
    job = json.loads(run_layout.batch_path(folder, 'engineering_status').read_text())['jobs'][index]
    if job.get('status') != 'needs_review' or job.get('reason') not in RECOVERABLE_REASONS:
        raise RecoveryBlocked('The batch has not handed this task back after a recoverable host end')
    status = json.loads(run_layout.path(run, 'engineering_status', 'claude').read_text())
    if status.get('status') != 'needs_review' or status.get('reason') not in RECOVERABLE_REASONS:
        raise RecoveryBlocked('The run did not end with a recoverable host end')
    if not _lock_free(run_layout.path(run, 'engineering_lock', 'claude')):
        raise RecoveryBlocked('The original Claude runner still holds this run')
    with readonly(run) as store:
        if store.get('integrity_valid') is not True: raise RecoveryBlocked('Run integrity is not valid')
        if store.get('segment', 0) >= run_segments.MAX_RETRIES and upgrade_from is None:
            raise RecoveryBlocked('Run already continued once')
        lifecycle, physics = store.get('lifecycle'), store.get('physics_state')
        if not store.get('dispatch_paused'): raise RecoveryBlocked('Dispatch is not paused')
        live = not run_segments.owner_released(run)
        if live and (lifecycle != 'running' or physics != 'running'):
            raise RecoveryBlocked('A live world must be running and paused')
        if not live and (lifecycle != 'interrupted' or physics != 'stopped'):
            raise RecoveryBlocked('A closed world must be sealed as interrupted')
        unsettled = sorted({row[0] for row in store.db.execute("SELECT id FROM calls WHERE status IN ('accepted','running','uncertain')")}
                           | {row[0] for row in store.db.execute("SELECT id FROM actions WHERE status NOT IN ('completed','failed')")})
        # A live world must settle everything before it is sealed. A world that closed by itself
        # (its host was lost) leaves its unfinished actions to the next segment, which fails them
        # without replay (run_segments.prepare_retry).
        if live and unsettled:
            raise RecoveryBlocked('An original call or physical action is unsettled; never redispatch it')
        delegations = store.get('delegations', {}) or {}
        if any(b['status'] == 'creating' for b in delegations.values()):
            raise RecoveryBlocked('A delegation is still being created')
        reviews = [b['id'] for b in unstarted_reviews(store)]
        threads = sorted({json.loads(value)['thread_id'] for (value,) in store.db.execute('SELECT value FROM agents')
                          if json.loads(value).get('thread_id')})
        hosts = live_sessions(threads, processes)
        if hosts: raise RecoveryBlocked('A native session of this run is still live: pid '+', '.join(hosts))
        if store.get('start_at') is None: raise RecoveryBlocked('Run never started')
        remaining = run_segments.remaining_s(run, store)
        if remaining < run_segments.MIN_REMAINING_S: raise RecoveryBlocked('Less than a minute of trial time is left')
        _, frame, sim_s, pose = run_segments._last_frame(run, store.get('segment', 0))
        holds = store.get('arm_holds') or {}
        if any(not 0 <= sim_s-hold.get('sim_s', -1e9) <= run_segments.HOLD_MAX_AGE_S for hold in holds.values()):
            raise RecoveryBlocked('A recorded grasp is too old to restore safely')
        changed = verify_inputs(run, source_root=frozen)
        if changed: raise RecoveryBlocked('Frozen inputs changed: '+', '.join(changed[:3]))
        return {'run': str(run), 'batch': str(folder), 'job_reason': job['reason'], 'world_live': live,
                'frozen_source': str(frozen), 'source': str(source),
                'segment': store.get('segment', 0)+1, 'frame': frame, 'sim_s': sim_s,
                'pose_sha256': hashlib.sha256(pose.tobytes()).hexdigest(), 'held_arms': sorted(holds),
                'ledger_sha256': _ledger(store.db, unsettled), 'role_threads': threads, 'failed_setups': reviews,
                'interrupted': [] if live else unsettled,
                'remaining_s': remaining, 'robot_owners': store.get('robot_owners'),
                'restore': 'Approximate: last recorded qpos, zero velocity, recent completed grasp holds'}


RUNNER = """import json, os, platform, sys
from pathlib import Path
source, batch, run = map(Path, sys.argv[1:4]); sys.path.insert(0, str(source))
from robofrontier.batch.prepare import load_env
from robofrontier.cli import _frozen_configuration
from robofrontier.configuration import rendering_environment
from robofrontier.runtime.diagnostics import require_runtime
from robofrontier.engines.claude.run import run_engineering
load_env(source/'.env')
config = _frozen_configuration(batch); require_runtime(config)
environment = rendering_environment(config['render']['device'], platform.system(), os.environ)
os.environ.clear(); os.environ.update(environment)
result = run_engineering(run, dict(os.environ), wall_limit_s=config['batch']['task_wall_limit_s'],
                         startup_timeout_s=config['batch']['startup_timeout_s'])
print(json.dumps(result, default=str))
"""


def execute(run, source, python, scratch, *, seal=None, launcher=subprocess.Popen, upgrade_from=None, reason=None):
    run, source, python = Path(run).resolve(), Path(source).resolve(), Path(python).absolute()
    if upgrade_from is not None:
        if not isinstance(reason, str) or not reason.strip(): raise RecoveryBlocked('A runtime upgrade needs a stated reason')
        # The upgrade grants policy read access to this interpreter's environment, which must be
        # the one the continued runner uses.
        if Path(sys.prefix).absolute() != python.parent.parent:
            raise RecoveryBlocked('Run the upgrade with the interpreter given as --python')
    from robofrontier.runtime.access import mode
    scratch = Path(scratch).resolve(); info = scratch.stat()
    access = json.loads((run/'private/inputs/policy-access.json').read_text())
    if (not scratch.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077
            or mode(access['filesystem'], scratch) != 'deny'):
        raise RecoveryBlocked('Recovery scratch must be private and denied by the frozen policy')
    control = run/'private/state/control'; control.mkdir(parents=True, exist_ok=True)
    with (control/'recovery.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = inspect(run, source, own=True, upgrade_from=upgrade_from)  # this process now holds the recovery lock
        status_path = control/'recovery.json'
        earlier = [json.loads(status_path.read_text())] if status_path.exists() else []
        earlier = (earlier[0].pop('earlier_attempts', []) + earlier) if earlier else []
        record = {**plan, 'earlier_attempts': earlier, 'schema': 'robofrontier.claude-task-recovery.v1', 'phase': 'sealing' if plan['world_live'] else 'validating',
                  'pid': os.getpid(), 'at': time.time()}
        write_json(status_path, record)
        try:
            sealed_report = run_segments.output_dir(run, plan['segment']-1)/'seal.json'
            if not plan['world_live'] and not sealed_report.exists():
                # The world closed by itself before its seal finished: record that seal now (no
                # world is started and nothing is replayed; run_seal.seal_run on a free lock).
                if seal is None: from robofrontier.runtime.seal import seal_run as seal
                store = RuntimeStore(run/'private/state/runtime.sqlite')
                try: record['seal'] = seal(store, 0)
                finally: store.close()
                again = inspect(run, source, own=True, upgrade_from=upgrade_from)
                if again['ledger_sha256'] != plan['ledger_sha256'] or again['interrupted'] != plan['interrupted']:
                    raise RecoveryBlocked('Call ledger changed while sealing the closed world')
            if plan['world_live']:
                # The paused world is closed by its own shutdown; never killed, never replayed.
                if seal is None: from robofrontier.runtime.seal import seal_run as seal
                store = RuntimeStore(run/'private/state/runtime.sqlite')
                try: record['seal'] = seal(store, 60)
                finally: store.close()
                if not run_segments.owner_released(run): raise RecoveryBlocked('The world did not release its lock')
                sealed = inspect(run, source, own=True, upgrade_from=upgrade_from)
                if sealed['ledger_sha256'] != plan['ledger_sha256']: raise RecoveryBlocked('Call ledger changed while sealing')
                plan = {**sealed, 'world_live': True}
                record.update(plan, phase='validating', earlier_attempts=earlier); write_json(status_path, record)
            record['physical_check'] = validate_physical_restore(run, source, python, scratch, plan)
            again = inspect(run, source, own=True, upgrade_from=upgrade_from)
            if {k: v for k, v in again.items() if k != 'world_live'} != {k: v for k, v in plan.items() if k != 'world_live'}:
                raise RecoveryBlocked('Task changed during validation')
            backup = scratch/('runtime-before-segment-%d-%d.sqlite' % (plan['segment'], time.time_ns()//1000000))
            backup.touch(mode=0o600, exist_ok=False)
            with readonly(run) as old, sqlite3.connect(backup) as destination: old.db.backup(destination)
            record['backup'] = str(backup)
            store = RuntimeStore(run/'private/state/runtime.sqlite')
            try:
                record['prepared'] = True; write_json(status_path, record)
                authorization = None
                if upgrade_from is not None:
                    from robofrontier.runtime import upgrade as runtime_upgrade
                    authorization = runtime_upgrade.upgrade(run, store, previous_source=Path(upgrade_from).resolve(),
                                                            reason=reason, expected_segment=plan['segment']-1,
                                                            expected_ledger=runtime_upgrade.ledger(store), source=source)
                    record['authorization'] = authorization; write_json(status_path, record)
                store.event('MANUAL_TASK_RECOVERY', 'Meta', {'reason': reason or REASON, 'engine': 'claude',
                                                            'authorization': authorization,
                                                            'plan': {k: plan[k] for k in ('segment', 'frame', 'sim_s', 'pose_sha256',
                                                                                          'failed_setups', 'remaining_s', 'role_threads')}})
                record['failed_setups'] = fail_unstarted_reviews(store)
                run_segments.prepare_retry(run, store, reason or REASON, sealed_host_failure=True, source_root=source,
                                           manual_authorization=authorization)
                if _ledger(store.db, plan['interrupted']) != plan['ledger_sha256']:
                    raise RecoveryBlocked('Original call ledger changed during preparation')
                record['robot_owners'] = store.get('robot_owners')
            finally: store.close()
            record['phase'] = 'host_started'; write_json(status_path, record)
            log_path = run/'private/logs/recovery-runner.log'
            with log_path.open('a') as log:
                # The frozen runner and physics from the run's checkout (the upgraded one after an upgrade).
                host = launcher([str(python), '-I', '-c', RUNNER, str(source), plan['batch'], str(run)],
                                cwd=source, stdout=log, stderr=log, stdin=subprocess.DEVNULL)
                record['host_pid'] = host.pid; write_json(status_path, record)
                code = host.wait()
            with readonly(run) as final:
                resumed = any(s.get('index') == plan['segment'] for s in (final.get('segments') or []))
                lifecycle = final.get('lifecycle')
            result = json.loads(run_layout.path(run, 'engineering_status', 'claude').read_text())
            complete = code == 0 and resumed and result.get('status') == 'finished' and run_segments.owner_released(run)
            record.update(phase='closed' if complete else 'needs_review', host_exit_code=code, segment_started=resumed,
                          lifecycle=lifecycle, result_status=result.get('status'), result_reason=result.get('reason'),
                          finished_at=time.time())
            write_json(status_path, record)
            return record
        except BaseException as error:
            record.update(phase='needs_review', error=str(error)[:1000], finished_at=time.time())
            write_json(status_path, record)
            raise


def wait_for_recoveries(jobs, sleep=time.sleep):
    """Keep a batch from closing (and collecting) while one of its tasks is being recovered."""
    for job in jobs:
        path = Path(job['run_directory'])/'private/state/control/recovery.json'
        while path.exists():
            if _lock_free(path.parent/'recovery.lock') and run_segments.owner_released(job['run_directory']): break
            sleep(1)
        if path.exists():
            record = json.loads(path.read_text())
            job['recovery'] = {k: record.get(k) for k in ('phase', 'segment', 'host_exit_code', 'result_reason')}
            job['status'] = 'closed' if record.get('phase') == 'closed' else 'needs_review'


def submit_durable(args):
    """Run this same recovery as a one-shot macOS launchd job with Interactive priority, so it
    outlives the terminal or agent session that started it (robofrontier.batch.mac)."""
    from robofrontier.batch import mac as durable
    run = Path(args.run_dir).resolve()
    # Absolute paths: the job starts in this checkout, not in the caller's directory.
    argv = ['--run-dir', run, '--source-root', Path(args.source_root).resolve(), '--python', Path(args.python).absolute(),
            '--scratch', Path(args.scratch).resolve(), '--execute']
    if args.upgrade_from is not None: argv += ['--upgrade-from', Path(args.upgrade_from).resolve(), '--reason', args.reason]
    tag = hashlib.sha256(str(run).encode()).hexdigest()[:16]
    stamp = time.strftime('%Y%m%dT%H%M%S')
    folder = run/'private/state/control'/('recovery-durable-'+stamp)
    command = [str(Path(sys.executable).absolute()), '-m', 'robofrontier.engines.claude.recover_task', *argv, '--foreground']
    plist = durable.job('org.robofrontier.recovery.%s.%s' % (tag, stamp), command, folder,
                        Path(__file__).resolve().parents[3], durable.passed_environment())
    return durable.bootstrap(plist, folder, {'run': str(run), 'recovery': True})


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--scratch', type=Path)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--upgrade-from', type=Path, help='The checkout the run is frozen on, to upgrade it to --source-root')
    parser.add_argument('--reason', help='Why the runtime is upgraded (required with --upgrade-from)')
    parser.add_argument('--foreground', action='store_true',
                        help='On macOS, run --execute in this process instead of a launchd job (the default)')
    args = parser.parse_args(argv)
    try:
        if args.execute and sys.platform == 'darwin' and not args.foreground:
            if not args.scratch: parser.error('--execute requires --scratch')
            inspect(args.run_dir, args.source_root, upgrade_from=args.upgrade_from)  # refuse before submitting
            if args.upgrade_from is not None and not (args.reason or '').strip(): parser.error('--upgrade-from requires --reason')
            print(json.dumps({'eligible': True, 'submitted': submit_durable(args)}, default=str))
            return
        if args.execute:
            if not args.scratch: parser.error('--execute requires --scratch')
            result = execute(args.run_dir, args.source_root, args.python, args.scratch,
                             upgrade_from=args.upgrade_from, reason=args.reason)
        else: result = inspect(args.run_dir, args.source_root, upgrade_from=args.upgrade_from)
        print(json.dumps({'eligible': True, **result}, default=str))
        if args.execute and result['phase'] != 'closed': raise SystemExit(1)
    except (RecoveryBlocked, OSError, ValueError) as error:
        print(json.dumps({'eligible': False, 'reason': str(error), 'automatic_redispatch': False}))
        raise SystemExit(2)


if __name__ == '__main__': main()
