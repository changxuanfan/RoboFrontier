"""Trusted job-level native process lifecycle and task-channel manifest.

No scheduler calls or credential reads. CredentialLease surrounds this owner.
Each task keeps a distinct frozen filesystem profile and runtime database.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import signal
import threading
import time

from robofrontier.policy_access import mode
from robofrontier.run_setup import write_json
from robofrontier.task_config import ROOT

BACKEND = 'slurm-managed-v1'


def fingerprint():
    names = ('codex/job_engine.py', 'codex/job_gateway.js', 'codex/gateway_rpc.js',
             'codex/file_sandbox.py', 'codex/tool_worker.py', 'codex/tool_backend.py',
             'codex/codex_rpc.js', 'codex/codex_policy_host.js', 'codex/batch.py',
             'codex/tool_broker.js', 'codex/launch.py', 'slurm_auth.py', 'slurm_job.py',
             'policy_access.py', 'slurm_proxy.py')
    digest = hashlib.sha256(BACKEND.encode())
    for name in names:
        digest.update(name.encode() + b'\0' + (ROOT/'robofrontier'/name).read_bytes() + b'\0')
    return digest.hexdigest()


def task_id(run):
    return hashlib.sha256(str(Path(run).resolve()).encode()).hexdigest()[:24]


def _common_args(launch):
    args, common = launch['args'], []
    if len(args) % 2 or any(args[i] != '-c' for i in range(0, len(args), 2)):
        raise ValueError('Job engine requires explicit native configuration overrides')
    for key, value in zip(args[::2], args[1::2]):
        name = value.split('=', 1)[0]
        if name == 'default_permissions' or name.startswith('permissions.') or name == 'model_catalog_json':
            continue
        common.extend([key, value])
    return common


def build_manifest(jobs, control, private_root, credential_store, *, preflight=False):
    control, private_root = Path(control).resolve(), Path(private_root).resolve()
    tasks, args, launch, catalog = [], None, None, None
    for job in jobs:
        run = Path(job['run_directory']).resolve()
        current = json.loads(Path(job.get('launch_file', run/'private/inputs/codex.json')).read_text())
        if (current.get('tool_backend') != 'landlock-v1' or current['profile']['provider'] != 'openai'
                or current['profile'].get('runner_backend') != BACKEND):
            raise ValueError('Job engine requires an explicit managed-subscription broker profile')
        native_args = _common_args(current)
        model_bytes = Path(current['model_catalog']).read_bytes()
        if args is None:
            args, launch, catalog = native_args, current, model_bytes
        elif native_args != args or model_bytes != catalog:
            raise ValueError('A job engine requires one exact model/provider/catalog configuration')
        access = json.loads((run/'private/inputs/policy-access.json').read_text())
        if access.get('network') is not False:
            raise ValueError('Job policy networking must be disabled')
        forbidden_roots = [private_root, credential_store, '/proc', '/dev']
        if os.environ.get('ROBOFRONTIER_EGRESS_ROOT'):
            forbidden_roots.append(os.environ['ROBOFRONTIER_EGRESS_ROOT'])
        for forbidden in forbidden_roots:
            if mode(access['filesystem'], forbidden) != 'deny':
                raise ValueError('Job credential/control paths are absent from the frozen deny table')
        for other in jobs:
            if other != job and mode(access['filesystem'], other['run_directory']) != 'deny':
                raise ValueError('Another task is readable through the frozen policy table')
        identity = task_id(run)
        tasks.append({'id': identity, 'run': str(run), 'cwd': str(run/'workspace'),
                      'permissions': 'rf_' + identity, 'model': current['model'],
                      'provider': current['provider'], 'effort': current['effort'],
                      'kind': 'preflight' if preflight else 'policy',
                      **({'image': str(Path(job['launch_file']).parent/'colors.png')} if preflight else {})})
    if not tasks:
        raise ValueError('No tasks for job engine')
    args = [*args, '-c', 'model_catalog_json=' + json.dumps(launch['model_catalog']),
            '-c', 'cli_auth_credentials_store="file"', '-c', 'default_permissions="rf_closed"',
            '-c', 'permissions.rf_closed.filesystem={"/"="deny"}',
            '-c', 'permissions.rf_closed.network.enabled=false']
    for task in tasks:
        access = json.loads((Path(task['run'])/'private/inputs/policy-access.json').read_text())
        table = ','.join(json.dumps(p)+'='+json.dumps(v) for p, v in access['filesystem'].items())
        prefix = 'permissions.' + task['permissions']
        args.extend(['-c', prefix+'.filesystem={'+table+'}', '-c', prefix+'.network.enabled=false'])
    endpoint = str(control/'engine.sock')
    if len(endpoint.encode()) >= 104:
        raise ValueError('Job gateway socket path is too long; use a shorter node-local scratch path')
    return {'backend': BACKEND, 'fingerprint': fingerprint(), 'tasks': tasks, 'args': args,
            'launch': launch, 'endpoint': endpoint, 'ready': str(control/'ready.json'),
            'ownership': str(control/'ownership.json'), 'log': str(control/'native.log')}


def export_sessions(manifest, home):
    """Export owned transcripts after the one native writer has stopped.

    Normal role/snapshot sessions use the existing canonical index. Retain
    unbound forks separately too, e.g. an acknowledgement lost before binding.
    Never walk/copy the engine home or collect auth/config/native SQLite.
    """
    from robofrontier.session_archive import keep_codex, _copy_verified
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
        if (run/'private/state/runtime.sqlite').is_file():
            kept = keep_codex(run, home)
            if kept is not None:
                index = json.loads(Path(kept['index']).read_text())
                known = {entry['thread_id'] for entry in index['threads'] if entry.get('verified')}
        rows = []
        for thread in row['threads']:
            if not isinstance(thread, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,127}', thread) or thread in seen:
                raise ValueError('Invalid or multiply owned gateway transcript ID')
            seen.add(thread)
            if thread in known:
                continue
            matches = list((Path(home)/'sessions').rglob('*'+thread+'.jsonl'))
            if len(matches) != 1:
                rows.append({'thread_id': thread, 'status': 'missing' if not matches else 'ambiguous'})
                continue
            source = matches[0]
            if source.is_symlink() or not source.is_file():
                raise ValueError('Gateway transcript source must be a regular file')
            target = run/'private/engine/gateway-transcripts'/source.name
            target.parent.mkdir(parents=True, exist_ok=True)
            digest = _copy_verified(source, target)
            rows.append({'thread_id': thread, 'file': target.relative_to(run).as_posix(), 'sha256': digest, 'verified': True})
        write_json(run/'private/engine/gateway-transcripts/index.json',
                   {'backend': BACKEND, 'task_id': task['id'], 'threads': rows})


@contextmanager
def engine(jobs, *, env, preflight=False, timeout_s=180):
    env = dict(env)
    for key in ('OPENAI_API_KEY', 'CODEX_API_KEY', 'CODEX_ACCESS_TOKEN', 'OPENAI_BASE_URL', 'OPENAI_API_BASE'):
        env.pop(key, None)
    private = Path(env['ROBOFRONTIER_JOB_PRIVATE_ROOT']).resolve()
    control = private/'control'
    control.mkdir(mode=0o700, exist_ok=False)
    manifest = build_manifest(jobs, control, private, env['ROBOFRONTIER_CREDENTIAL_STORE'], preflight=preflight)
    write_json(control/'manifest.json', manifest)
    log = (control/'gateway.log').open('a')
    proc = subprocess.Popen(['node', str(ROOT/'robofrontier/codex/job_gateway.js'), str(control/'manifest.json')],
                            env=env, cwd=ROOT, stdout=log, stderr=log, start_new_session=True)
    stopped = threading.Event()
    def supervise():
        while not stopped.wait(.1):
            if any((private/name).exists() for name in ('CREDENTIAL_ERROR', 'EGRESS_ERROR')) and proc.poll() is None:
                proc.terminate()
                return
    watcher = threading.Thread(target=supervise, name='codex-engine-custody', daemon=True)
    watcher.start()
    try:
        deadline = time.monotonic() + timeout_s
        while not Path(manifest['ready']).exists():
            if proc.poll() is not None or time.monotonic() >= deadline:
                raise RuntimeError('Shared native engine failed admission before START; see private supervisor logs')
            time.sleep(.05)
        yield manifest, proc
    finally:
        stopped.set()
        watcher.join()
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
        # Reap a native descendant even if its Node parent died unexpectedly.
        # Policy hosts/worlds do not belong to this isolated process group.
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        try:
            export_sessions(manifest, env['CODEX_HOME'])
        finally:
            log.close()
        if proc.returncode:
            raise RuntimeError('Shared native engine did not close cleanly; task evidence needs review')
