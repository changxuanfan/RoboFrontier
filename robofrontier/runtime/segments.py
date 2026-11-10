"""One run, several segments: after an unexpected exit the same run continues once.

The continued segment is the same trial: same run directory, runtime database, workspace
and model sessions. Only the physical world is new, rebuilt from the last recorded
motion frame; the time the host was down does not count against the wall limit.
See docs/running/run-segments.md.
"""
import fcntl
import json
import time
from pathlib import Path

import numpy as np

from .layout import path as run_path
from .setup import verify_inputs, write_json

MAX_RETRIES = 1
MIN_REMAINING_S = 60.
RESTORE_SCHEMA = 'robofrontier.segment-restore.v1'
INTERRUPTED = ('Interrupted by an unexpected host exit; the world was restored from the last recorded pose. '
               'Not replayed.')
# A held grasp is restored only from a hold snapshot at most this much older than the frame.
HOLD_MAX_AGE_S = 5.


def supported(run):
    try:
        run_path(run, 'segment_outputs')
        return True
    except KeyError:
        return False


def output_dir(run, segment):
    """Process outputs of one segment; segment 0 keeps the original locations."""
    return Path(run) / 'private/outputs' if segment == 0 else run_path(run, 'segment_outputs') / str(segment)


def input_dir(run, segment):
    return run_path(run, 'segment_inputs') / str(segment)


def motion_dirs(run):
    """Every segment's motion recording, in order; their timelines are continuous."""
    folders = [Path(run) / 'private/outputs/motion']
    if supported(run) and run_path(run, 'segment_outputs').is_dir():
        numbers = sorted(int(p.name) for p in run_path(run, 'segment_outputs').iterdir() if p.name.isdigit())
        folders += [output_dir(run, k) / 'motion' for k in numbers]
    return [f for f in folders if (f / 'stream.json').is_file()]


def current_restore(run):
    """The restore record of the segment now being started, or None for segment 0."""
    if not supported(run) or not run_path(run, 'segment_inputs').is_dir(): return None
    numbers = sorted(int(p.name) for p in run_path(run, 'segment_inputs').iterdir() if p.name.isdigit())
    if not numbers: return None
    folder = input_dir(run, numbers[-1])
    note = json.loads((folder / 'restore-pose.json').read_text())
    if note.get('schema') != RESTORE_SCHEMA or note.get('segment') != numbers[-1]:
        raise ValueError('Invalid segment restore record')
    return note, folder / 'restore-pose.npy'


def restore_world(run, task, model, data):
    """Set a new world to the restore pose of the segment being started; None for segment 0.

    The pose must be bound to the manifest. Velocities are zeroed and the simulation
    clock continues from the recorded frame, so the trial timeline stays continuous.
    """
    found = current_restore(run)
    if found is None: return None
    note, pose_path = found
    import hashlib
    frozen = json.loads((Path(run) / 'private/inputs/manifest.json').read_text()).get('input_sha256', {})
    for path in (pose_path, pose_path.with_suffix('.json')):
        if frozen.get(str(path.relative_to(Path(run)))) != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Segment restore pose is not bound to the run manifest')
    if note['case_id'] != task['id'] or note['source_scene_sha256'] != task['scene_sha256']:
        raise ValueError('Segment restore pose belongs to another scene')
    pose = np.load(pose_path, allow_pickle=False)
    if pose.shape != (model.nq,) or not np.isfinite(pose).all(): raise ValueError('Segment restore pose invalid')
    data.qpos[:] = pose; data.qvel[:] = 0.; data.time = note['source_sim_s']
    return note


def deadline(store, wall_limit_s):
    """Wall-clock end of a START_wall_time trial: downtime between segments is not counted.

    An active_time_v1 trial has no wall-clock end; see used_s and remaining_s."""
    return store.get('start_at') + wall_limit_s + store.get('downtime_s', 0.)


