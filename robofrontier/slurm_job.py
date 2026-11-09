"""Queue frozen source, execute on node-local storage, and return stopped evidence.

The batch shell outlives its srun step. No function opens SQLite. API credentials
travel in the environment. Subscription caches are loaded late under a private
stream lease, never in source snapshots or returned evidence.
"""
import argparse
from contextlib import contextmanager
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import shlex
import shutil
import stat
import subprocess
import sys

from . import run_layout
import tarfile
import tempfile
import time
import zipfile

from .configuration import ROOT, validate_configuration
from .run_setup import write_json


def checksum(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _copy_verified(source, destination):
    source, destination = Path(source), Path(destination)
    if source.is_symlink() or not source.is_file():
        raise ValueError('A regular file is required: ' + str(source))
    expected = checksum(source)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open('rb') as incoming, destination.open('xb') as outgoing:
        shutil.copyfileobj(incoming, outgoing)
        outgoing.flush()
        os.fsync(outgoing.fileno())
    if checksum(destination) != expected or checksum(source) != expected:
        raise ValueError('File changed or was corrupted during transfer: ' + str(source))
    return expected


def _stopped_files(root, relative, issues, *, prune_config=True):
    """Regular files below `root` for the stopped-evidence fallback; never raises.

    Links are never followed or copied and nonregular files are never opened: each is
    recorded in `issues` (a link with its link text) and the walk goes on. With
    `prune_config`, CLI configuration folders are skipped except their native JSONL
    transcripts (projects/**/*.jsonl), as in the original fallback."""
    if root.is_symlink():
        issues.append({'path': relative(root), 'issue': 'symlink', 'link': _link_text(root)})
        return
    def walk_error(error):
        issues.append({'path': relative(Path(error.filename)) if error.filename else None,
                       'issue': 'unreadable', 'error': type(error).__name__})
    for parent, dirs, files in os.walk(root, followlinks=False, onerror=walk_error):
        parent = Path(parent)
        kept = []
        for name in sorted(dirs):
            path = parent/name
            if path.is_symlink():
                issues.append({'path': relative(path), 'issue': 'symlink', 'link': _link_text(path)})
            elif prune_config and (name == 'claude-config' and parent.name == 'private' or
                                   name == 'config' and parent.name == 'engine' and parent.parent.name == 'private'):
                # A Claude home can contain credentials beside its projects.
                projects = path/'projects'
                if projects.is_dir() or projects.is_symlink():
                    yield from (file for file in _stopped_files(projects, relative, issues, prune_config=False)
                                if file.name.endswith('.jsonl'))
            elif not (prune_config and (name == 'claude-config' or name == 'config' and parent.name == 'engine')):
                kept.append(name)
        dirs[:] = kept
        for name in sorted(files):
            if name == '.DS_Store': continue
            path = parent/name
            try:
                mode = os.lstat(path).st_mode
            except OSError as error:
                issues.append({'path': relative(path), 'issue': 'unreadable', 'error': type(error).__name__})
                continue
            if stat.S_ISLNK(mode):
                issues.append({'path': relative(path), 'issue': 'symlink', 'link': _link_text(path)})
            elif not stat.S_ISREG(mode):
                issues.append({'path': relative(path), 'issue': 'nonregular'})
            else:
                yield path


def _link_text(path):
    try: return os.readlink(path)
    except OSError: return None


def _extract_source(archive, output):
    with tarfile.open(archive) as source:
        seen = set()
        for member in source.getmembers():
            path = PurePosixPath(member.name)
            if (path.is_absolute() or '..' in path.parts or not path.parts or
                    '\\' in member.name or member.name in seen or
                    not (member.isfile() or member.isdir())):
                raise ValueError('Unsafe source archive member')
            seen.add(member.name)
        source.extractall(output, filter='data')


def _verify_submission(folder):
    folder = Path(folder).resolve()
    manifest = json.loads((folder/'submission.json').read_text())
    if manifest.get('schema') != 'robofrontier.slurm-submission.v1':
        raise ValueError('Unknown Slurm submission schema')
    for name, expected in manifest['sha256'].items():
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or not path.parts:
            raise ValueError('Unsafe submission file path')
        file = folder/name
        if file.is_symlink() or checksum(file) != expected:
            raise ValueError('Slurm submission changed: ' + name)
    config = json.loads((folder/'effective-config.json').read_text())
    validate_configuration(config)
    return manifest, config


def queue_command(slurm, folder):
    command = ['sbatch', '--parsable', '--nodes=1', '--ntasks=1',
               '--cpus-per-task='+str(slurm['cpus_per_task']), '--mem='+str(slurm['memory_gib'])+'G',
               '--time='+str(math.ceil(slurm['time_limit_s']/60)),
               '--signal=B:USR1@'+str(slurm['stop_warning_s']),
               '--export=ALL', '--output='+str(Path(folder)/'slurm-%j.log')]
    if slurm['gpus']:
        command.append('--gpus='+str(slurm['gpus']))
    if slurm.get('auth_mode') == 'subscription':
        stream = hashlib.sha256(slurm['credential_store'].encode()).hexdigest()[:24]
        command.extend(['--job-name=rf-auth-'+stream, '--dependency=singleton'])
    for field in ('partition', 'account', 'qos'):
        if slurm[field]:
            command.append('--'+field+'='+slurm[field])
    return [*command, str(Path(folder)/'job.sbatch')]


def _script(folder, python, slurm):
    q = shlex.quote
    scratch = q(slurm["scratch_root"]) if slurm["scratch_root"] else '"${SLURM_TMPDIR:?Configure node-local SLURM_TMPDIR or slurm.scratch_root}"'
    return f'''#!/bin/bash
set -eu
umask 077
submission={q(str(folder))}
python={q(str(python))}
scratch_root={scratch}
local_run="$scratch_root/robofrontier-${{SLURM_JOB_ID}}"
export OMP_NUM_THREADS="${{OMP_NUM_THREADS:-1}}"
export OPENBLAS_NUM_THREADS="${{OPENBLAS_NUM_THREADS:-1}}"
cd "$submission/launcher"
"$python" -m robofrontier.slurm_job stage "$submission" "$local_run"
mkdir "$local_run/tmp"
export TMPDIR="$local_run/tmp"
unset CODEX_HOME CLAUDE_CONFIG_DIR
request_stop() {{
  (cd "$local_run/source" && "$python" -m robofrontier.slurm_job stop "$local_run") || true
}}
trap request_stop USR1 TERM INT
cd "$local_run/source"
# Slurm tracks detached CLI descendants too. A leftover owner after step-leader
# exit is closed by Slurm after 120 seconds and remains incomplete evidence.
srun --nodes=1 --ntasks=1 --wait=120 "$python" -m robofrontier.slurm_job execute "$local_run" &
step=$!
step_status=0
while kill -0 "$step" 2>/dev/null; do
  "$python" -m robofrontier.slurm_job snapshot "$local_run" "$submission" || true
  sleep 5 &
  wait $! || true
done
wait "$step" || step_status=$?
"$python" -m robofrontier.slurm_job stage-out "$local_run" "$submission" --step-exit-code "$step_status"
exit "$step_status"
'''


def submit(config, output, *, queue=False, engineering=False, root=ROOT):
    """Freeze a single-use submission; optionally submit it to the queue."""
    from .cli import _catalog, plan
    from scripts.benchmark_handoff import ensure_asset_archive
    validate_configuration(config)
    plan(config)
    if config['render']['device'] == 'native':
        raise ValueError('Slurm requires Linux nvidia or cpu rendering')
    if config['render']['device'] == 'nvidia' and config['slurm']['gpus'] < 1:
        raise ValueError('NVIDIA rendering requires a GPU allocation')
    subscription = config['slurm'].get('auth_mode') == 'subscription'
    if not subscription and (config['runtime']['codex_home_scope'] != 'task' or config['runtime']['codex_home']):
        raise ValueError('Slurm assigns node-local task homes; leave runtime.codex_home empty and select task scope')
    if not config['evidence']['auto_collect'] or not config['evidence']['auto_archive']:
        raise ValueError('Slurm requires automatic collection and ZIP archiving')
    policy = config['policy']
    if policy['engine'] == 'claude' and not engineering:
        raise ValueError('Claude Slurm execution requires --engineering')
    selected = _catalog(config)['profiles'][policy['profile']]
    if subscription:
        if selected.get('provider') != 'openai' or selected.get('env_key'):
            raise ValueError('Subscription Slurm requires an exact native ChatGPT profile without API keys')
        store = Path(config['slurm']['credential_store']).resolve()
        for excluded in (Path(root).resolve(), Path(output).resolve()):
            if store.is_relative_to(excluded) or excluded.is_relative_to(store):
                raise ValueError('Keep the credential store outside checkouts and submission/evidence directories')
        if config['slurm'].get('egress_mode') == 'mac-ssh':
            relay = Path(config['slurm']['egress_root']).resolve()
            for excluded in (Path(root).resolve(), Path(output).resolve(), store):
                if relay.is_relative_to(excluded) or excluded.is_relative_to(relay):
                    raise ValueError('Keep egress state outside checkouts, submissions and credential directories')
    elif not selected.get('env_key') or (selected.get('auth_mode') == 'oauth_token' and policy['engine'] != 'claude'):
        raise ValueError('The Slurm entry supports API credentials and the Claude subscription token only')
    if not subscription and config['slurm'].get('egress_mode') == 'mac-ssh':
        relay = Path(config['slurm']['egress_root']).resolve()
        for excluded in (Path(root).resolve(), Path(output).resolve()):
            if relay.is_relative_to(excluded) or excluded.is_relative_to(relay):
                raise ValueError('Keep egress state outside checkouts and submission/evidence directories')
    root, output = Path(root).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new submission directory')
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root, text=True):
        raise ValueError('Commit tracked changes before freezing a Slurm source snapshot')
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    receipt = root/'runs/engineering/model-compatibility'/policy['profile']/'report.json'
    if policy['engine'] == 'codex' and (not receipt.is_file() or not json.loads(receipt.read_text()).get('passed')):
        raise ValueError('Run the matching explicit provider preflight before preparing a Slurm submission')
    if subscription:
        from .codex.job_engine import fingerprint
        if json.loads(receipt.read_text()).get('job_gateway_sha256') != fingerprint():
            raise ValueError('Run the matching job-gateway subscription preflight before submission')
    archive = ensure_asset_archive(root)
    python = Path(sys.executable).absolute()  # Preserve the venv symlink and site-packages.
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rf-submission-', dir=output.parent) as temporary:
        staged = Path(temporary)/'submission'
        staged.mkdir(mode=0o700)
        subprocess.run(['git', 'archive', '--format=tar', '--output='+str(staged/'source.tar'), commit], cwd=root, check=True)
        with tempfile.TemporaryDirectory(prefix='rf-source-check-') as check:
            _extract_source(staged/'source.tar', Path(check))
            if (Path(check)/'.env').exists():
                raise ValueError('A source snapshot must not contain .env')
            # Freeze the staging implementation too: the login checkout may
            # change while this submission is waiting in the queue.
            shutil.copytree(Path(check)/'robofrontier', staged/'launcher/robofrontier')
        files = {'source.tar': checksum(staged/'source.tar')}
        for file in sorted((staged/'launcher').rglob('*')):
            if file.is_file():
                files[file.relative_to(staged).as_posix()] = checksum(file)
        files['policy-assets.tar.gz'] = _copy_verified(archive, staged/'policy-assets.tar.gz')
        write_json(staged/'effective-config.json', config)
        files['effective-config.json'] = checksum(staged/'effective-config.json')
        if policy['engine'] == 'codex':
            files['provider-report.json'] = _copy_verified(receipt, staged/'provider-report.json')
        (staged/'job.sbatch').write_text(_script(output, python, config['slurm']))
        files['job.sbatch'] = checksum(staged/'job.sbatch')
        write_json(staged/'submission.json', {'schema': 'robofrontier.slurm-submission.v1',
            'commit': commit, 'sha256': files, 'engine': policy['engine'], 'engineering': engineering,
            'credential_env': selected.get('env_key'), 'auth_mode': 'subscription' if subscription else 'api',
            'model_calls_during_preparation': 0,
            'python': str(python), 'status': 'prepared_not_queued'})
        staged.rename(output)
    if queue:
        if platform.system() != 'Linux':
            raise ValueError('Submission prepared; run sbatch on the Linux cluster: ' + str(output))
        job_id = subprocess.check_output(queue_command(config["slurm"], output), cwd=root, text=True).strip().split(";")[0]
        if not job_id.isdigit():
            raise ValueError('Unexpected sbatch response; inspect the queue before submitting again')
        write_json(output/'queue.json', {'job_id': job_id, 'queued_at': time.time()})
    return {'submission': str(output), 'queued': queue, 'model_calls_during_preparation': 0,
            **({'job_id': job_id} if queue else {})}


