"""Freeze, fingerprint and exercise the Codex file-tool isolation backend."""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
import tempfile

from robofrontier.runtime import access as policy_access
from robofrontier.runtime.setup import write_json
from robofrontier.tasks.config import ROOT
from .tool_worker import SCHEMA

BACKENDS = ('native', 'landlock-v1')


def selected(profile):
    backend = profile.get('tool_backend', 'native')
    if backend not in BACKENDS:
        raise ValueError('Unknown Codex tool backend: ' + str(backend))
    return backend


def fingerprint(profile):
    if selected(profile) == 'native':
        return None
    files = ('tool_worker.py', 'file_sandbox.py', 'tool_backend.py', 'tool_broker.js', 'launch.py',
             'codex_policy_host.js', 'codex_preflight.js', 'codex_rpc.js',
             'job_engine.py', 'job_gateway.js', 'gateway_rpc.js', 'borrowed_auth.js',
             '../common/tool_worker.py', '../common/landlock.py', '../../runtime/access.py')
    digest = hashlib.sha256(b'landlock-v1\0')
    for name in files:
        digest.update(name.encode()+b'\0'+(Path(__file__).parent/name).read_bytes()+b'\0')
    return digest.hexdigest()


def verify_receipt(launch, checked):
    if selected(launch['profile']) == 'landlock-v1':
        expected = fingerprint(launch['profile'])
        if (not checked.get('passed') or checked.get('tool_backend') != 'landlock-v1'
                or not checked.get('broker_tools_verified') or checked.get('tool_backend_sha256') != expected
                or launch.get('tool_backend_sha256') != expected):
            raise ValueError('Codex broker backend changed or was not qualified; rerun preflight')


def prepare(run, profile):
    if selected(profile) == 'native':
        return
    run = Path(run).resolve()
    path = run/'private/inputs/policy-access.json'
    access = json.loads(path.read_text())
    if access.get('network') is not False:
        raise ValueError('The Landlock broker does not permit model networking')
    access['filesystem'].update({'/proc': 'deny', '/dev': 'deny'})
    # A run with a policy environment keeps /tmp open, on every engine (policy_access), and
    # gets a private /dev/shm (tool_worker), where Python's multiprocessing keeps its locks.
    if access.get('policy_env'):
        access['filesystem']['/dev/shm'] = 'write'
    else:
        access['filesystem']['/tmp'] = 'deny'
    if os.environ.get('TMPDIR'):
        temporary = Path(os.environ['TMPDIR']).resolve()
        if not (access.get('policy_env') and temporary == Path('/tmp').resolve()):
            access['filesystem'][str(temporary)] = 'deny'
    access['filesystem'][str(run/'workspace')] = 'write'
    # Job-local virtualenvs can live beneath denied /tmp or source roots. Allow
    # only interpreter metadata and libraries, never the entire environment or
    # its parent. These grants are frozen before a policy turn can run.
    runtime_paths = {Path(sys.prefix)/'pyvenv.cfg',
                     Path(sysconfig.get_path('purelib')), Path(sysconfig.get_path('platlib'))}
    if profile.get('runner_backend') == 'slurm-managed-v1' and os.environ.get('ROBOFRONTIER_SHARED_DENY_ROOTS'):
        runtime_paths.update(Path(p) for p in sys.path if p and Path(p).name in ('site-packages', 'dist-packages'))
        runtime_paths.update((Path(sysconfig.get_path('stdlib')), Path(sys.executable).resolve()))
        libdir, library = sysconfig.get_config_var('LIBDIR'), sysconfig.get_config_var('LDLIBRARY')
        if libdir and library:
            runtime_paths.add(Path(libdir)/library)
    private_roots = [run/'private', *policy_access._auth_homes(Path.home())]
    for runtime_path in runtime_paths:
        if runtime_path.exists():
            runtime_path = runtime_path.resolve()
            if any(runtime_path.is_relative_to(Path(root).resolve()) for root in private_roots):
                raise ValueError('Keep the Python runtime outside private credential/control directories')
            access['filesystem'][str(runtime_path)] = 'read'
    (run/'workspace/.tmp').mkdir(exist_ok=True)
    write_json(path, access)
    write_json(run/'private/inputs/codex-tools.json', {'schema': SCHEMA, 'backend': 'landlock-v1'})
    # New runs get backend-specific tool instructions before hashes are frozen.
    from robofrontier.runtime.bootstrap import ENGINE_LINES
    message = ('Use policy_exec for file reads, shell commands and workspace notes. '
               'Use policy_image with a path to view permitted PNG/JPEG files. '
               'Robot observations still return images through robot. '
               'Delegate work only through robot delegate, never Codex collaboration tools.')
    for path in (run/'private/inputs/bootstrap').glob('*.md'):
        path.write_text(path.read_text().replace(ENGINE_LINES['codex'], message))