def used_s(run, store, ended_at=None):
    """Seconds of the trial's limit used so far, by the clock its frozen protocol names.

    START_wall_time: wall time from START to `ended_at` (default: the last activity), less
    downtime. active_time_v1: the active running time the world saved (policy_probe.BudgetGuard)."""
    from .clock import WALL_CLOCK, run_clock
    task = json.loads((Path(run) / 'private/inputs/task.json').read_text())
    if run_clock(task['run_protocol']) != WALL_CLOCK: return float(store.get('active_s', 0.) or 0.)
    ended_at = last_activity(run, store) if ended_at is None else ended_at
    return ended_at - store.get('start_at') - store.get('downtime_s', 0.)


def remaining_s(run, store, ended_at=None):
    """Seconds of the trial's limit left (see used_s)."""
    task = json.loads((Path(run) / 'private/inputs/task.json').read_text())
    return task['run_protocol']['total_wall_limit_s'] - used_s(run, store, ended_at)


# Written after the segment had already ended; they do not show it was alive.
POSTMORTEM_EVENTS = ('RUN_INTERRUPTED', 'RUN_SEALED', 'RUN_SEAL_INCOMPLETE', 'DISPATCH_PAUSED',
                     'EXECUTION_RECOVERY_REQUIRED', 'INTERRUPTION_EVALUATION_UNAVAILABLE', 'HOST_LOST',
                     'ACTIONS_INTERRUPTED_BY_SEGMENT', 'DELEGATION_FAILED', 'SEGMENT_PREPARED', 'MANUAL_TASK_RECOVERY',
                     'RUNTIME_UPGRADE_AUTHORIZED')


def last_activity(run, store):
    """When the segment that just ended was last seen alive."""
    marks = ','.join('?' * len(POSTMORTEM_EVENTS))
    times = [store.db.execute('SELECT max(created) FROM events WHERE kind NOT IN (%s)' % marks,
                              POSTMORTEM_EVENTS).fetchone()[0] or 0.]
    try:
        host_log = run_path(run, 'host_log', store.get('config', {}).get('engine', 'codex'))
        with host_log.open('rb') as log:
            log.seek(0, 2); size = log.tell(); log.seek(max(0, size - 65536))
            for line in reversed(log.read().decode(errors='replace').splitlines()):
                try:
                    times.append(float(json.loads(line)['at'])); break
                except (ValueError, KeyError, TypeError):
                    continue
    except (OSError, KeyError):
        pass
    return max(times)


