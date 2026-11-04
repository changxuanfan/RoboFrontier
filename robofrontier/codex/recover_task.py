"""Explicit recovery of one closed task through its original job gateway.

Default: read-only eligibility report. --execute validates an approximate physical
restore on a private clone, then continues the original ledger and native threads.
An old gateway, unsettled action, live owner or uncertain admission fails closed.
No engine restart, token copy, automatic retry or physical call replay is allowed.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time

from robofrontier import run_segments
from robofrontier.codex.job_engine import task_id
from robofrontier.run_layout import path as run_path, batch_path
from robofrontier.run_setup import write_json
from robofrontier.runtime_store import RuntimeStore


class RecoveryBlocked(ValueError):
    pass


@contextmanager
def readonly(run):
    db = sqlite3.connect((Path(run)/'private/state/runtime.sqlite').as_uri()+'?mode=ro', uri=True)
    db.execute('PRAGMA query_only=ON')
    class Store:
        def get(self, key, default=None):
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
            return json.loads(row[0]) if row else default
    store = Store(); store.db = db
    try: yield store
    finally: db.close()


def gateway_call(endpoint, method, params=None):
    """Unbound control query: never bind or redispatch a task as a probe."""
    with socket.socket(socket.AF_UNIX) as channel:
        channel.settimeout(10); channel.connect(endpoint)
        channel.sendall((json.dumps({'id': 1, 'method': method, 'params': params or {}})+'\n').encode())
        data = b''
        while b'\n' not in data:
            block = channel.recv(65536)
            if not block or len(data)+len(block) > 1048576:
                raise RecoveryBlocked('Gateway capability acknowledgement unavailable')
            data += block
        value = json.loads(data.split(b'\n', 1)[0])
        if 'error' in value:
            raise RecoveryBlocked('Running gateway does not support safe single-task recovery; no task was rebound')
        return value['result']


def _ledger(db):
    rows = [list(row) for row in db.execute('SELECT * FROM calls ORDER BY id')]
    actions = [list(row) for row in db.execute('SELECT * FROM actions ORDER BY id')]
    return hashlib.sha256(json.dumps([rows, actions], sort_keys=True).encode()).hexdigest()


def inspect(run, manifest, source):
    run, source = Path(run).resolve(), Path(source).resolve()
    identity = task_id(run)
    tasks = [t for t in manifest['tasks'] if t['id'] == identity and t['run'] == str(run)]
    if len(tasks) != 1: raise RecoveryBlocked('Run is not uniquely owned by this job gateway')
    batch = run.parent.parent
    if (batch/'batch.json').exists() and batch_path(batch, 'stop').exists():
        raise RecoveryBlocked('Batch stop requested')
    with readonly(run) as store:
        if (store.get('lifecycle') != 'interrupted' or store.get('physics_state') != 'stopped'
                or not store.get('dispatch_paused') or store.get('integrity_valid') is not True):
            raise RecoveryBlocked('Only a stopped, interrupted, integrity-valid task can recover')
        if store.db.execute("SELECT 1 FROM calls WHERE status IN ('accepted','running','uncertain') LIMIT 1").fetchone():
            raise RecoveryBlocked('An original call is unsettled; never redispatch it')
        if store.db.execute("SELECT 1 FROM actions WHERE status NOT IN ('completed','failed') LIMIT 1").fetchone():
            raise RecoveryBlocked('An original physical action is unsettled')
        seal = json.loads((run_segments.output_dir(run, store.get('segment', 0))/'seal.json').read_text())
        if not seal.get('sealed') or not seal.get('fresh_observation') or seal.get('unresolved_action_ids') or seal.get('capture_error') or seal.get('shutdown_error'):
            raise RecoveryBlocked('The original world did not seal cleanly')
        events = [json.loads(line) for line in run_path(run, 'host_log', 'codex').read_text().splitlines() if line.strip()]
        if not any(e.get('event') == 'model_host_exited' and e.get('signal') == 'gateway-lost' for e in events):
            raise RecoveryBlocked('No recorded task-channel loss; this manual exception is not applicable')
        host = json.loads(run_path(run, 'host_process', 'codex').read_text())
        try: os.kill(int(host['pid']), 0)
        except ProcessLookupError: pass
        else: raise RecoveryBlocked('Original host PID is still alive or has been reused')
        ok, reason = run_segments.retry_eligibility(run, store, sealed_host_failure=True, source_root=source)
        if not ok: raise RecoveryBlocked(reason)
        _, frame, sim_s, pose = run_segments._last_frame(run, store.get('segment', 0))
        holds = store.get('arm_holds') or {}
        if any(not 0 <= sim_s-hold.get('sim_s', -1e9) <= run_segments.HOLD_MAX_AGE_S for hold in holds.values()):
            raise RecoveryBlocked('A recorded grasp is too old to restore safely')
        config = json.loads((run/'private/inputs/task.json').read_text())
        used = run_segments.last_activity(run, store)-store.get('start_at')-store.get('downtime_s', 0.)
        threads = sorted({json.loads(value)['thread_id'] for (value,) in store.db.execute('SELECT value FROM agents')
                          if json.loads(value).get('thread_id')})
        record = {'run': str(run), 'task_id': identity, 'segment': store.get('segment', 0)+1,
                  'frame': frame, 'sim_s': sim_s, 'pose_sha256': hashlib.sha256(pose.tobytes()).hexdigest(),
                  'held_arms': sorted(holds), 'ledger_sha256': _ledger(store.db), 'role_threads': threads,
                  'remaining_s': config['run_protocol']['total_wall_limit_s']-used,
                  'restore': 'Approximate: last recorded qpos, zero velocity, recent completed grasp holds'}
    # Capability is checked before any run mutation or native session operation.
    capability = gateway_call(manifest['endpoint'], 'gateway/capabilities')
    if capability.get('singleTaskRecovery') != 1:
        raise RecoveryBlocked('Running gateway lacks single-task recovery admission')
    host_rpc = Path(__file__).with_name('gateway_rpc.js')
    if hashlib.sha256(host_rpc.read_bytes()).digest() != hashlib.sha256((source/'robofrontier/codex/gateway_rpc.js').read_bytes()).digest():
        raise RecoveryBlocked('Frozen policy host lacks the qualified recovery handshake')
    state = gateway_call(manifest['endpoint'], 'gateway/recovery/status', {'taskId': identity})
    if state['state'] != 'closed' or state['pendingTools'] or state['inflight'] or state['recoveryUsed']:
        raise RecoveryBlocked('Original gateway task has not handed back all ownership')
    if not set(threads) <= set(state['threads']): raise RecoveryBlocked('Original role ownership is incomplete')
    record['threads'] = state['threads']
    return record


def validate_physical_restore(run, source, python, scratch, record):
    """Construct only a private clone. No model, action, mj_step or original output write."""
    import numpy as np
    with tempfile.TemporaryDirectory(prefix='restore-check-', dir=scratch) as temporary:
        clone = Path(temporary)
        shutil.copytree(Path(run)/'private/inputs', clone/'private/inputs', ignore=shutil.ignore_patterns('frozen-source'))
        with readonly(run) as store:
            _, _, _, pose = run_segments._last_frame(run, store.get('segment', 0))
            holds = store.get('arm_holds') or {}
        folder = run_segments.input_dir(clone, record['segment']); folder.mkdir(parents=True)
        np.save(folder/'restore-pose.npy', pose, allow_pickle=False)
        task = json.loads((clone/'private/inputs/task.json').read_text())
        note = {'schema': run_segments.RESTORE_SCHEMA, 'segment': record['segment'], 'case_id': task['id'],
                'source_scene_sha256': task['scene_sha256'], 'source_sim_s': record['sim_s'], 'held_grasps': holds}
        write_json(folder/'restore-pose.json', note)
        file = clone/'private/inputs/manifest.json'; manifest = json.loads(file.read_text())
        for path in folder.iterdir(): manifest['input_sha256'][str(path.relative_to(clone))] = hashlib.sha256(path.read_bytes()).hexdigest()
        write_json(file, manifest)
        code = """import sys,json,numpy as np