def execute(run, request, *, timeout=15):
    return subprocess.run([sys.executable, '-I', '-m', 'robofrontier.engines.codex.tool_worker',
                           '--run-dir', str(run)], input=json.dumps(request),
                          env={'PATH': os.environ.get('PATH', '/usr/bin:/bin'), 'LANG': 'C.UTF-8'},
                          capture_output=True, text=True, timeout=timeout, close_fds=True)


def preflight_probe(folder, profile=None):
    """A fresh non-physical run for the live broker/image compatibility check."""
    import shlex
    import shutil
    import uuid
    run = Path(folder)/'broker-probes'/uuid.uuid4().hex
    for name in ('private/inputs', 'public', 'workspace'):
        (run/name).mkdir(parents=True)
    write_json(run/'private/inputs/policy-access.json', policy_access.record(run))
    (run/'public/task.txt').write_text('broker-public-canary')
    (run/'private/secret.txt').write_text('broker-private-canary')
    prepare(run, profile or {'tool_backend': 'landlock-v1'})
    shutil.copyfile(Path(folder)/'colors.png', run/'public/colors.png')
    script = '''from pathlib import Path
import json,socket
r=Path.cwd().parent
assert (r/'public/task.txt').read_text()=='broker-public-canary'
(r/'workspace/probe-note').write_text('ok')
try:(r/'private/secret.txt').read_text()
except PermissionError:pass
else:raise RuntimeError('Private file was readable')
try:socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)
except PermissionError:pass
else:raise RuntimeError('Unix sockets were available')
print('BROKER_ISOLATION_OK')
'''
    (run/'public/check.py').write_text(script)
    return {'run_dir': str(run), 'command': shlex.join([sys.executable, str(run/'public/check.py')]),
            'image': str(run/'public/colors.png')}


def doctor():
    if not sys.platform.startswith('linux'):
        raise ValueError('landlock-v1 requires Linux')
    with tempfile.TemporaryDirectory(prefix='rf-codex-tools-') as temporary:
        base = Path(temporary).resolve()
        run = base/'repo/run'
        for name in ('private/inputs', 'public', 'workspace'):
            (run/name).mkdir(parents=True)
        (run/'public/task.txt').write_text('public')
        (run/'private/secret.txt').write_text('private-canary')
        (base/'repo/other.txt').write_text('other-canary')
        access = policy_access.record(run, checkouts=[base/'repo'])
        write_json(run/'private/inputs/policy-access.json', access)
        prepare(run, {'tool_backend': 'landlock-v1'})
        checks = '''import ctypes,errno,json,os,socket,subprocess,sys
from pathlib import Path
r=Path.cwd().parent
checks={}
def denied(name,fn):
 try:fn()
 except PermissionError:checks[name]=True;return
 checks[name]=False
checks['public_read']=(r/'public/task.txt').read_text()=='public'
(r/'workspace/note').write_text('ok');checks['workspace_write']=True
(r/'workspace/note').write_text('updated');checks['workspace_overwrite']=True
denied('readonly_truncate',lambda:os.open(r/'public/task.txt',os.O_RDONLY|os.O_TRUNC))
denied('path_truncate',lambda:os.truncate(r/'public/task.txt',0))
checks['public_intact']=(r/'public/task.txt').read_text()=='public'
for key,p in [('private',r/'private/secret.txt'),('other_run',r.parent/'other.txt'),('proc',Path('/proc/self/environ'))]:
 denied(key,lambda p=p:p.read_bytes())
denied('public_write',lambda:(r/'public/illegal').write_text('bad'))
for key,family,kind in [('unix',socket.AF_UNIX,socket.SOCK_STREAM),('tcp',socket.AF_INET,socket.SOCK_STREAM),('udp',socket.AF_INET,socket.SOCK_DGRAM)]:
 denied(key,lambda family=family,kind=kind:socket.socket(family,kind))
checks['environment']=not any(k in os.environ for k in ('CODEX_HOME','OPENAI_API_KEY','CLAUDE_CODE_OAUTH_TOKEN','BASH_ENV'))
print(json.dumps(checks));sys.exit(0 if all(checks.values()) else 1)
'''
        # The policy can read the checker; it is not in private trusted source.
        (run/'public/check.py').write_text(checks)
        import shlex
        result = execute(run, {'tool': 'policy_exec', 'command': shlex.join([sys.executable, str(run/'public/check.py')])})
        if result.returncode:
            raise RuntimeError('Landlock/seccomp confinement probe failed: ' + result.stderr[-1200:])
        checks = json.loads(result.stdout)
        if not checks or not all(value is True for value in checks.values()):
            raise RuntimeError('Confinement checks failed')
        from .file_sandbox import abi
        return {'backend': 'landlock-v1', 'sandbox_checked': True, 'checks': checks,
                'landlock_abi': abi(), 'network_isolation': 'seccomp',
                'backend_sha256': fingerprint({'tool_backend': 'landlock-v1'})}


if __name__ == '__main__':
    print(json.dumps(doctor()))
