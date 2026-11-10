"""Custody and archiving of a run's native session transcripts.

Codex writes transcripts into its shared home. At the end of every segment the
Codex host calls `keep_codex` (python -m robofrontier.batch.session_archive keep RUN):
each thread of the run (roles, delegates, snapshot anchors) is copied into the
run's private/engine/transcripts/, verified by SHA-256 and listed in index.json.
The host never deletes the originals, because a continued segment resumes
those threads from the home. Claude keeps its transcripts in the run already.

`archive_run` (python -m robofrontier.batch.session_archive archive RUN) runs once a
run is final and idle. It compresses each transcript to `.jsonl.xz` in place
and, for Codex, removes the home originals. Every step is recorded before the
file it replaces is removed: a compressed copy must decompress to the original
SHA-256 and be listed in private/outputs/session-archive.json before its
original goes, and a home original goes only when it still equals the run's
verified copy. Readers (`run_metrics.session_glob`, reports, collection) accept
both forms.
"""
import argparse
import hashlib
import json
import lzma
import os
from pathlib import Path
import shutil
import sqlite3
import time

from ..runtime import layout as run_layout
from .metrics import session_glob
from ..runtime.setup import write_json

FINISHED = ('ended', 'interrupted', 'recovery_required')


def sha256(path, opener=open):
    digest = hashlib.sha256()
    with opener(path, 'rb') as stream:
        for block in iter(lambda: stream.read(1 << 20), b''): digest.update(block)
    return digest.hexdigest()


def _meta(run):
    """Lifecycle, configuration, roles and snapshot anchors, read without writing the database."""
    database = run/'private/state/runtime.sqlite'
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        meta = {key: json.loads(value) for key, value in db.execute('SELECT key, value FROM meta')}
        agents = {actor: json.loads(value) for actor, value in db.execute('SELECT id, value FROM agents')}
    threads = {agent['thread_id']: actor for actor, agent in agents.items()
               if agent.get('kind') != 'manager' and agent.get('thread_id')}
    for delegation_id, delegation in (meta.get('delegations') or {}).items():
        if delegation.get('snapshot_thread_id'):
            threads.setdefault(delegation['snapshot_thread_id'], 'snapshot:'+delegation_id)
    return meta, threads


def _codex_home(run, home=None):
    if home is not None: return Path(home).expanduser().resolve()
    marker = run_layout.path(run, 'codex_home_marker', 'codex')
    if not marker.is_file(): raise ValueError('Run has no Codex home marker: '+str(marker))
    return Path(json.loads(marker.read_text())['codex_home']).expanduser().resolve()


def _copy_verified(source, target):
    temporary = target.with_name(target.name+'.%d.tmp' % os.getpid())
    shutil.copy2(source, temporary)  # keeps the modification time the idle check reads
    with temporary.open('rb') as written: os.fsync(written.fileno())
    checksum = sha256(temporary)
    if checksum != sha256(source):
        temporary.unlink()
        raise ValueError('Transcript changed while copying: '+str(source))
    os.replace(temporary, target)
    return checksum


def keep_codex(run, home=None):
    """Copy this run's Codex threads from the shared home into the run, verified; delete nothing."""
    run = Path(run).resolve()
    try: folder = run_layout.path(run, 'engine_transcripts', 'codex')
    except KeyError: return None  # legacy runs keep their transcripts in the home
    home = _codex_home(run, home)
    _, threads = _meta(run)
    folder.mkdir(parents=True, exist_ok=True)
    index_path = folder/'index.json'
    previous = {row['thread_id']: row for row in json.loads(index_path.read_text())['threads']} if index_path.is_file() else {}
    rows, complete = [], True
    for thread, actor in sorted(threads.items()):
        sources = [p for p in session_glob(home/'sessions', '*'+thread+'.jsonl') if p.suffix == '.jsonl']
        if len(sources) != 1:
            # Already archived and removed from the home: the run's copy is the record.
            if not sources and thread in previous and previous[thread].get('verified'):
                rows.append(previous[thread]); continue
            complete = False
            rows.append({'thread_id': thread, 'actor': actor, 'status': 'missing' if not sources else 'ambiguous'})
            continue
        source = sources[0]
        archived = folder/(source.name+'.xz')
        if archived.exists():
            # An archive stopped before releasing the home copy: keep the run's copy as is.
            checksum = sha256(source)
            if sha256(archived, lzma.open) != checksum:
                raise ValueError('Run copy of '+thread+' is archived but differs from the home; refusing to overwrite it')
        else:
            checksum = _copy_verified(source, folder/source.name)
        copy = archived if archived.exists() else folder/source.name
        rows.append({'thread_id': thread, 'actor': actor, 'file': copy.relative_to(run).as_posix(),
                     'source': str(source), 'sha256': checksum, 'verified': True})
    write_json(index_path, {'schema': 'robofrontier.codex-transcripts.v1', 'codex_home': str(home),
                            'complete': complete, 'copied_at': time.time(), 'threads': rows})
    return {'threads': len(rows), 'complete': complete, 'index': str(index_path)}