def _local_storage(path):
    kind = subprocess.check_output(['stat', '-f', '-c', '%T', str(path)], text=True).strip()
    if kind not in ('ext2/ext3', 'xfs', 'btrfs', 'tmpfs', 'overlayfs', 'zfs'):
        raise ValueError('Node-local scratch is required; detected filesystem: ' + kind)
    return kind


def stage(submission, local):
    submission, local = Path(submission).resolve(), Path(local).resolve()
    manifest, config = _verify_submission(submission)
    if platform.system() != 'Linux' or not os.environ.get('SLURM_JOB_ID'):
        raise ValueError('Stage must run in a Linux Slurm allocation')
    if local.exists():
        raise ValueError('Local directory exists; never restart a physical run')
    kind = _local_storage(local.parent)
    local.mkdir(mode=0o700)
    source = local/'source'
    source.mkdir()
    _extract_source(submission/'source.tar', source)
    asset = source/'runs/asset-cache'/(manifest['sha256']['policy-assets.tar.gz']+'.tar.gz')
    _copy_verified(submission/'policy-assets.tar.gz', asset)
    if config['policy']['engine'] == 'codex':
        receipt = source/'runs/engineering/model-compatibility'/config['policy']['profile']/'report.json'
        _copy_verified(submission/'provider-report.json', receipt)
    write_json(local/'config.json', config)
    write_json(local/'local-job.json', {'schema': 'robofrontier.slurm-local.v1', 'submission': str(submission),
        'job_id': os.environ['SLURM_JOB_ID'], 'filesystem': kind, 'engineering': manifest['engineering'],
        'commit': manifest['commit'], 'status': 'staged'})
    return {'local': str(local), 'status': 'staged'}


