"""Collect stopped Codex/Claude benchmark evidence without inference or source edits.

Run in the same filesystem/container environment as the runner. This is an
evidence collector, not a score validator or an authentication backup.
"""

import argparse
import fcntl
import json
import os
import re
import shutil
import sqlite3
import stat
import subprocess
import tempfile
from contextlib import ExitStack
from pathlib import Path

from roboteam.harness.claude.session.native_home import history_directory
from roboteam.io import file_sha256 as digest
from roboteam.launch.results.host_metrics import codex_run_transcripts, session_glob, session_stem
from roboteam.runtime.run import layout as run_layout
from roboteam.runtime.run.setup import write_json

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}\Z')
TERMINAL = {'closed', 'needs_review', 'stopped', 'stopped_before_start'}


def load(path):
    return json.loads(Path(path).read_text())


def lock_if_present(stack, path):
    if path.exists():
        stream = stack.enter_context(path.open('rb'))
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('Evidence is still owned by a running writer: ' + str(path)) from error


def copy_stable(source, target):
    if not stat.S_ISREG(source.lstat().st_mode):
        raise ValueError('Expected a regular evidence file: ' + str(source))
    before = source.stat()
    checksum = digest(source)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    after = source.stat()
    if (
        (before.st_size, before.st_mtime_ns, before.st_ino)
        != (after.st_size, after.st_mtime_ns, after.st_ino)
        or digest(target) != checksum
        or digest(source) != checksum
    ):
        raise ValueError('Evidence changed while collecting: ' + str(source))
    return checksum


def _alive(pid):
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return True
    try:
        os.kill(int(pid), 0)
        return True
    except ProcessLookupError:
        return False
    except (PermissionError, TypeError, ValueError):
        return True


def native_matches(harness, run, home, tid):
    """Where one native session is looked up and its transcripts there, plain or archived.

    A sealed Codex run carries its own copies; one that never sealed still has them in its home."""
    if harness == 'claude':
        root = history_directory(run)
        return root, [
            p for p in session_glob(root / 'projects', tid + '.jsonl') if p.parent.parent == root / 'projects'
        ]
    own = codex_run_transcripts(run, tid)
    return (
        (own[0].parent, own)
        if own
        else (home / 'sessions', session_glob(home / 'sessions', '*' + tid + '.jsonl'))
    )


def session_name(tid, transcript):
    """The collected file name keeps the transcript's form: archived copies stay `.jsonl.xz`."""
    return tid + ('.jsonl.xz' if transcript.name.endswith('.xz') else '.jsonl')


def host_is_live(pid, run):
    """A live recorded PID is insufficient: it may belong to an unrelated job."""
    if not _alive(pid):
        return False
    if not isinstance(pid, int) or isinstance(pid, bool) or pid <= 1:
        return True
    proc = Path('/proc') / str(pid) / 'cmdline'
    try:
        if Path('/proc').is_dir():
            argv = [a.decode(errors='replace') for a in proc.read_bytes().split(b'\x00') if a]
            command = ' '.join(argv)
            for i, arg in enumerate(argv[:-1]):
                if Path(arg).name == 'policy_host.js':
                    target = Path(argv[i + 1])
                    if not target.is_absolute():
                        target = Path('/proc') / str(pid) / 'cwd' / target
                    if target.is_dir():
                        return target.resolve() == run.resolve()
        else:
            result = subprocess.run(
                ['ps', '-ww', '-p', str(pid), '-o', 'command='], capture_output=True, text=True, timeout=5
            )
            if result.returncode:
                return _alive(pid)
            command = result.stdout
    except (OSError, subprocess.TimeoutExpired):
        return _alive(pid)  # Unverifiable ownership remains a blocker.
    if not command.strip():
        return _alive(pid)
    # macOS ps does not quote argv boundaries. If a policy host is present but
    # its run cannot be established, remain conservative (also for symlink paths).
    return 'policy_host.js' in command


