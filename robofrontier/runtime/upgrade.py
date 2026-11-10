"""Explicit stopped-run runtime upgrades and single-segment retry authority.

The operator holds the recovery/supervisor locks and has excluded live hosts.
This module never starts a process, executes an action, or relaxes automatic retry.
A failed partial upgrade remains fenced by the original input integrity checks.
"""
import hashlib
import json
from pathlib import Path
import shutil
import sys
import sysconfig
import time

from . import segments as run_segments
from .bootstrap import NETWORK_RESUME
from .setup import verify_inputs, write_json
from ..tasks.config import ROOT

SCHEMA = 'robofrontier.stopped-runtime-upgrade.v1'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ledger(store):
    rows = [[list(row) for row in store.db.execute('SELECT * FROM '+table+' ORDER BY id')]
            for table in ('calls', 'actions')]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def stopped(run, store):
    run = Path(run).resolve()
    # A world the wall backstop stopped ended as at a cutoff (policy_probe.BudgetGuard).
    backstop = (store.get('wall_backstop') and store.get('lifecycle') == 'ended'
                and store.get('physics_state') == 'finished')
    if (not backstop and (store.get('lifecycle') != 'interrupted' or store.get('physics_state') != 'stopped')
            or not store.get('dispatch_paused') or store.get('integrity_valid') is not True
            or store.get('segment_journal') or store.get('pending_segment')):
        raise ValueError('Upgrade requires a fully stopped, sealed and integrity-valid segment')
    if not run_segments.owner_released(run): raise ValueError('A process still owns the world')
    kinds = ('INTEGRITY_ABORT',) + run_segments.NORMAL_END_EVENTS
    if store.db.execute('SELECT 1 FROM events WHERE kind IN (%s) LIMIT 1' % ','.join('?' for _ in kinds), kinds).fetchone():
        raise ValueError('A normal end or integrity abort cannot be upgraded for continuation')
    seal = json.loads((run_segments.output_dir(run, store.get('segment', 0))/'seal.json').read_text())
    if not seal.get('sealed') or any(seal.get(k) for k in ('capture_error', 'shutdown_error')):
        raise ValueError('The original world did not seal cleanly')
    actions = {row['id'] for row in store.db.execute("SELECT id FROM actions WHERE status NOT IN ('completed','failed')")}
    if seal.get('owner_was_live') is False:
        # The world had closed by itself before the seal (its host was lost). Its unfinished
        # actions are the ones the seal lists; the next segment fails them and replays none
        # (run_segments.prepare_retry, as for an automatic continuation).
        if actions != set(seal.get('unresolved_action_ids') or []):
            raise ValueError('Unsettled actions differ from the ones the seal recorded')
        return
    if store.db.execute("SELECT 1 FROM calls WHERE status NOT IN ('completed','failed') LIMIT 1").fetchone():
        raise ValueError('An original call is unsettled; never replay it')
    if actions: raise ValueError('An original action is unsettled; never replay it')
    if not seal.get('fresh_observation') or seal.get('unresolved_action_ids'):
        raise ValueError('The original world did not seal cleanly')