def execute(local):
    from .cli import prepare, run
    local = Path(local).resolve()
    if ROOT != local/'source':
        raise ValueError('Execute must import the staged node-local source')
    document = json.loads((local/'local-job.json').read_text())
    config = json.loads((local/'config.json').read_text())
    path = local/'execution-result.json'
    result = None
    try:
        with subscription_environment(config, local, on_failure=lambda: request_stop(local)):
            prepare(ROOT/'runs/policy/batch', config)
            if (local/'STOP').exists():
                request_stop(local)
                result = {'status': 'stopped_before_start'}
            else:
                result = run(ROOT/'runs/policy/batch', engineering=document['engineering'])
            # Persist the result (naming any verified archive) before leaving the managed
            # route/credential context, whose exit raises when its fence fired.
            write_json(path, result)
    except Exception as error:
        if result is not None:
            # The kind only; a message could carry route or credential details.
            write_json(path, {**result, 'context_failure': type(error).__name__})
        raise
    return result


@contextmanager
def subscription_environment(config, local, *, on_failure):
    """Seed only after allocation and hold custody until native writers close.

    Without a subscription store (Claude's token travels in the job environment) only a
    configured Mac route is admitted, with the same pause, fencing and environment.
    """
    if config['slurm'].get('auth_mode') != 'subscription':
        if config['slurm'].get('egress_mode', 'direct') != 'mac-ssh':
            yield
            return
        with routed_environment(config, local, on_failure=on_failure):
            yield
        return
    if platform.system() != 'Linux' or not os.environ.get('SLURM_JOB_ID'):
        raise ValueError('Job-scoped subscription execution requires a Linux Slurm allocation')
    from .slurm_auth import CredentialLease, BorrowedAccess
    from .slurm_proxy import environment as egress_environment
    local = Path(local).resolve()
    store = Path(config['slurm']['credential_store']).absolute()
    borrowed = os.environ.get('ROBOFRONTIER_BORROWED_AUTH')
    if borrowed and borrowed != str(store/'current.json'):
        raise ValueError('Borrowed access must follow the configured canonical store')
    for excluded in (ROOT.resolve(), local):
        if store.is_relative_to(excluded) or excluded.is_relative_to(store):
            raise ValueError('Credential store must be separate from source, scratch and evidence')
    private = local/'engine'
    private.mkdir(mode=0o700, exist_ok=False)
    original = dict(os.environ)
    if config['slurm'].get('egress_mode') == 'mac-ssh':
        relay = Path(config['slurm']['egress_root']).absolute()
        for excluded in (ROOT.resolve(), local, store):
            if relay.is_relative_to(excluded) or excluded.is_relative_to(relay):
                raise ValueError('Keep egress state separate from source, scratch and credentials')
    try:
        # No fallback into API billing, personal login homes or CLI overrides.
        for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'OPENAI_BASE_URL',
                    'CODEX_HOME', 'ROBOFRONTIER_CODEX_GATEWAY', 'ROBOFRONTIER_CODEX_TASK'):
            os.environ.pop(key, None)
        os.environ.update(CODEX_HOME=str(private/'codex'),
                          ROBOFRONTIER_JOB_PRIVATE_ROOT=str(private),
                          ROBOFRONTIER_CREDENTIAL_STORE=str(store))
        def egress_failed():
            (private/'EGRESS_ERROR').touch(mode=0o600)
            on_failure()
        with egress_environment(config, on_failure=egress_failed):
            with (BorrowedAccess if borrowed else CredentialLease)(store, private/'codex') as lease:
                def failed():
                    (private/'CREDENTIAL_ERROR').touch(mode=0o600)
                    on_failure()
                lease.watch(failed)
                yield lease
    finally:
        os.environ.clear()
        os.environ.update(original)


