"""Trusted job-level native process lifecycle and task-channel manifest.

No scheduler calls or credential reads. Native refresh custody is external;
an explicitly admitted access-only harness can follow its canonical generation.
Each task keeps a distinct frozen filesystem profile and runtime database.
"""

import hashlib
import json
import os
import re
import signal
import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

from roboteam.runtime.run.setup import write_json
from roboteam.runtime.sandbox import policy_env
from roboteam.runtime.sandbox.access import mode
from roboteam.tasks.config import ROOT

BACKEND = 'slurm-managed-v1'
PINNED_CLI = re.compile(r'^ARG CODEX_VERSION=(\S+)$', re.M)
CLI_TIMEOUT_S = 30


def fingerprint():
    names = (
        'harness/codex/job_harness.py',
        'harness/codex/host/job_gateway.js',
        'harness/codex/host/gateway_rpc.js',
        'harness/codex/file_sandbox.py',
        'harness/codex/tool_worker.py',
        'harness/codex/tool_backend.py',
        'harness/codex/host/rpc.js',
        'harness/codex/host/policy_host.js',
        'launch/codex_batch.py',
        'harness/codex/host/tool_broker.js',
        'harness/codex/launch.py',
        'launch/slurm/auth.py',
        'launch/slurm/job.py',
        'runtime/sandbox/access.py',
        'launch/slurm/proxy.py',
        'runtime/time/egress_pause.py',
        'runtime/world/service.py',
        'harness/codex/host/borrowed_auth.js',
    )
    digest = hashlib.sha256(BACKEND.encode())
    for name in names:
        digest.update(name.encode() + b'\0' + (ROOT / 'roboteam' / name).read_bytes() + b'\0')
    return digest.hexdigest()


def task_id(run):
    return hashlib.sha256(str(Path(run).resolve()).encode()).hexdigest()[:24]


def _common_args(launch):
    args, common = launch['args'], []
    if len(args) % 2 or any(args[i] != '-c' for i in range(0, len(args), 2)):
        raise ValueError('Job harness requires explicit native configuration overrides')
    for key, value in zip(args[::2], args[1::2]):
        name = value.split('=', 1)[0]
        if name == 'default_permissions' or name.startswith('permissions.') or name == 'model_catalog_json':
            continue
        common.extend([key, value])
    return common