def _files(root, tolerated=(), skipped=None):
    """Never follow symlinks or collect a CLI credential/configuration store.

    A link or nonregular entry is fatal, except below a `tolerated` folder (a run's
    policy-writable workspace, where `python -m venv` makes links): there it is not
    followed or copied, and (path, kind, link text) is appended to `skipped`."""
    if root.is_symlink():
        raise ValueError('Symlink evidence root: ' + str(root))

    def tolerate(path, kind):
        if not any(path.is_relative_to(folder) and path != folder for folder in tolerated):
            return False
        if skipped is not None:
            try:
                link = os.readlink(path) if kind == 'symlink' else None
            except OSError:
                link = None
            skipped.append((path, kind, link))
        return True

    for parent, dirs, files in os.walk(root, followlinks=False):
        parent = Path(parent)
        linked = set()
        for name in dirs + files:
            if (parent / name).is_symlink():
                if not tolerate(parent / name, 'symlink'):
                    raise ValueError(
                        'Symlink inside evidence; resolve explicitly before collecting: ' + str(parent / name)
                    )
                linked.add(name)
        # The native configuration (private/harness/config) is collected separately.
        dirs[:] = sorted(
            d for d in dirs if d not in linked and not (d == 'config' and parent.name == 'harness')
        )
        # Finder writes .DS_Store into any folder it shows, even during collection;
        # it is desktop metadata, not run evidence.
        for name in sorted(f for f in files if f != '.DS_Store' and f not in linked):
            path = parent / name
            if not path.is_file():
                if tolerate(path, 'nonregular'):
                    continue
                raise ValueError('Nonregular evidence file: ' + str(path))
            yield path


def motion_inventory(run):
    """Check every segment's recorded dependencies without importing MuJoCo or altering evidence."""
    from roboteam.runtime.run import segments as run_segments

    task_path = run / 'private/inputs/task.json'
    try:
        task = load(task_path) if task_path.is_file() else {}
        if not isinstance(task, dict):
            raise ValueError('Task must be an object')
    except ValueError:
        return ['task metadata unreadable; motion inventory requires review']
    # A continued run records one motion stream per segment (docs/runs/continuation.md).
    folders = [run_segments.output_dir(run, k) / 'motion' for k in range(load_segment(run) + 1)]
    issues = []
    for k, path in enumerate(folders):
        found = _motion_folder_inventory(path, task)
        issues += found if k == 0 else ['segment %d: %s' % (k, issue) for issue in found]
    return issues


def load_segment(run):
    """The run's current segment from its exported segment record (0 when never continued)."""
    record = run / 'private/outputs/segments.json'
    try:
        return int(load(record).get('segment', 0)) if record.is_file() else 0
    except (ValueError, TypeError, AttributeError):
        return 0


def _motion_folder_inventory(path, task):
    if not (path / 'stream.json').is_file():
        return ['missing motion recording'] if task.get('kind') == 'frontier_suite' else []

    def checked(name, checksum=None):
        p = path / name
        if not p.resolve().is_relative_to(path.resolve()) or not p.is_file():
            raise ValueError('Missing/outside motion dependency: ' + name)
        if checksum is not None and digest(p) != checksum:
            raise ValueError('Motion dependency checksum mismatch: ' + name)
        return p

    try:
        stream = load(path / 'stream.json')
        if stream.get('schema') != 'roboteam.motion.v1' or stream.get('status') not in (
            'complete',
            'interrupted',
        ):
            raise ValueError('Motion index is not finalized')
        chunks = stream['chunks']
        if not chunks or stream['frames'] != sum(c['frames'] for c in chunks):
            raise ValueError('Motion chunk frame counts differ')
        for chunk in chunks:
            checked(chunk['file'], chunk['sha256'])
        checked('events.jsonl')
        source = load(checked('source/workstation.json'))
        if (
            source['scene_sha256'] != stream['source_scene_sha256']
            or source['case']['id'] != stream['case_id']
        ):
            raise ValueError('Motion source identity differs')
        checked('source/scene.xml', source['scene_sha256'])
        for name in ('task.json', 'environment.json'):
            checked('source/' + name)
        for asset in source['assets']:
            checked('source/' + asset['path'], asset['sha256'])
        return []
    except (AttributeError, KeyError, TypeError, ValueError, OSError) as error:
        return ['motion inventory: ' + str(error)]