@contextmanager
def routed_environment(config, local, *, on_failure):
    """Admit the allocation's Mac route for a credential carried in the environment."""
    if platform.system() != 'Linux' or not os.environ.get('SLURM_JOB_ID'):
        raise ValueError('Managed egress requires a Linux Slurm allocation')
    from .slurm_proxy import environment as egress_environment
    local = Path(local).resolve()
    relay = Path(config['slurm']['egress_root']).absolute()
    for excluded in (ROOT.resolve(), local):
        if relay.is_relative_to(excluded) or excluded.is_relative_to(relay):
            raise ValueError('Keep egress state separate from source and scratch')
    private = local/'engine'
    private.mkdir(mode=0o700, exist_ok=False)
    original = dict(os.environ)
    try:
        os.environ['ROBOFRONTIER_JOB_PRIVATE_ROOT'] = str(private)
        def egress_failed():
            (private/'EGRESS_ERROR').touch(mode=0o600)
            on_failure()
        with egress_environment(config, on_failure=egress_failed):
            yield
    finally:
        os.environ.clear()
        os.environ.update(original)


def request_stop(local):
    local = Path(local).resolve()
    (local/'STOP').touch()
    batch = local/'source/runs/policy/batch'
    if batch.is_dir():
        stops = [run_layout.batch_path(batch, 'stop')]
        if (batch/'batch.json').exists():
            runs = [Path(job['run_directory']).resolve() for job in json.loads((batch/'batch.json').read_text())['jobs']]
            if any(not run.is_relative_to(batch) or run == batch for run in runs):
                raise ValueError('Invalid local run directory')
            stops += [run_layout.path(run, 'stop') for run in runs]
        for stop in stops:
            stop.parent.mkdir(parents=True, exist_ok=True)
            stop.touch()
    return {'stop_requested': True}