def compress_verified(path):
    """Write path.xz and prove it decompresses to the original bytes; the original is kept."""
    path = Path(path); target = path.with_name(path.name+'.xz')
    original = sha256(path)
    if target.exists():
        # A previous archive stopped after compressing; reuse the copy only if it is exact.
        if sha256(target, lzma.open) != original: raise ValueError('Existing archive differs from '+str(path))
    else:
        temporary = target.with_name(target.name+'.%d.tmp' % os.getpid())
        with path.open('rb') as source, lzma.open(temporary, 'wb', preset=6) as output:
            for block in iter(lambda: source.read(1 << 20), b''): output.write(block)
        with temporary.open('rb') as written: os.fsync(written.fileno())
        if sha256(temporary, lzma.open) != original:
            temporary.unlink()
            raise ValueError('Compressed copy does not match '+str(path)+'; original kept')
        os.replace(temporary, target)
    return {'path': str(target), 'sha256_uncompressed': original,
            'bytes_uncompressed': path.stat().st_size, 'bytes_compressed': target.stat().st_size}


def continuable(run, meta):
    """Whether this run may still be continued as a new segment, and so must keep its sessions.

    Only what no continuation can change ends it: a normal end or integrity abort, a run
    that never started, a layout without segments, or no recorded motion to restore. A
    source checkout that moved on, the automatic continuation already used, a stop
    request or a seal do not: an operator-authorized runtime upgrade can still continue
    such a run (runtime_upgrade), and it resumes its Codex threads from the home."""
    from ..runtime import segments as run_segments
    if meta.get('lifecycle') == 'ended' or meta.get('integrity_valid') is False: return False
    if not run_segments.supported(run) or meta.get('start_at') is None: return False
    kinds = ('INTEGRITY_ABORT',) + run_segments.NORMAL_END_EVENTS
    database = run/'private/state/runtime.sqlite'
    with sqlite3.connect(database.resolve().as_uri()+'?mode=ro', uri=True) as db:
        if db.execute('SELECT 1 FROM events WHERE kind IN (%s) LIMIT 1' % ','.join('?'*len(kinds)), kinds).fetchone():
            return False
    try:
        return run_segments._last_frame(run, meta.get('segment', 0)) is not None
    except (OSError, ValueError, KeyError, TypeError):
        return True  # Unreadable motion is for review, not a reason to release the sessions.


def _host_alive(pid):
    """Conservative: any live process with the recorded PID counts as the host."""
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1: return False
    try: os.kill(pid, 0)
    except ProcessLookupError: return False
    except PermissionError: return True
    return True


def archive_run(run, home=None, min_idle_s=60, final=False):
    run = Path(run).resolve()
    meta, _ = _meta(run)
    if meta.get('lifecycle') not in FINISHED:
        raise ValueError('Archive only a finished run; lifecycle is '+str(meta.get('lifecycle')))
    if not final and continuable(run, meta):
        raise ValueError('This run can still be continued; archive it after its last segment or pass --final')
    engine = json.loads((run/'private/inputs/manifest.json').read_text()).get('engine', 'codex')
    host = run_layout.path(run, 'host_process', engine)
    if host.is_file() and _host_alive(json.loads(host.read_text()).get('pid')):
        raise ValueError('A process with the recorded host PID is still live')
    if engine == 'codex':
        kept = keep_codex(run, home)
        if kept is not None and not kept['complete']:
            raise ValueError('Some Codex threads have no single source; see '+kept['index'])
        folder = run_layout.path(run, 'engine_transcripts', 'codex') if kept is not None else None
        paths = sorted(folder.glob('*.jsonl')) if folder else []
    else:
        paths = sorted((run_layout.path(run, 'engine_config', 'claude')/'projects').rglob('*.jsonl'))
    now = time.time()
    busy = [str(p) for p in paths if now-p.stat().st_mtime < min_idle_s]
    if busy: raise ValueError('Sessions modified in the last %ds; not archiving: %s' % (min_idle_s, busy[:3]))
    manifest_path = run/'private/outputs/session-archive.json'
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else \
        {'schema': 'robofrontier.session-archive.v2', 'files': [], 'home_sources_removed': []}
    manifest.setdefault('home_sources_removed', [])
    for path in paths:
        manifest['files'].append({**compress_verified(path), 'archived_at': time.time()})
        write_json(manifest_path, manifest)  # recorded before the original goes
        path.unlink()
    if engine == 'codex' and folder is not None:
        index = json.loads((folder/'index.json').read_text())
        for row in index['threads']:
            source = Path(row.get('source', ''))
            if not row.get('verified') or not source.is_file(): continue
            if sha256(source) != row['sha256']: continue  # changed after the copy: keep it
            manifest['home_sources_removed'].append({'thread_id': row['thread_id'], 'path': str(source),
                                                     'sha256': row['sha256'], 'removed_at': time.time()})
            write_json(manifest_path, manifest)
            source.unlink()
    return {'archived': len(paths), 'home_sources_removed': len(manifest['home_sources_removed']),
            'manifest': str(manifest_path)}


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest='command', required=True)
    keep = sub.add_parser('keep', help='copy a Codex run\'s transcripts into the run (the host does this)')
    keep.add_argument('run_dir', type=Path); keep.add_argument('--codex-home', type=Path)
    archive = sub.add_parser('archive', help='compress a final run\'s transcripts and release the home copies')
    archive.add_argument('run_dir', type=Path); archive.add_argument('--codex-home', type=Path)
    archive.add_argument('--min-idle-s', type=float, default=60)
    archive.add_argument('--final', action='store_true', help='the run will not be continued even though it could be')
    args = parser.parse_args()
    if args.command == 'keep': result = keep_codex(args.run_dir, args.codex_home)
    else: result = archive_run(args.run_dir, args.codex_home, args.min_idle_s, args.final)
    print(json.dumps(result, indent=2))


if __name__ == '__main__': main()