def collect_batch(batch_path, output):
    batch_path = Path(batch_path).resolve()
    output = Path(output).resolve()
    if output.exists() or output.is_relative_to(batch_path) or batch_path.is_relative_to(output):
        raise ValueError('Collection output must be new and outside the source batch')
    batch = load(batch_path / 'batch.json')
    harnesses = {'roboteam.claude-batch.v2': 'claude', 'roboteam.cli-benchmark.v1': 'codex'}
    if batch.get('schema') not in harnesses:
        raise ValueError('Unsupported batch schema')
    harness = harnesses[batch['schema']]
    state_path = (
        run_layout.batch_path(batch_path, 'engineering_status')
        if harness == 'claude'
        else batch_path / 'batch.json'
    )
    state = load(state_path)
    if state.get('status') not in TERMINAL:
        raise ValueError('Collect only a stopped batch; inspect runner status first')
    jobs = batch.get('jobs')
    if not isinstance(jobs, list) or not jobs:
        raise ValueError('Batch has no jobs')
    marker = run_layout.batch_path(batch_path, 'codex_home_marker')
    batch_home = (
        Path(load(marker)['codex_home']).resolve()
        if marker.exists()
        else Path(os.environ.get('CODEX_HOME', Path.home() / '.codex')).resolve()
    )
    state_jobs = {(j.get('model_entry'), j.get('case_id')): j for j in state.get('jobs', [])}
    seen = set()
    runs = []
    for job in jobs:
        case, model_entry = job.get('case_id'), job.get('model_entry', '')
        if (
            not isinstance(case, str)
            or not ID.fullmatch(case)
            or model_entry
            and (not isinstance(model_entry, str) or not ID.fullmatch(model_entry))
        ):
            raise ValueError('Invalid case/model identifier')
        run = Path(job['run_directory']).resolve()
        if not run.is_relative_to(batch_path) or run == batch_path or run in seen:
            raise ValueError('Run must be unique and inside this batch')
        seen.add(run)
        status = state_jobs.get((job.get('model_entry'), case), job).get('status')
        if status not in TERMINAL:
            raise ValueError('Job may still be writing: ' + str(run))
        if harness == 'claude':
            launch_file = run / 'private/inputs/claude.json'
            selected = load(launch_file).get('model_entry', {}) if launch_file.is_file() else {}
            auth_home = selected.get('native_config_dir')
            if (
                selected.get('auth_mode') == 'native_login'
                and isinstance(auth_home, str)
                and Path(auth_home).resolve().is_relative_to(batch_path)
            ):
                raise ValueError('Keep the native authentication home outside the evidence batch')
        runs.append((job, run, status))
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix='.rf-collection-', dir=output.parent))
    try:
        with ExitStack() as stack:
            for key in ('supervisor_lock', 'engineering_lock'):
                lock_if_present(stack, run_layout.batch_path(batch_path, key))
            for job, run, status in runs:
                for key in ('world_lock', 'engineering_lock'):
                    lock_if_present(stack, run_layout.path(run, key))
                host = run_layout.path(run, 'host_process')
                if host.is_file() and host_is_live(load(host).get('pid'), run):
                    raise ValueError(
                        'Recorded host PID is still live; collect in the runner environment: ' + str(host)
                    )
            workspaces = {run: run_layout.path(run, 'policy_cwd') for job, run, status in runs}
            tolerated = tuple(workspaces.values())
            skipped = []
            initial_files = list(_files(batch_path, tolerated, skipped))
            hashes, native_sources, native_directories, native_queries = {}, {}, {}, []
            for path in initial_files:
                rel = Path('batch') / path.relative_to(batch_path)
                hashes[rel.as_posix()] = copy_stable(path, temporary / rel)
            rows = []
            for job, run, status in runs:
                run_marker = run_layout.path(run, 'codex_home_marker')
                native_config = run_layout.path(run, 'harness_config').relative_to(run)
                home = Path(load(run_marker)['codex_home']).resolve() if run_marker.is_file() else batch_home
                issues, roles, snapshot_sessions = [], [], []
                for path, kind, link in skipped:
                    if path.is_relative_to(workspaces[run]):
                        issues.append(
                            'workspace %s not collected: %s%s'
                            % (kind, path.relative_to(run).as_posix(), '' if link is None else ' -> ' + link)
                        )
                db = temporary / 'batch' / run.relative_to(batch_path) / 'private/state/runtime.sqlite'
                agents, meta = [], {}
                if not db.is_file():
                    issues.append('missing runtime.sqlite')
                else:
                    try:
                        # SQLite can update shared-memory bookkeeping even in a
                        # read-only connection. Validate a disposable copy so the
                        # collected DB/WAL/SHM bytes remain original evidence.
                        with tempfile.TemporaryDirectory(prefix='rf-db-check-') as check:
                            check = Path(check)
                            for suffix in ('', '-wal', '-shm'):
                                if Path(str(db) + suffix).is_file():
                                    shutil.copyfile(Path(str(db) + suffix), check / (db.name + suffix))
                            with sqlite3.connect((check / db.name).as_uri() + '?mode=ro', uri=True) as conn:
                                if conn.execute('PRAGMA quick_check').fetchall() != [('ok',)]:
                                    raise ValueError('SQLite quick_check failed')
                                agents = conn.execute('select id,value from agents').fetchall()
                                tables = {
                                    row[0]
                                    for row in conn.execute(
                                        "select name from sqlite_master where type='table'"
                                    )
                                }
                                if 'meta' in tables:
                                    meta = {
                                        k: json.loads(v)
                                        for k, v in conn.execute('select key,value from meta')
                                    }
                                    if meta.get('lifecycle') not in ('ended', 'interrupted'):
                                        issues.append('runtime lifecycle is not finalized')
                                if (
                                    'actions' in tables
                                    and conn.execute(
                                        "select count(*) from actions where status in ('pending','running','uncertain')"
                                    ).fetchone()[0]
                                ):
                                    issues.append('unresolved physical actions')
                    except (sqlite3.Error, ValueError) as error:
                        issues.append('database unreadable: ' + type(error).__name__)
                for actor, value in agents:
                    try:
                        agent = json.loads(value)
                        if not isinstance(agent, dict):
                            raise ValueError('Agent must be an object')
                    except (TypeError, ValueError):
                        issues.append(str(actor) + ': unreadable role metadata')
                        continue
                    if agent.get('kind') == 'manager':
                        continue
                    tid = agent.get('thread_id')
                    if not isinstance(tid, str) or not ID.fullmatch(tid):
                        issues.append(str(actor) + ': missing or invalid session id')
                        continue
                    config = history_directory(run) if harness == 'claude' else run / 'private/harness'
                    _, matches = native_matches(harness, run, home, tid)
                    native_queries.append((run, home, tid, matches))
                    if len(matches) != 1:
                        issues.append(
                            str(actor) + ': expected one native session, found ' + str(len(matches))
                        )
                        continue
                    base = (
                        Path('sessions') / job['model_entry'] if job.get('model_entry') else Path('sessions')
                    )
                    rel = base / job['case_id'] / session_name(tid, matches[0])
                    checksum = copy_stable(matches[0], temporary / rel)
                    hashes[rel.as_posix()] = checksum
                    native_sources[matches[0]] = checksum
                    roles.append(
                        {
                            'actor': actor,
                            'kind': agent.get('kind'),
                            'thread_id': tid,
                            'delegation_id': agent.get('delegation_id'),
                            'delegation_state': agent.get('delegation_state'),
                            'parent': meta.get('delegations', {})
                            .get(agent.get('delegation_id'), {})
                            .get('parent', agent.get('parent')),
                            'session': rel.as_posix(),
                            'sha256': checksum,
                        }
                    )
                    if harness == 'claude':
                        original_rel = (
                            Path('batch')
                            / run.relative_to(batch_path)
                            / native_config
                            / matches[0].relative_to(config)
                        )
                        hashes[original_rel.as_posix()] = copy_stable(matches[0], temporary / original_rel)
                        roles[-1]['native_session'] = original_rel.as_posix()
                    # Native Claude may keep session-linked auxiliary transcripts.
                    # Preserve these too, without copying configuration or auth files.
                    sidecars = session_stem(matches[0])
                    if harness == 'claude':
                        native_directories[sidecars] = sorted(_files(sidecars))
                        for extra in native_directories[sidecars]:
                            extra_rel = rel.parent / tid / extra.relative_to(sidecars)
                            hashes[extra_rel.as_posix()] = copy_stable(extra, temporary / extra_rel)
                            native_sources[extra] = hashes[extra_rel.as_posix()]
                            original_rel = (
                                Path('batch')
                                / run.relative_to(batch_path)
                                / native_config
                                / extra.relative_to(config)
                            )
                            hashes[original_rel.as_posix()] = copy_stable(extra, temporary / original_rel)
                if not roles:
                    issues.append('no recorded policy role sessions')
                # Snapshot anchors are not policy actors, but are required to
                # reconstruct and audit the native lineage of their delegates.
                for delegation_id, delegation in meta.get('delegations', {}).items():
                    tid = delegation.get('snapshot_thread_id')
                    if tid is None:
                        continue  # no snapshot was taken for this delegation
                    if not isinstance(tid, str) or not ID.fullmatch(tid):
                        issues.append(str(delegation_id) + ': invalid snapshot session id')
                        continue
                    native_root, matches = native_matches(harness, run, home, tid)
                    native_queries.append((run, home, tid, matches))
                    if len(matches) != 1:
                        issues.append(
                            str(delegation_id) + ': expected one snapshot session, found ' + str(len(matches))
                        )
                        continue
                    base = (
                        Path('sessions') / job['model_entry'] if job.get('model_entry') else Path('sessions')
                    )
                    rel = base / job['case_id'] / session_name(tid, matches[0])
                    checksum = copy_stable(matches[0], temporary / rel)
                    hashes[rel.as_posix()] = checksum
                    native_sources[matches[0]] = checksum
                    snapshot_sessions.append(
                        {
                            'delegation_id': delegation_id,
                            'thread_id': tid,
                            'session': rel.as_posix(),
                            'sha256': checksum,
                        }
                    )
                    if harness == 'claude':
                        native_rel = (
                            Path('batch')
                            / run.relative_to(batch_path)
                            / native_config
                            / matches[0].relative_to(native_root)
                        )
                        hashes[native_rel.as_posix()] = copy_stable(matches[0], temporary / native_rel)
                        snapshot_sessions[-1]['native_session'] = native_rel.as_posix()
                        sidecars = session_stem(matches[0])
                        native_directories[sidecars] = sorted(_files(sidecars))
                        for extra in native_directories[sidecars]:
                            extra_rel = rel.parent / tid / extra.relative_to(sidecars)
                            hashes[extra_rel.as_posix()] = copy_stable(extra, temporary / extra_rel)
                            native_sources[extra] = hashes[extra_rel.as_posix()]
                            original_rel = (
                                Path('batch')
                                / run.relative_to(batch_path)
                                / native_config
                                / extra.relative_to(native_root)
                            )
                            hashes[original_rel.as_posix()] = copy_stable(extra, temporary / original_rel)
                if harness == 'claude':
                    launch_file = run / 'private/inputs/claude.json'
                    launch = load(launch_file) if launch_file.is_file() else {}
                    if launch.get('model_entry', {}).get('auth_mode') == 'native_login':
                        relative = (
                            Path('batch')
                            / run.relative_to(batch_path)
                            / run_layout.path(run, 'collected_sessions').relative_to(run)
                        )
                        marker = temporary / relative
                        if not marker.exists():
                            write_json(
                                marker,
                                {
                                    'schema': 'roboteam.claude-collected-sessions.v1',
                                    'writers_stopped': True,
                                    'session_ids': [
                                        entry['thread_id'] for entry in roles + snapshot_sessions
                                    ],
                                },
                            )
                        hashes[relative.as_posix()] = digest(marker)
                results = run / 'private/outputs'
                if not any(
                    (results / name).is_file()
                    for name in ('evaluation.json', 'interruption-evaluation.json', 'budget-cutoff.json')
                ):
                    issues.append('no final/interruption evaluation')
                if status != 'closed':
                    issues.append('job needs review: ' + status)
                copied_run = temporary / 'batch' / run.relative_to(batch_path)
                issues.extend(motion_inventory(copied_run))
                seal = copied_run / 'private/outputs/seal.json'
                if seal.is_file():
                    try:
                        sealed = load(seal)
                        if sealed.get('sealed') is not True or sealed.get('unresolved_action_ids'):
                            issues.append('seal incomplete or physical actions unresolved')
                    except (ValueError, AttributeError):
                        issues.append('seal metadata unreadable')
                run_settings = run / 'private/inputs/run.json'
                try:
                    cfg = load(run_settings) if run_settings.is_file() else {}
                    if not isinstance(cfg, dict):
                        raise ValueError('Harness must be an object')
                except ValueError:
                    cfg = {}
                    issues.append('harness metadata unreadable')
                rows.append(
                    {
                        'case_id': job['case_id'],
                        'model_entry': job.get('model_entry'),
                        'status': status,
                        'harness': harness,
                        'system': cfg.get('system'),
                        'model': cfg.get('model'),
                        'lifecycle': meta.get('lifecycle'),
                        'run': (Path('batch') / run.relative_to(batch_path)).as_posix(),
                        'roles': roles,
                        'snapshot_sessions': snapshot_sessions,
                        'issues': issues,
                    }
                )
            # Check all original evidence again, including files outside sessions.
            if list(_files(batch_path, tolerated)) != initial_files or load(state_path) != state:
                raise ValueError('Batch changed while collecting')
            for path in initial_files:
                if digest(path) != hashes[(Path('batch') / path.relative_to(batch_path)).as_posix()]:
                    raise ValueError('Batch evidence changed: ' + str(path))
            for path, checksum in native_sources.items():
                if digest(path) != checksum:
                    raise ValueError('Native session changed: ' + str(path))
            for directory, initial in native_directories.items():
                if sorted(_files(directory)) != initial:
                    raise ValueError('Native auxiliary session inventory changed: ' + str(directory))
            for run, home, tid, initial in native_queries:
                if native_matches(harness, run, home, tid)[1] != initial:
                    raise ValueError('Native session lookup changed: ' + tid)
            report = {
                'schema': 'roboteam.policy-collection.v1',
                'harness': harness,
                'batch_status': state['status'],
                'source_batch': str(batch_path),
                'writers_stopped': True,
                'job_count': len(rows),
                'jobs': rows,
                'complete': not any(row['issues'] for row in rows),
                'files': hashes,
                'note': 'Private stopped-run evidence; completeness is not score validity. CLI configuration/credentials excluded. Embedded paths preserved.',
            }
            (temporary / 'collection.json').write_text(
                json.dumps(report, ensure_ascii=False, indent=2) + '\n'
            )
        if output.exists():
            raise FileExistsError(output)
        temporary.rename(output)
        return report
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = collect_batch(args.batch, args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['complete'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