def snapshot(local, submission):
    """Publish atomic JSON only, without opening any active database."""
    state = {'updated_at': time.time(), 'job_id': os.environ.get('SLURM_JOB_ID'), 'status': 'starting'}
    batch = Path(local)/'source/runs/policy/batch'
    for name, path in (('batch.json', batch/'batch.json'),
                       ('engineering-status.json', run_layout.batch_path(batch, 'engineering_status') if batch.is_dir() else None)):
        if path is not None and path.is_file():
            state[name] = json.loads(path.read_text())
            state['status'] = state[name]['status']
    write_json(Path(submission)/'status.json', state)
    return state


def _writer_locks(local):
    """Every lock path a batch or run layout defines, for each layout version.

    Only these fixed paths: a file a policy names world.lock in its workspace is not a lock."""
    batch = (Path(local)/'source/runs/policy/batch').resolve()
    locks = {batch/layout[key] for layout in run_layout.BATCH_LAYOUTS.values()
             for key in ('supervisor_lock', 'engineering_lock')}
    runs = set()
    try:
        jobs = json.loads((batch/'batch.json').read_text())['jobs'] if (batch/'batch.json').is_file() else []
        runs |= {Path(job['run_directory']).resolve() for job in jobs}
    except (OSError, ValueError, KeyError, TypeError):
        pass
    # Runs live at <profile>/<case>/; also find them when batch.json is missing or unreadable.
    if batch.is_dir() and not batch.is_symlink():
        for profile in batch.iterdir():
            if profile.is_dir() and not profile.is_symlink():
                runs |= {case for case in profile.iterdir() if case.is_dir() and not case.is_symlink()}
    for run in runs:
        if not run.is_relative_to(batch) or run == batch:
            continue
        locks |= {run/layout[key] for layout in run_layout.LAYOUTS.values() for key in ('world_lock', 'engineering_lock')}
    return sorted(locks)


