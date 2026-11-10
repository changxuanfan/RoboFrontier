"""What the manual task recoveries of both engines share (engines/claude/recover_task.py,
engines/codex/recover_task.py): a read-only view of the runtime database, the call ledger a
recovery must leave unchanged, a physical-restore check on a private clone, and the batch's
wait for a recovery in progress."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time

from robofrontier.runtime import segments as run_segments
from robofrontier.runtime.setup import write_json


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


def ledger(db, interrupted=()):
    """The task's own calls and actions; the seal's observe/shutdown calls are not task calls.
    `interrupted`: unfinished calls/actions of a world that closed by itself, which the next
    segment settles as failed."""
    skip = set(interrupted)
    rows = [list(row) for row in db.execute("SELECT * FROM calls WHERE NOT (actor='Meta' AND id LIKE 'seal-%') ORDER BY id")
            if row[0] not in skip]
    actions = [list(row) for row in db.execute('SELECT * FROM actions ORDER BY id') if row[0] not in skip]
    return hashlib.sha256(json.dumps([rows, actions], sort_keys=True).encode()).hexdigest()


def lock_free(path):
    if not path.exists(): return True
    with path.open('a+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return False
        fcntl.flock(lock, fcntl.LOCK_UN)
        return True


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
from robofrontier.runtime.pipeline import World
from robofrontier.runtime.segments import current_restore
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


def wait_for_recoveries(jobs, sleep=time.sleep):
    """Keep a batch from closing (and collecting) while one of its tasks is being recovered.

    Even a lost recovery supervisor can leave its host and world alive: wait for that owner
    too; never restart it."""
    for job in jobs:
        path = Path(job['run_directory'])/'private/state/control/recovery.json'
        while path.exists():
            if lock_free(path.parent/'recovery.lock') and run_segments.owner_released(job['run_directory']): break
            sleep(1)
        if path.exists():
            record = json.loads(path.read_text())
            job['recovery'] = {k: record.get(k) for k in ('phase', 'segment', 'host_exit_code', 'result_reason')}
            job['status'] = 'closed' if record.get('phase') == 'closed' else 'needs_review'
            if record.get('phase') == 'closed' and 'host_exit_code' in record:
                job.setdefault('original_host_exit_code', job.get('host_exit_code'))
                job['host_exit_code'] = record['host_exit_code']