def build_manifest(jobs, control, private_root, credential_store, *, preflight=False, pause_file=None):
    control, private_root = Path(control).resolve(), Path(private_root).resolve()
    tasks, args, launch, catalog = [], None, None, None
    for job in jobs:
        run = Path(job['run_directory']).resolve()
        if (pause_file or os.environ.get('ROBOTEAM_EGRESS_PAUSE_FILE')) and not preflight:
            try:
                frozen = json.loads((run / 'private/inputs/manifest.json').read_text())['source_sha256']
                required = (
                    'roboteam/runtime/time/egress_pause.py',
                    'roboteam/runtime/world/service.py',
                    'roboteam/runtime/world/pipeline.py',
                    'roboteam/runtime/run/cli.py',
                    'roboteam/harness/codex/host/meta_dispatcher.js',
                    'roboteam/harness/codex/host/gateway_rpc.js',
                    'roboteam/harness/codex/host/policy_host.js',
                    'roboteam/runtime/run/bootstrap.py',
                )
                supported = all(
                    frozen.get(name) == hashlib.sha256((ROOT / name).read_bytes()).hexdigest()
                    and frozen[name]
                    == hashlib.sha256((run / 'private/inputs/frozen-source' / name).read_bytes()).hexdigest()
                    for name in required
                )
            except (OSError, ValueError, KeyError):
                supported = False
            if not supported:
                raise ValueError(
                    'Short-outage pause requires the run to be frozen on this runtime; task left untouched'
                )
        current = json.loads(Path(job.get('launch_file', run / 'private/inputs/codex.json')).read_text())
        if (
            current.get('tool_backend') != 'landlock-v1'
            or current['model_entry']['provider'] != 'openai'
            or current['model_entry'].get('runner_backend') != BACKEND
        ):
            raise ValueError('Job harness requires an explicit managed-subscription broker model')
        native_args = _common_args(current)
        model_bytes = Path(current['model_catalog']).read_bytes()
        if args is None:
            args, launch, catalog = native_args, current, model_bytes
        elif native_args != args or model_bytes != catalog:
            raise ValueError('A job harness requires one exact model/provider/catalog configuration')
        access = json.loads((run / 'private/inputs/policy-access.json').read_text())
        if access.get('network') is not False:
            raise ValueError('Job policy networking must be disabled')
        forbidden_roots = [private_root, credential_store, '/proc', '/dev']
        if os.environ.get('ROBOTEAM_EGRESS_ROOT'):
            forbidden_roots.append(os.environ['ROBOTEAM_EGRESS_ROOT'])
        forbidden_roots.extend(json.loads(os.environ.get('ROBOTEAM_SHARED_DENY_ROOTS', '[]')))
        for forbidden in forbidden_roots:
            if mode(access['filesystem'], forbidden) != 'deny':
                raise ValueError('Job credential/control paths are absent from the frozen deny table')
        for other in jobs:
            if other != job and mode(access['filesystem'], other['run_directory']) != 'deny':
                raise ValueError('Another task is readable through the frozen policy table')
        identity = task_id(run)
        tasks.append(
            {
                'id': identity,
                'run': str(run),
                'cwd': str(run / 'workspace'),
                'permissions': 'rf_' + identity,
                'model': current['model'],
                'provider': current['provider'],
                'effort': current['effort'],
                'kind': 'preflight' if preflight else 'policy',
                **({'resumeThreads': job['resume_threads']} if job.get('resume_threads') else {}),
                **(
                    {
                        'image': current.get('tool_probe', {}).get(
                            'image', str(Path(job['launch_file']).parent / 'colors.png')
                        )
                    }
                    if preflight
                    else {}
                ),
            }
        )
    if not tasks:
        raise ValueError('No tasks for job harness')
    args = [
        *args,
        '-c',
        'model_catalog_json=' + json.dumps(launch['model_catalog']),
        '-c',
        'cli_auth_credentials_store="file"',
        '-c',
        'default_permissions="rf_closed"',
        '-c',
        'permissions.rf_closed.filesystem={"/"="deny"}',
        '-c',
        'permissions.rf_closed.network.enabled=false',
    ]
    for task in tasks:
        access = json.loads((Path(task['run']) / 'private/inputs/policy-access.json').read_text())
        table = ','.join(json.dumps(p) + '=' + json.dumps(v) for p, v in access['filesystem'].items())
        prefix = 'permissions.' + task['permissions']
        args.extend(['-c', prefix + '.filesystem={' + table + '}', '-c', prefix + '.network.enabled=false'])
    endpoint = str(control / 'harness.sock')
    if len(endpoint.encode()) >= 104:
        raise ValueError('Job gateway socket path is too long; use a shorter node-local scratch path')
    return {
        'backend': BACKEND,
        'fingerprint': fingerprint(),
        'tasks': tasks,
        'args': args,
        'launch': launch,
        'endpoint': endpoint,
        'ready': str(control / 'ready.json'),
        'recovery_directory': str(control / 'recovery'),
        'ownership': str(control / 'ownership.json'),
        'log': str(control / 'native.log'),
    }


def export_sessions(manifest, home):
    """Export owned transcripts after the one native writer has stopped.

    Normal role/snapshot sessions use the existing canonical index. Retain
    unbound forks separately too, e.g. an acknowledgement lost before binding.
    Never walk/copy the harness home or collect auth/config/native SQLite.
    """
    from roboteam.launch.results.session_archive import _copy_verified, keep_codex

    ownership = Path(manifest['ownership'])
    if not ownership.exists():
        return
    tasks = {task['id']: task for task in manifest['tasks']}
    seen = set()
    for row in json.loads(ownership.read_text()):
        task = tasks.get(row['task_id'])
        if task is None or row['run'] != task['run']:
            raise ValueError('Invalid gateway transcript ownership record')
        run = Path(task['run'])
        known = set()
        if (run / 'private/state/runtime.sqlite').is_file():
            kept = keep_codex(run, home)
            if kept is not None:
                index = json.loads(Path(kept['index']).read_text())
                known = {entry['thread_id'] for entry in index['threads'] if entry.get('verified')}
        rows = []
        for thread in row['threads']:
            if (
                not isinstance(thread, str)
                or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', thread)
                or thread in seen
            ):
                raise ValueError('Invalid or multiply owned gateway transcript ID')
            seen.add(thread)
            if thread in known:
                continue
            matches = list((Path(home) / 'sessions').rglob('*' + thread + '.jsonl'))
            if len(matches) != 1:
                rows.append({'thread_id': thread, 'status': 'missing' if not matches else 'ambiguous'})
                continue
            source = matches[0]
            if source.is_symlink() or not source.is_file():
                raise ValueError('Gateway transcript source must be a regular file')
            target = run / 'private/harness/gateway-transcripts' / source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = _copy_verified(source, target)
            rows.append(
                {
                    'thread_id': thread,
                    'file': target.relative_to(run).as_posix(),
                    'sha256': digest,
                    'verified': True,
                }
            )
        write_json(
            run / 'private/harness/gateway-transcripts/index.json',
            {'backend': BACKEND, 'task_id': task['id'], 'threads': rows},
        )