def upgrade(run, store, *, previous_source, reason, expected_segment, expected_ledger, source=ROOT):
    """Freeze a new runtime with an archived parent; preserve all original policy inputs.

    This is a deliberate operator migration, never a batch preparation side effect.
    The returned manifest-bound record authorizes precisely the next segment once.
    """
    run, source = Path(run).resolve(), Path(source).resolve()
    stopped(run, store)
    if not reason or store.get('segment', 0) != expected_segment or ledger(store) != expected_ledger:
        raise ValueError('Operator authorization no longer matches the stopped segment and ledger')
    if verify_inputs(run, source_root=previous_source): raise ValueError('Original frozen inputs changed')
    segment = expected_segment + 1
    parent = run/'private/inputs/runtime-upgrades'/str(segment)
    parent.mkdir(parents=True, exist_ok=False)
    manifest_file = run/'private/inputs/manifest.json'
    old = json.loads(manifest_file.read_text())
    shutil.copy2(manifest_file, parent/'parent-manifest.json')
    shutil.copytree(run/'private/inputs/frozen-source', parent/'parent-source')
    access_file = run/'private/inputs/policy-access.json'
    shutil.copy2(access_file, parent/'parent-policy-access.json')
    # Public prompts, task semantics and physical inputs remain byte-identical.
    names = set(old['source_sha256']) | {
        str(p.relative_to(source)) for p in (source/'robofrontier').rglob('*.py')}
    hashes = {name: sha(source/name) for name in sorted(names)}
    changed = [name for name in sorted(names) if old['source_sha256'].get(name) != hashes[name]]
    if any(not name.startswith('robofrontier/') for name in changed):
        raise ValueError('Runtime upgrade cannot change frozen policy prompts or documentation')
    # Only interpreter metadata/package directories are added for a new venv.
    # The source, credentials, control roots and other tasks stay denied.
    access = json.loads(access_file.read_text())
    reads = {Path(sys.prefix)/'pyvenv.cfg', Path(sysconfig.get_path('purelib')), Path(sysconfig.get_path('platlib'))}
    for path in reads:
        if path.exists(): access['filesystem'][str(path.resolve())] = 'read'
    note = {'schema': SCHEMA, 'run': str(run), 'run_id': store.get('run_id'),
            'from_segment': expected_segment, 'to_segment': segment, 'reason': reason, 'at': time.time(),
            'parent_manifest_sha256': sha(parent/'parent-manifest.json'),
            'ledger_sha256': expected_ledger, 'source_sha256': hashes, 'changed_sources': changed,
            'runtime_metadata_reads': sorted(str(p.resolve()) for p in reads if p.exists()),
            'automatic_action_replays': 0,
            'restore_scope': 'Approximate last pose and recent completed holds; velocities/controllers/contact history unavailable'}
    grant = parent/'authorization.json'; write_json(grant, note)
    inputs = dict(old['input_sha256'])
    for path in parent.rglob('*'):
        if path.is_file(): inputs[str(path.relative_to(run))] = sha(path)
    write_json(access_file, access)
    inputs[str(access_file.relative_to(run))] = sha(access_file)
    notice = run/'private/inputs/bootstrap/network-resume.md'
    if notice.exists() and notice.read_text() != NETWORK_RESUME:
        raise ValueError('Existing network continuation notice differs')
    notice.write_text(NETWORK_RESUME)
    inputs[str(notice.relative_to(run))] = sha(notice)
    for name in names:
        target = run/'private/inputs/frozen-source'/name
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source/name, target)
    write_json(manifest_file, {**old, 'source_sha256': hashes, 'input_sha256': inputs})
    if verify_inputs(run, source_root=source): raise ValueError('Upgraded runtime did not verify; remain stopped')
    if ledger(store) != expected_ledger: raise ValueError('Original ledger changed during upgrade')
    relative = str(grant.relative_to(run))
    store.event('RUNTIME_UPGRADE_AUTHORIZED', 'Meta', {'authorization': relative, 'sha256': sha(grant),
                                                       'segment': segment, 'automatic_action_replays': 0})
    return relative


def validate_authorization(run, store, authorization, *, source_root=None):
    """Validate an explicitly supplied, manifest-bound one-segment grant."""
    run = Path(run).resolve(); grant = run/authorization
    if (not isinstance(authorization, str) or not grant.resolve().is_relative_to(run/'private/inputs/runtime-upgrades')
            or grant.is_symlink() or grant.name != 'authorization.json'):
        raise ValueError('Invalid stopped-runtime authorization path')
    stopped(run, store)
    manifest = json.loads((run/'private/inputs/manifest.json').read_text())
    note = json.loads(grant.read_text())
    if (manifest['input_sha256'].get(authorization) != sha(grant) or note.get('schema') != SCHEMA
            or note.get('run') != str(run) or note.get('run_id') != store.get('run_id')
            or note.get('from_segment') != store.get('segment', 0)
            or note.get('to_segment') != store.get('segment', 0)+1
            or note.get('source_sha256') != manifest['source_sha256']
            or note.get('ledger_sha256') != ledger(store)
            or note.get('automatic_action_replays') != 0
            or verify_inputs(run, source_root=source_root)):
        raise ValueError('Stopped-runtime authorization changed or was already consumed')
    return note
