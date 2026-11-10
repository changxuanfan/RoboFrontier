"""Run a prepared batch under the macOS user launchd service, for either engine.

The service runs the unified `run` command, which loads credentials from the
ignored .env itself, so the service file stores no credential. A batch is
submitted once; its world is never restarted automatically. Explicit benchmark
runs use application-class scheduling through ProcessType=Interactive. On macOS
`robofrontier run` submits a batch this way by default, a continuation included;
`--foreground` opts out.
"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys
import time

from . import run_layout
from .configuration import ROOT

CAFFEINATE = '/usr/bin/caffeinate'
# Non-secret variables the run needs from the submitting shell.
PASSED_ENVIRONMENT = ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'CODEX_HOME', 'ROBOFRONTIER_CLAUDE_HOME',
                      'MUJOCO_GL', 'PYOPENGL_PLATFORM')


def service_label(batch):
    return 'org.robofrontier.batch.' + hashlib.sha256(str(batch).encode()).hexdigest()[:16]


def service(batch, *, engineering, python, environment, continuing=False, label=None, folder=None):
    folder = folder or run_layout.batch_path(batch, 'durable')
    # The service itself runs in the foreground; otherwise it would submit itself again.
    command = ([str(python), '-m', 'robofrontier.cli', 'run', str(batch), '--foreground']
               + (['--continue'] if continuing else []) + (['--engineering'] if engineering else []))
    return job(label or service_label(batch), command, folder, ROOT, environment)


def job(label, command, folder, working_directory, environment):
    """A one-shot user launchd job with application-class (Interactive) scheduling.

    caffeinate holds the Mac awake (no idle, disk or system sleep on AC) for exactly the job's
    life: a sleeping host stalls every world, and active time does not count a stall."""
    command = [CAFFEINATE, '-ims', *command]
    return {'Label': label, 'ProgramArguments': [str(part) for part in command], 'WorkingDirectory': str(working_directory),
            'RunAtLoad': True, 'KeepAlive': False, 'ProcessType': 'Interactive',
            'StandardOutPath': str(Path(folder)/'stdout.log'), 'StandardErrorPath': str(Path(folder)/'stderr.log'),
            'EnvironmentVariables': environment}


def bootstrap(plist, folder, metadata):
    """Write the job's files into the new, private `folder` and load it once."""
    if sys.platform != 'darwin':
        raise ValueError('Durable runs use macOS launchd; on Linux submit through Slurm')
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'print', domain], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    folder = Path(folder)
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(mode=0o700)  # Atomic: a second submission into the same folder fails here.
    with (folder/'service.plist').open('wb') as out:
        plistlib.dump(plist, out)
    metadata = {'label': plist['Label'], 'domain': domain, 'submitted_at': time.time(), **metadata}
    (folder/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(folder/'service.plist')], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('launchctl bootstrap failed; inspect '+str(folder)+' before retrying: '+result.stderr.strip())
    return metadata


def passed_environment():
    return {key: os.environ[key] for key in PASSED_ENVIRONMENT if key in os.environ}


def submit(batch, *, engineering=False, continuing=False):
    """Run a batch under launchd. A fresh batch is submitted once; a continuation of a batch
    whose supervisor died gets its own job (`run --continue` checks it may continue)."""
    if sys.platform != 'darwin':
        raise ValueError('Durable runs use macOS launchd; on Linux submit through Slurm')
    batch = Path(batch).expanduser().resolve(strict=True)
    data = json.loads((batch/'batch.json').read_text())
    if not continuing and data.get('status') not in ('prepared_not_started', 'prepared_not_qualified'):
        raise ValueError('Only a freshly prepared batch may be submitted; a world is never restarted automatically')
    folder, label = run_layout.batch_path(batch, 'durable'), service_label(batch)
    if continuing:
        number = 1 + sum(1 for p in folder.glob('continue-*') if p.is_dir()) if folder.is_dir() else 1
        folder, label = folder/('continue-%d' % number), label+'.continue-%d' % number
    plist = service(batch, engineering=engineering, python=Path(sys.executable).absolute(), environment=passed_environment(),
                    continuing=continuing, label=label, folder=folder)
    return bootstrap(plist, folder, {'batch': str(batch), 'engineering': engineering, 'continuing': continuing})


def service_state(batch):
    """The launchd job's state for a durable batch, or None if it was not submitted durably."""
    folder = run_layout.batch_path(batch, 'durable')
    if not (folder/'metadata.json').is_file():
        return None
    metadata = json.loads((folder/'metadata.json').read_text())
    printed = subprocess.run(['launchctl', 'print', metadata['domain']+'/'+metadata['label']], text=True, capture_output=True)
    return {**metadata, 'loaded': printed.returncode == 0}