@contextmanager
def _assert_no_writers(local):
    """Refuse while any writer holds its lock; yield issues for lock paths that are not files."""
    import contextlib
    issues = []
    with contextlib.ExitStack() as stack:
        for path in _writer_locks(local):
            try:
                # Never block on a FIFO or follow a link planted at a lock path.
                descriptor = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
            except FileNotFoundError:
                continue
            except OSError as error:
                issues.append({'path': str(path), 'issue': 'lock not opened', 'error': type(error).__name__})
                continue
            lock = stack.enter_context(os.fdopen(descriptor, 'r'))
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                issues.append({'path': str(path), 'issue': 'nonregular lock'})
                continue
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise ValueError('Writer still live; refusing stage-out: ' + str(path)) from None
        yield issues


def stage_out(local, submission, step_exit_code):
    """Return one evidence ZIP, or raw stopped evidence when collection failed.

    srun must have returned. No source deletion, auth/config transfer, physical
    replay, or success certification is performed here.
    """
    with _assert_no_writers(local) as lock_issues:
        return _stage_out_stopped(local, submission, step_exit_code, lock_issues)


def _stage_out_stopped(local, submission, step_exit_code, lock_issues=()):
    local, submission = Path(local).resolve(), Path(submission).resolve()
    _verify_submission(submission)
    output = submission/'results'
    if output.exists():
        raise ValueError('Stage-out destination exists; inspect it rather than overwriting')
    result_path = local/'execution-result.json'
    result = json.loads(result_path.read_text()) if result_path.exists() else {}
    source = local/'source'
    archive = Path(result['archive']).resolve() if result.get('archive') else None
    if archive and (not archive.is_relative_to(source/'runs/exports') or not archive.is_file()):
        raise ValueError('Unexpected evidence archive location')
    if archive:
        with zipfile.ZipFile(archive) as check:
            if 'manifest.json' not in check.namelist() or check.testzip() is not None:
                raise ValueError('Evidence ZIP failed its stage-out integrity check')
    with tempfile.TemporaryDirectory(prefix='.rf-stage-out-', dir=submission) as temporary:
        staged = Path(temporary)/'results'
        staged.mkdir(mode=0o700)
        files, issues = {}, list(lock_issues)
        def copy(file, relative):
            files[relative] = _copy_verified(file, staged/relative)
        def keep(file, relative):
            # Best effort per file: one unreadable, vanished or over-quota file is recorded
            # and the rest of the stopped evidence is still returned.
            try:
                copy(file, relative)
            except (OSError, ValueError) as error:
                files.pop(relative, None)
                try: (staged/relative).unlink(missing_ok=True)
                except OSError: pass
                issues.append({'path': relative, 'issue': 'not copied', 'error': type(error).__name__})
        if archive:
            copy(archive, 'evidence.zip')
        else:
            # Retain the only motion/trace copy if automatic collection failed. Only
            # native JSONL transcripts of a CLI configuration enter this fallback.
            name = lambda file: file.relative_to(source).as_posix()
            for base in (source/'runs/policy', source/'runs/state-assets'):
                if base.exists() or base.is_symlink():
                    for file in _stopped_files(base, name, issues):
                        keep(file, name(file))
            codex = source/'.robofrontier/codex'
            if codex.is_dir() and not codex.is_symlink():
                for home in sorted(codex.iterdir()):
                    sessions = home/'sessions'
                    if home.is_symlink():
                        issues.append({'path': name(home), 'issue': 'symlink', 'link': _link_text(home)})
                    elif sessions.exists() or sessions.is_symlink():
                        for file in _stopped_files(sessions, name, issues, prune_config=False):
                            keep(file, 'native-sessions/'+file.relative_to(home.parent).as_posix())
        for file in (local/'local-job.json', result_path):
            if file.is_file():
                keep(file, file.name)
        report = {'schema': 'robofrontier.slurm-stage-out.v1', 'sha256': files,
                  'step_exit_code': step_exit_code, 'returned_at': time.time(),
                  'status': 'collected' if (archive and step_exit_code == 0 and result.get('status') != 'needs_review'
                                            and result.get('collection_complete') and not issues
                                            and not result.get('context_failure')) else 'needs_review',
                  **({'context_failure': result['context_failure']} if result.get('context_failure') else {}),
                  'task_status': result.get('status'), 'raw_fallback': archive is None,
                  'issues': issues,
                  'node_local_source_retained': str(local),
                  'task_success': 'See independent per-task evaluation'}
        write_json(staged/'stage-out.json', report)
        staged.rename(output)
    write_json(submission/'status.json', {k: v for k, v in report.items() if k != 'sha256'})
    return {'results': str(output), **report}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('stage', 'snapshot', 'stage-out'):
        p = sub.add_parser(name)
        if name == 'stage':
            p.add_argument('submission', type=Path)
            p.add_argument('local', type=Path)
        else:
            p.add_argument('local', type=Path)
            p.add_argument('submission', type=Path)
            if name == 'stage-out':
                p.add_argument('--step-exit-code', type=int, required=True)
    for name in ('execute', 'stop'):
        sub.add_parser(name).add_argument('local', type=Path)
    args = parser.parse_args(argv)
    if args.command == 'stage':
        result = stage(args.submission, args.local)
    elif args.command == 'execute':
        result = execute(args.local)
    elif args.command == 'stop':
        result = request_stop(args.local)
    elif args.command == 'snapshot':
        result = snapshot(args.local, args.submission)
    else:
        result = stage_out(args.local, args.submission, args.step_exit_code)
    print(json.dumps(result, allow_nan=False))


if __name__ == '__main__':
    main()