def pinned_cli():
    """The Codex CLI version that docker/Dockerfile pins."""
    found = PINNED_CLI.search((ROOT / 'docker/Dockerfile').read_text())
    if found is None:
        raise ValueError('docker/Dockerfile no longer pins the Codex CLI as ARG CODEX_VERSION=<version>')
    return found.group(1)


def require_pinned_cli(env=None, timeout_s=CLI_TIMEOUT_S):
    """Refuse any Codex CLI but the pinned one, for every job-scoped harness.

    This covers each Slurm subscription batch and its preflight, with or without a policy
    environment: a newer CLI can reject this backend's configuration, and a shared account's
    copy can change without notice. A CLI that fails or does not answer within `timeout_s`
    counts as none.
    """
    pinned = pinned_cli()
    actual = policy_env.cli_version('codex', env, timeout_s)
    if actual != 'codex-cli ' + pinned:
        raise ValueError(
            'Every job-scoped Codex harness needs Codex CLI %s first on PATH; found %s'
            % (pinned, actual or 'none')
        )


@contextmanager
def harness(jobs, *, env, preflight=False, timeout_s=180):
    env = dict(env)
    # Every job-scoped batch and preflight, not only runs with a policy environment.
    require_pinned_cli(env)
    for key in (
        'OPENAI_API_KEY',
        'CODEX_API_KEY',
        'CODEX_ACCESS_TOKEN',
        'OPENAI_BASE_URL',
        'OPENAI_API_BASE',
    ):
        env.pop(key, None)
    private = Path(env['ROBOTEAM_JOB_PRIVATE_ROOT']).resolve()
    control = private / 'control'
    control.mkdir(mode=0o700, exist_ok=False)
    (control / 'recovery').mkdir(mode=0o700)
    manifest = build_manifest(
        jobs,
        control,
        private,
        env['ROBOTEAM_CREDENTIAL_STORE'],
        preflight=preflight,
        pause_file=env.get('ROBOTEAM_EGRESS_PAUSE_FILE'),
    )
    if env.get('ROBOTEAM_EGRESS_PAUSE_FILE'):
        expected = str(private / 'EGRESS_PAUSED')
        if env['ROBOTEAM_EGRESS_PAUSE_FILE'] != expected:
            raise ValueError('Egress pause marker must belong to the original harness private root')
        manifest['pause_file'] = expected
    if env.get('ROBOTEAM_BORROWED_AUTH'):
        expected = str(Path(env['ROBOTEAM_CREDENTIAL_STORE']) / 'current.json')
        if env['ROBOTEAM_BORROWED_AUTH'] != expected:
            raise ValueError('Borrowed access must follow the configured canonical store')
        manifest['borrowed_credentials'] = expected
    write_json(control / 'manifest.json', manifest)
    log = (control / 'gateway.log').open('a')
    proc = subprocess.Popen(
        ['node', str(ROOT / 'roboteam/harness/codex/host/job_gateway.js'), str(control / 'manifest.json')],
        env=env,
        cwd=ROOT,
        stdout=log,
        stderr=log,
        start_new_session=True,
    )
    stopped = threading.Event()

    def supervise():
        while not stopped.wait(0.1):
            if (
                any((private / name).exists() for name in ('CREDENTIAL_ERROR', 'EGRESS_ERROR'))
                and proc.poll() is None
            ):
                proc.terminate()
                return

    watcher = threading.Thread(target=supervise, name='codex-harness-custody', daemon=True)
    watcher.start()
    try:
        deadline = time.monotonic() + timeout_s
        while not Path(manifest['ready']).exists():
            if proc.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError(
                    'Shared native harness failed admission before START; see private supervisor logs'
                )
            time.sleep(0.05)
        yield manifest, proc
    finally:
        stopped.set()
        watcher.join()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass
                proc.wait()
        # Reap a native descendant even if its Node parent died unexpectedly.
        # Policy hosts/worlds do not belong to this isolated process group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            # macOS refuses (EPERM) to signal a group whose members are all zombies.
            pass
        try:
            export_sessions(manifest, env['CODEX_HOME'])
        finally:
            log.close()
        if proc.returncode:
            raise RuntimeError('Shared native harness did not close cleanly; task evidence needs review')
