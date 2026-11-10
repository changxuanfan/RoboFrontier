"""Run a prepared batch under the macOS user launchd service, for either engine.

The service runs the unified `run` command, which loads credentials from the
ignored .env itself, so the service file stores no credential. A batch is
submitted once; its world is never restarted automatically. Explicit benchmark
runs use application-class scheduling through ProcessType=Interactive. On macOS
`robofrontier run` submits a fresh batch this way by default; `--foreground` opts out.
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

# Non-secret variables the run needs from the submitting shell.
PASSED_ENVIRONMENT = ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'CODEX_HOME', 'ROBOFRONTIER_CLAUDE_HOME',
                      'MUJOCO_GL', 'PYOPENGL_PLATFORM')


def service_label(batch):
    return 'org.robofrontier.batch.' + hashlib.sha256(str(batch).encode()).hexdigest()[:16]


def service(batch, *, engineering, python, environment):
    folder = run_layout.batch_path(batch, 'durable')
    # The service itself runs in the foreground; otherwise it would submit itself again.
    command = [str(python), '-m', 'robofrontier.cli', 'run', str(batch), '--foreground'] + (['--engineering'] if engineering else [])
    return {'Label': service_label(batch), 'ProgramArguments': command, 'WorkingDirectory': str(ROOT),
            'RunAtLoad': True, 'KeepAlive': False, 'ProcessType': 'Interactive',
            'StandardOutPath': str(folder/'stdout.log'), 'StandardErrorPath': str(folder/'stderr.log'),
            'EnvironmentVariables': environment}


def submit(batch, *, engineering=False):
    if sys.platform != 'darwin':
        raise ValueError('Durable runs use macOS launchd; on Linux submit through Slurm')
    batch = Path(batch).expanduser().resolve(strict=True)
    data = json.loads((batch/'batch.json').read_text())
    if data.get('status') not in ('prepared_not_started', 'prepared_not_qualified'):
        raise ValueError('Only a freshly prepared batch may be submitted; a world is never restarted automatically')
    domain = f'gui/{os.getuid()}'
    subprocess.run(['launchctl', 'print', domain], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    folder = run_layout.batch_path(batch, 'durable')
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(mode=0o700)  # Atomic: a second submission of the same batch fails here.
    environment = {key: os.environ[key] for key in PASSED_ENVIRONMENT if key in os.environ}
    plist = service(batch, engineering=engineering, python=Path(sys.executable).absolute(), environment=environment)
    with (folder/'service.plist').open('wb') as out:
        plistlib.dump(plist, out)
    metadata = {'label': plist['Label'], 'domain': domain, 'submitted_at': time.time(), 'batch': str(batch),
                'engineering': engineering}
    (folder/'metadata.json').write_text(json.dumps(metadata, indent=2)+'\n')
    result = subprocess.run(['launchctl', 'bootstrap', domain, str(folder/'service.plist')], text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('launchctl bootstrap failed; inspect '+str(folder)+' before retrying: '+result.stderr.strip())
    return metadata


def service_state(batch):
    """The launchd job's state for a durable batch, or None if it was not submitted durably."""
    folder = run_layout.batch_path(batch, 'durable')
    if not (folder/'metadata.json').is_file():
        return None
    metadata = json.loads((folder/'metadata.json').read_text())
    printed = subprocess.run(['launchctl', 'print', metadata['domain']+'/'+metadata['label']], text=True, capture_output=True)
    return {**metadata, 'loaded': printed.returncode == 0}