def owner_released(run):
    """True when no process holds this run's physical world."""
    try:
        with run_path(run, 'world_lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock, fcntl.LOCK_UN)
        return True
    except OSError:
        return False


def _last_frame(run, segment):
    from ..media.motion_recording import MotionReader
    folder = output_dir(run, segment) / 'motion'
    if not (folder / 'stream.json').is_file(): return None
    reader = MotionReader(folder)
    if not reader.meta.get('frames'): return None
    index, sim_s, pose = next(reader.selected_frames([reader.meta['frames'] - 1]))
    return reader, index, float(sim_s), pose


# Events that only a normal end writes: the trial was over, so it never continues.
NORMAL_END_EVENTS = ('POLICY_WALL_LIMIT', 'POLICY_BUDGET_CLOSED', 'TEAM_FINISH_PROPOSED')


BACKSTOP_REFUSAL = ('stopped by the 48 h wall-time backstop; continuing needs an explicit operator authorization '
                    '(runtime_upgrade)')


def wall_backstopped(run):
    """True when the run's last stop was the wall backstop (policy_probe.BudgetGuard): its
    budget-cutoff.json says so. Such a run needs review and its result is not counted."""
    try: return json.loads((Path(run) / 'private/outputs/budget-cutoff.json').read_text()).get('wall_backstop') is True
    except (OSError, ValueError, AttributeError): return False


def retry_eligibility(run, store, *, sealed_host_failure=False, source_root=None, manual_authorization=None):
    """(True, None) when this run may continue in a new segment, else (False, reason).

    Only a world that really died, with time left, continues: a finish, the wall limit,
    a budget close, STOP or a seal of a live world is a normal end. A preparation that
    stopped part way may be completed again (see prepare_retry). The explicit
    sealed_host_failure exception is reserved for the validated manual job-task
    recovery entrypoint; automatic continuation never enables it. source_root
    verifies the original immutable runtime rather than a development checkout."""
    run = Path(run)
    if not supported(run): return False, 'run layout has no segments'
    journal = store.get('segment_journal')
    if manual_authorization is not None:
        from .upgrade import validate_authorization
        try: validate_authorization(run, store, manual_authorization, source_root=source_root)
        except (ValueError, OSError, KeyError, TypeError) as error: return False, str(error)
    # A run stopped by the wall backstop continues only on an operator's explicit authorization;
    # the backstop's own stop (an ended world, sealed live) is then not a normal end.
    backstop = bool(store.get('wall_backstop'))
    if backstop and manual_authorization is None: return False, BACKSTOP_REFUSAL
    if store.get('segment', 0) >= MAX_RETRIES and not journal and manual_authorization is None:
        return False, 'already continued once'
    lifecycle = store.get('lifecycle')
    if lifecycle not in ('running', 'interrupted', 'recovery_required') and not (backstop and lifecycle == 'ended'):
        return False, 'run ended normally or never started (' + str(lifecycle) + ')'
    marks = ','.join('?' * (len(NORMAL_END_EVENTS) + 1))
    events = {kind for (kind,) in store.db.execute(
        'SELECT kind FROM events WHERE kind IN (%s)' % marks, ('INTEGRITY_ABORT',) + NORMAL_END_EVENTS)}
    if store.get('integrity_valid') is False or 'INTEGRITY_ABORT' in events: return False, 'integrity abort'
    if events & set(NORMAL_END_EVENTS): return False, 'run reached a normal end (' + ', '.join(sorted(events)) + ')'
    # A seal of a live world is a normal end (stop, finish, a model-side failure); a seal
    # made after the world had already died does not prevent continuing.
    segment = store.get('segment', 0)
    for (value,) in store.db.execute("SELECT value FROM events WHERE kind='RUN_SEALED'"):
        sealed = json.loads(value)
        report = sealed.get('report_ref') or ''
        if (not sealed_host_failure and not backstop and sealed.get('owner_was_live', True)
                and Path(report).resolve().parent == output_dir(run, segment).resolve()):
            return False, 'run was sealed with its world alive'
    if run_path(run, 'stop').exists(): return False, 'stop requested'
    # A preparation that stopped part way may have left its own restore files unverified.
    partial = 'input:'+input_dir(run, journal['segment']).relative_to(run).as_posix()+'/' if journal else None
    changed = [c for c in verify_inputs(run, source_root=source_root) if not (partial and c.startswith(partial))]
    if changed: return False, 'frozen inputs changed: ' + ', '.join(changed[:3])
    if not owner_released(run): return False, 'a process still owns the physical world'
    if store.get('start_at') is None: return False, 'never started'
    ended_at = journal['ended_at'] if journal else None
    if remaining_s(run, store, ended_at) < MIN_REMAINING_S: return False, 'less than %d s of the wall limit left' % MIN_REMAINING_S
    if _last_frame(run, segment) is None: return False, 'no recorded motion frame'
    return True, None


def _write_atomic(path, data):
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_bytes(data); temporary.replace(path)


def prepare_retry(run, store, reason, *, sealed_host_failure=False, source_root=None, manual_authorization=None):
    """Turn an unexpectedly ended run into one that continues in the next segment.

    `reason` names what ended the previous segment (for example the host exit code).
    The caller has already established that no host or world process is alive.
    Preparation follows a journal kept in the runtime database, so a preparation that
    stopped part way is completed by calling this again: it reuses the same segment,
    the same restore frame and end time, and uses no further continuation.
    """
    run = Path(run)
    ok, why = retry_eligibility(run, store, sealed_host_failure=sealed_host_failure, source_root=source_root,
                              manual_authorization=manual_authorization)
    if not ok: raise ValueError('Run cannot continue: ' + why)
    previous = store.get('segment', 0)
    journal = store.get('segment_journal')
    if not journal or journal.get('segment') != previous + 1:
        reader, index, sim_s, _ = _last_frame(run, previous)
        journal = {'segment': previous + 1, 'reason': reason, 'ended_at': last_activity(run, store),
                   'source_frame': int(index), 'source_sim_s': sim_s, 'interrupted': None}
        store.put('segment_journal', journal)
    segment, sim_s = journal['segment'], journal['source_sim_s']
    if journal['interrupted'] is None:
        with store.transaction():  # the interruptions and their record commit together
            journal['interrupted'] = store.interrupt_for_segment(INTERRUPTED, sim_s)
            store.put('segment_journal', journal)
    reader = _last_frame(run, previous)[0]
    pose = next(reader.selected_frames([journal['source_frame']]))[2]
    holds = {}
    for arm, hold in (store.get('arm_holds') or {}).items():
        if isinstance(hold, dict) and 0 <= sim_s - hold.get('sim_s', -1e9) <= HOLD_MAX_AGE_S: holds[arm] = hold
    folder = input_dir(run, segment); folder.mkdir(parents=True, exist_ok=True)
    import io
    buffer = io.BytesIO(); np.save(buffer, pose, allow_pickle=False)
    _write_atomic(folder / 'restore-pose.npy', buffer.getvalue())
    note = {'schema': RESTORE_SCHEMA, 'segment': segment, 'case_id': reader.meta['case_id'],
            'source_scene_sha256': reader.meta['source_scene_sha256'],
            'from_segment': previous, 'source_frame': journal['source_frame'], 'source_sim_s': sim_s,
            'held_grasps': holds,
            'missing': ['velocity', 'actuator and controller state', 'contact history', 'unfinished actions'],
            'scope': 'Approximate physical restore of the same trial; the run, its sessions and records continue'}
    # The Dial game is episode history: the new world's evaluator continues its trials and BEST.
    record = dial_record(run, sim_s)
    if record is None:
        payloads = relay_record(run, sim_s)
        if payloads is not None: record = {'relay_payloads': payloads}
    if record is not None: note['evaluator'] = record
    write_json(folder / 'restore-pose.json', note)
    import hashlib
    manifest_path = run / 'private/inputs/manifest.json'; manifest = json.loads(manifest_path.read_text())
    for name in ('restore-pose.npy', 'restore-pose.json'):
        path = folder / name
        manifest['input_sha256'][str(path.relative_to(run))] = hashlib.sha256(path.read_bytes()).hexdigest()
    write_json(manifest_path, manifest)
    if verify_inputs(run, source_root=source_root): raise ValueError('Segment restore inputs did not verify')
    # The previous world's address is dead; hosts wait for the new world to publish one.
    for connection in (run / 'private/state/connections').glob('*.json'):
        value = json.loads(connection.read_text())
        if value.pop('url', None) is not None:
            write_json(connection, value); connection.chmod(0o600)
    # Last, so a preparation that stopped part way still sees the backstop stop it continues.
    if store.get('wall_backstop'): _waive_backstop(run, store, manual_authorization)
    with store.transaction():
        segments = store.get('segments') or [{'index': 0, 'started_at': store.get('start_at')}]
        segments[-1].update(ended_at=journal['ended_at'], end_reason=journal['reason'])
        store.put('segments', segments)
        store.put('pending_segment', {'segment': segment, 'prepared_at': time.time(), 'previous_ended_at': journal['ended_at'],
                                      'restored_sim_s': sim_s, 'interrupted': journal['interrupted']})
        store.put('segment', segment)
        store.put('dispatch_paused', True)
        store.put('physics_state', 'stopped')
        store.put('execution_owner_attached', False)
        store.put('lifecycle', 'resuming')
        store.put('segment_journal', None)
        store.event('SEGMENT_PREPARED', 'Meta', {'segment': segment, 'reason': journal['reason'], 'restored_sim_s': sim_s,
                                                 'source_frame': journal['source_frame'], 'interrupted': journal['interrupted']})
    export(run, store)
    return note


def _waive_backstop(run, store, authorization):
    """An operator authorized continuing a run the wall backstop stopped: the backstop's stop
    records are kept under their own names, so the trial is again scored at its active-time
    cutoff, and the backstop counts again from now."""
    outputs = Path(run) / 'private/outputs'
    segment = store.get('segment', 0)
    for name in ('budget-cutoff.json', 'evaluation.json'):
        if (outputs / name).is_file():
            (outputs / name).replace(outputs / name.replace('.json', '-wall-backstop-%d.json' % segment))
    with store.transaction():
        waived = {'at': time.time(), 'authorization': authorization, 'segment': segment,
                  'backstop': store.get('wall_backstop')}
        store.put('wall_backstop_waived', waived)
        store.put('wall_backstop', None)
        store.put('termination_reason', None)
        store.event('WALL_BACKSTOP_WAIVED', 'Meta', waived)


def begin_segment(store, now=None):
    """Record the start of the prepared segment; returns its record."""
    now = time.time() if now is None else now
    pending = store.get('pending_segment')
    if not pending: raise ValueError('No prepared segment')
    downtime = max(0., now - pending['previous_ended_at'])
    store.put('downtime_s', store.get('downtime_s', 0.) + downtime)
    record = {'index': pending['segment'], 'started_at': now, 'downtime_s': downtime,
              'restored_sim_s': pending['restored_sim_s'], 'interrupted': pending['interrupted']}
    store.put('segments', (store.get('segments') or []) + [record])
    store.put('pending_segment', None)
    store.event('SEGMENT_STARTED', 'Meta', record)
    return record


def resume_message(run, actor, record):
    """The frozen resume text for one role, filled for this segment (the same on both engines)."""
    from .bootstrap import fill_resume
    return fill_resume(run, actor, record)


def export(run, store):
    write_json(Path(run) / 'private/outputs/segments.json',
               {'segment': store.get('segment', 0), 'segments': store.get('segments') or [],
                'downtime_s': store.get('downtime_s', 0.), 'pending': store.get('pending_segment')})


def try_continue(run, reason, wait_s=60., sleep=time.sleep):
    """After a host exited abnormally: prepare the next segment if this run may continue.

    Waits up to `wait_s` for the world process to finish closing (it closes by itself once
    its host is gone). Returns (True, None) when a segment was prepared, else (False, why).
    """
    from .store import RuntimeStore
    run = Path(run)
    deadline = time.monotonic() + wait_s
    while not owner_released(run) and time.monotonic() < deadline: sleep(.5)
    store = RuntimeStore(run / 'private/state/runtime.sqlite')
    try:
        ok, why = retry_eligibility(run, store)
        if not ok: return False, why
        prepare_retry(run, store, reason)
        return True, None
    finally:
        store.close()


# Process statistics that accumulate within one world process (suite Monitor results).
PROCESS_SUM = ('samples', 'inter_robot_contacts', 'execution_overlap_sim_s', 'motion_overlap_sim_s',
               'any_motion_sim_s', 'robot_motion_s', 'useful_blue_support_robot_s')
PROCESS_MAX = ('max_sample_gap_s', 'peak_concurrent_actions', 'peak_moving_robots')
PROCESS_LISTS = ('violations', 'self_contacts')
EPISODE_SUM = ('inter_robot_episodes', 'self_robot_episodes')


def process_summary(run):
    """Process statistics of the whole trial, combined over its segments.

    Each world process starts its own counts, so a continued run's final evaluation covers
    only its last segment. Earlier segments are read from their last cumulative snapshot
    in the shared process log (each segment starts with its own header row); a segment
    whose world was killed loses what changed since its last logged row. None for one segment.
    """
    run = Path(run); log = run / 'private/outputs/suite-process.jsonl'
    if not log.is_file(): return None
    parts = []
    for line in log.read_text(errors='replace').splitlines():
        try: row = json.loads(line)
        except ValueError: continue
        if 'schema' in row and 'type' not in row: parts.append(None)
        elif row.get('type') in ('snapshot', 'event') and parts: parts[-1] = row['result']
    if len(parts) < 2: return None
    final = run / 'private/outputs/evaluation.json'
    if final.is_file():
        evaluation = json.loads(final.read_text())
        if all(k in evaluation for k in PROCESS_SUM[:2]): parts[-1] = evaluation
    segments = [{k: p.get(k) for k in PROCESS_SUM + PROCESS_MAX + ('process_compliant', 'sim_time_s')}
                if p else None for p in parts]
    seen = [p for p in parts if p]
    total = {k: sum(p.get(k) or 0 for p in seen) for k in PROCESS_SUM}
    total.update({k: max((p.get(k) or 0) for p in seen) for k in PROCESS_MAX})
    total.update({k: [x for p in seen for x in (p.get(k) or [])] for k in PROCESS_LISTS})
    total['process_compliant'] = all(p.get('process_compliant', True) for p in seen) and len(seen) == len(parts)
    total['robot_contact_episodes'] = {k: sum((p.get('robot_contact_episodes') or {}).get(k) or 0 for p in seen)
                                       for k in EPISODE_SUM}
    record = dial_record(run)
    if record is not None: total['dial'] = record
    return {'segments': segments, 'total': total, 'missing_segments': [i for i, p in enumerate(parts) if not p],
            'scope': 'Earlier segments from their last logged row before they ended'}


def relay_record(run, cutoff=None):
    """Each Relay timber's handovers and drops over all segments, up to `cutoff`, with its
    custody and dropped state as last logged.

    A segment's rows run to the restore frame of the next. Handovers are matched by their
    content, so a carried record is not counted twice. None for other families or an empty log.
    """
    log = Path(run) / 'private/outputs/suite-process.jsonl'
    if not log.is_file(): return None
    blocks = [[]]
    for line in log.read_text(errors='replace').splitlines():
        try: row = json.loads(line)
        except ValueError: continue
        if not isinstance(row, dict): continue
        if 'schema' in row and 'type' not in row: blocks.append([])
        elif isinstance(row.get('result'), dict) and isinstance(row['result'].get('payloads'), dict): blocks[-1].append(row)
    blocks = [b for b in blocks if b]
    payloads = {}
    for i, block in enumerate(blocks):
        end = blocks[i + 1][0]['sim_time_s'] if i + 1 < len(blocks) else cutoff
        kept = [r for r in block if end is None or r['sim_time_s'] <= end + 1e-9]
        if not kept: continue
        for ident, item in kept[-1]['result']['payloads'].items():
            entry = payloads.setdefault(ident, {'handovers': [], 'drops': 0})
            for handover in item.get('handovers') or []:
                if handover not in entry['handovers']: entry['handovers'].append(handover)
            entry['drops'] = max(entry['drops'], int(item.get('drops') or 0))
            # Who held it and whether it lay dropped, at the end of the latest segment.
            for key in ('custody', 'dropped'):
                if key in item: entry[key] = item[key]
    return payloads or None


def dial_record(run, cutoff=None):
    """The Dial game's episode record over all segments: valid trials, BEST and success.

    Each segment counts up to the restore frame of the next (later rows were never
    physically kept); `cutoff` ends the last one. A segment whose evaluator continued
    the record reports cumulative counts with the carried part beside them; one started
    before that existed counted from zero, so its trials are added. Rows are the Dial
    results of the shared process log; None for other families or an empty log.
    """
    log = Path(run) / 'private/outputs/suite-process.jsonl'
    if not log.is_file(): return None
    blocks = [[]]
    for line in log.read_text(errors='replace').splitlines():
        try: row = json.loads(line)
        except ValueError: continue
        if not isinstance(row, dict): continue
        if 'schema' in row and 'type' not in row: blocks.append([])
        elif isinstance(row.get('result'), dict) and 'valid_trials' in row['result']: blocks[-1].append(row)
    blocks = [b for b in blocks if b]
    trials, best, solved, last = 0, None, False, None
    for i, block in enumerate(blocks):
        end = blocks[i + 1][0]['sim_time_s'] if i + 1 < len(blocks) else cutoff
        kept = [r for r in block if end is None or r['sim_time_s'] <= end + 1e-9]
        if not kept: continue
        last = kept[-1]; result = last['result']
        trials += result['valid_trials'] - result.get('carried_valid_trials', 0)
        if result.get('feedback_mode') == 'best_so_far' and isinstance(result.get('display'), int):
            best = max(best or 0, result['display'])
        solved = solved or bool(result.get('solved'))
    if last is None: return None
    record = {'valid_trials': trials, 'best': best, 'solved': solved,
              'input_ready': bool(last['result'].get('input_ready')), 'sim_time_s': last['sim_time_s']}
    # Which dials had qualified blue support at the restore frame (Monitor.continue_dial_record).
    if isinstance(last['result'].get('private_support_ready'), list):
        record['support_ready'] = [bool(x) for x in last['result']['private_support_ready']]
    return record