sys.path.insert(0,sys.argv[1])
from robofrontier.pipeline import World
from robofrontier.run_segments import current_restore
from pathlib import Path
run=Path(sys.argv[2]); task=json.loads((run/'private/inputs/task.json').read_text())
world=World(run,task); note,pose=current_restore(run)
assert np.array_equal(world.data.qpos,np.load(pose,allow_pickle=False))
assert np.count_nonzero(world.data.qvel)==0 and world.time==note['source_sim_s']
assert sorted(getattr(world,'restored_holds',[]))==sorted(note['held_grasps'])
print(json.dumps({'verified':True,'physics_steps':0,'held_arms':sorted(note['held_grasps'])}))
"""
        checked = subprocess.run([str(python), '-I', '-c', code, str(source), str(clone)], capture_output=True, text=True, timeout=120)
        if checked.returncode: raise RecoveryBlocked('Physical restore validation failed on the private clone: '+checked.stderr[-1500:])
        return json.loads(checked.stdout.splitlines()[-1])


def execute(run, manifest, source, python, scratch, *, allocation_end):
    run = Path(run).resolve()
    source, python = Path(source).resolve(), Path(python).absolute()
    from robofrontier.policy_access import mode
    scratch = Path(scratch).resolve()
    info = scratch.stat()
    access = json.loads((run/'private/inputs/policy-access.json').read_text())
    if (not scratch.is_dir() or info.st_uid != os.getuid() or info.st_mode & 0o077
            or mode(access['filesystem'], scratch) != 'deny'):
        raise RecoveryBlocked('Recovery scratch must be private and denied by the frozen policy')
    if not math.isfinite(allocation_end): raise RecoveryBlocked('Allocation end must be finite')
    lock_path = run/'private/state/control/recovery.lock'
    with lock_path.open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        plan = inspect(run, manifest, source)
        if time.time()+plan['remaining_s']+180 >= allocation_end:
            raise RecoveryBlocked('Allocation has insufficient time for the remaining trial and safe closure')
        physical = validate_physical_restore(run, source, python, scratch, plan)
        if inspect(run, manifest, source) != plan: raise RecoveryBlocked('Task changed during validation')
        if time.time()+plan['remaining_s']+180 >= allocation_end:
            raise RecoveryBlocked('Allocation became too short during validation')
        status_path = run/'private/state/control/recovery.json'
        record = {**plan, 'phase': 'preparing', 'pid': os.getpid(), 'at': time.time(), 'physical_check': physical}
        write_json(status_path, record)
        # Original ledger is backed up first; no completed call is changed.
        backup = Path(scratch)/('runtime-before-'+plan['task_id']+'.sqlite')
        backup.touch(mode=0o600, exist_ok=False)
        with readonly(run) as old, sqlite3.connect(backup) as destination: old.db.backup(destination)
        nonce = secrets.token_hex(32)
        try:
            store = RuntimeStore(run/'private/state/runtime.sqlite')
            try:
                store.event('MANUAL_TASK_RECOVERY', 'Meta', {'reason': 'sealed after task-channel loss', 'plan': plan})
                run_segments.prepare_retry(run, store, 'manual recovery after closed task channel',
                                           sealed_host_failure=True, source_root=source)
                if _ledger(store.db) != plan['ledger_sha256']: raise RecoveryBlocked('Original call ledger changed during preparation')
            finally: store.close()
            grant = Path(manifest['recovery_directory'])/(plan['task_id']+'.json')
            if grant.exists() or grant.with_suffix('.json.consumed').exists(): raise RecoveryBlocked('A recovery grant was already issued')
            write_json(grant, {'schema': 'robofrontier.task-recovery-grant.v1', 'taskId': plan['task_id'],
                              'run': str(run), 'threads': plan['threads'], 'nonce': nonce, 'expiresAt': time.time()+240})
            env = dict(os.environ, ROBOFRONTIER_CODEX_GATEWAY=manifest['endpoint'],
                       ROBOFRONTIER_CODEX_TASK=plan['task_id'], ROBOFRONTIER_CODEX_RECOVERY_NONCE=nonce)
            # The original immutable host, physics and file worker stay in use.
            with run_path(run, 'supervisor_log', 'codex').open('a') as log:
                host = subprocess.Popen(['node', str(Path(source)/'robofrontier/codex/codex_policy_host.js'),
                                         str(run), str(source), str(python)], cwd=source, env=env, stdout=log, stderr=log)
                write_json(run_path(run, 'host_process', 'codex'), {'pid': host.pid, 'started_at': time.time()})
                record.update(phase='host_started', host_pid=host.pid); write_json(status_path, record)
                result = host.wait()
            with readonly(run) as final:
                resumed = any(s['index'] == plan['segment'] for s in (final.get('segments') or []))
                ended = final.get('lifecycle') == 'ended'
            complete = result == 0 and resumed and ended and run_segments.owner_released(run)
            record.update(phase='closed' if complete else 'needs_review', segment_started=resumed,
                          host_exit_code=result, finished_at=time.time())
            write_json(status_path, record)
            return record
        except BaseException:
            record.update(phase='needs_review', finished_at=time.time()); write_json(status_path, record)
            raise


def wait_for_recoveries(jobs):
    """Keep the original supervisor/engine alive until authorized recovery hosts finish."""
    for job in jobs:
        path = Path(job['run_directory'])/'private/state/control/recovery.json'
        while path.exists():
            record = json.loads(path.read_text())
            with (path.parent/'recovery.lock').open('r') as lock:
                try:
                    fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
                    supervising = False
                except BlockingIOError: supervising = True
            # Even a lost recovery supervisor can leave its host/world alive.
            # Wait for that original owner; never restart it or close its gateway.
            if not supervising and run_segments.owner_released(job['run_directory']): break
            time.sleep(1)
        if path.exists():
            record = json.loads(path.read_text())
            job['recovery'] = record
            job['status'] = 'closed' if record['phase'] == 'closed' else 'needs_review'
            if record['phase'] == 'closed':
                job.setdefault('original_host_exit_code', job.get('host_exit_code'))
                job['host_exit_code'] = record['host_exit_code']


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--engine-manifest', type=Path, required=True)
    parser.add_argument('--source-root', type=Path, required=True)
    parser.add_argument('--python', type=Path, default=Path(sys.executable))
    parser.add_argument('--scratch', type=Path)
    parser.add_argument('--allocation-end', type=float)
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(); manifest = json.loads(args.engine_manifest.read_text())
    try:
        if args.execute:
            if not args.scratch or not args.allocation_end: parser.error('--execute requires --scratch and --allocation-end')
            result = execute(args.run_dir, manifest, args.source_root, args.python, args.scratch, allocation_end=args.allocation_end)
        else: result = inspect(args.run_dir, manifest, args.source_root)
        print(json.dumps({'eligible': True, **result}))
        if args.execute and result['phase'] != 'closed': raise SystemExit(1)
    except (RecoveryBlocked, OSError, ValueError) as error:
        print(json.dumps({'eligible': False, 'reason': str(error), 'automatic_redispatch': False}))
        raise SystemExit(2)


if __name__ == '__main__': main()
