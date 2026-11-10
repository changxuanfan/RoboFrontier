"""Parallel, isolated nominal goal endpoint screens for Mosaic planning.

Workers never access the live MjData or issue actions. Each reconstructs its
own model and robot IK from an immutable trial scene and captured references.
The owner retains responsibility for all physical and collision checks.
"""
import multiprocessing
import os
import time

import mujoco
import numpy as np

from ..physics.robot_control import PandaArm, rotation_vector
from ..runtime.setup import write_json
from . import placement as placement_oracle


_scratch = None
_init_error = None


class _Scratch:
    def screen_ik(self, robot, target, rotation, seed=None):
        arm = self.arms[robot]
        q, error = arm.ik.solve(np.asarray(target), rotation,
                                arm.qref if seed is None else seed, 220)
        _, reached = arm.ik.pose(q)
        return q if error < .0018 and np.linalg.norm(rotation_vector(rotation, reached)) < .02 else None


def _initialize(scene, task, refs, env=None, qpos=None, home=None):
    global _scratch, _init_error
    _scratch = None
    _init_error = None
    try:
        _scratch = _build_scratch(scene, task, refs, env, qpos, home)
    except Exception as error:
        # Pool otherwise repeatedly respawns a failing initializer forever.
        # Report the failure through the first submitted work item instead.
        _init_error = f'{type(error).__name__}: {error}'


def _build_scratch(scene, task, refs, env=None, qpos=None, home=None):
    scratch = _Scratch()
    scratch.task = task
    scratch.model = mujoco.MjModel.from_xml_path(scene)
    scratch.data = mujoco.MjData(scratch.model)
    mujoco.mj_resetDataKeyframe(scratch.model, scratch.data, scratch.model.key('initial').id)
    if qpos is not None:
        scratch.data.qpos[:] = qpos
    mujoco.mj_forward(scratch.model, scratch.data)
    scratch.arms = {name: PandaArm(scratch.model, scratch.data, name) for name in refs}
    for name, reference in refs.items():
        scratch.arms[name].qref = np.asarray(reference, dtype=float)
    scratch.env = env
    scratch.home_q = {name: np.asarray(q, dtype=float) for name, q in (home or {}).items()}
    return scratch


def _require_scratch():
    if _init_error is not None:
        raise RuntimeError('Mosaic planning worker initialization failed: '+_init_error)
    if _scratch is None:
        raise RuntimeError('Mosaic planning worker has not initialized')


def _screen(goal):
    _require_scratch()
    original = _scratch.task
    _scratch.task = dict(original, goals=[goal])
    try:
        try:
            result = placement_oracle.goal_coverage(_scratch)[goal['goal_id']]
        except RuntimeError as error:
            if not str(error).startswith('No candidate goal approach/seat/withdraw endpoints '):
                raise
            result = None
        return goal['goal_id'], result
    finally:
        _scratch.task = original


def _screen_pickup(item):
    _require_scratch()
    from .mosaic import pickup_endpoint_candidates
    original = _scratch.env
    _scratch.env = dict(original, objects=[item])
    try:
        return item['id'], pickup_endpoint_candidates(_scratch)[item['id']]
    finally:
        _scratch.env = original


def _parallel_map(trial, workers, items, fn, phase):
    count = min(len(items), os.cpu_count() or 1) if workers == 0 else min(len(items), workers)
    if count < 1:
        raise ValueError('Planning workers must be nonnegative and goals must be present')
    refs = {name: arm.qref.tolist() for name, arm in trial.arms.items()}
    started = time.monotonic()
    last_progress = started
    last_item = None
    results = {}
    path = trial.directory / 'planning-status.json'
    def publish(state, error=None):
        write_json(path, dict(phase=phase, state=state, completed=len(results), total=len(items),
            workers=count, updated_at_unix_s=time.time(), elapsed_s=time.monotonic()-started,
            seconds_since_progress=time.monotonic()-last_progress, last_completed_item=last_item,
            error=error))
        trial._heartbeat('planning_'+phase)
    publish('running')
    pool = multiprocessing.get_context('spawn').Pool(count, initializer=_initialize,
        initargs=(str(trial.directory/'scene.xml'), trial.task, refs,
                  trial.env, trial.data.qpos.copy(),
                  {name: q.tolist() for name, q in trial.home_q.items()}))
    worker_pids = {worker.pid for worker in pool._pool}
    try:
        pending = pool.imap_unordered(fn, items, chunksize=1)
        while len(results) < len(items):
            trial.check_stop()
            try:
                name, options = pending.next(timeout=1.)
                results[name] = options
                last_progress = time.monotonic()
                last_item = name
            except multiprocessing.TimeoutError:
                pass
            # multiprocessing.Pool silently replaces a crashed process but
            # can lose its in-flight item forever.  No workers are configured
            # to retire normally; a changed PID is therefore a failure.
            if {worker.pid for worker in pool._pool} != worker_pids:
                raise RuntimeError('Mosaic planning worker exited unexpectedly; inspect worker logs')
            publish('running')
        pool.close()
        pool.join()
    except BaseException as error:
        pool.terminate()
        pool.join()
        publish('interrupted',f'{type(error).__name__}: {error}')
        raise
    publish('complete')
    return results


def nominal_goal_coverage(trial, workers):
    """Return nominal candidates or None when original fallback is needed."""
    goals = trial.task['goals']
    results = _parallel_map(trial, workers, goals, _screen, 'goal_endpoints')
    if any(results[g['goal_id']] is None for g in goals):
        return None
    return {g['goal_id']: results[g['goal_id']] for g in goals}


def pickup_coverage(trial, workers):
    """Return the same finite pickup endpoint map using isolated snapshots."""
    objects = trial.env['objects']
    results = _parallel_map(trial, workers, objects, _screen_pickup, 'pickup_endpoints')
    return {item['id']: results[item['id']] for item in objects}
