"""Run a prepared batch as a background service on plain Linux (a RunPod pod, a workstation).

`robofrontier run BATCH --durable` on Linux starts the unified `run --foreground` command
detached from the terminal, so the batch outlives the shell that started it, as launchd does
on macOS (batch/mac.py). With a systemd user manager it becomes a transient user service;
without one (RunPod containers have none) it is a `setsid` daemon in its own session. The
batch's control folder holds the service record and logs, and a lock that keeps a second
submission out. The service stores no credential: `run` loads .env itself.

    robofrontier run BATCH --durable     # start
    robofrontier status BATCH            # includes the service state
    robofrontier stop BATCH              # an orderly stop, as everywhere
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from ..configuration import ROOT
from ..runtime import layout as run_layout

PASSED_ENVIRONMENT = ('HOME', 'PATH', 'LANG', 'LC_ALL', 'TMPDIR', 'CODEX_HOME', 'ROBOFRONTIER_CLAUDE_HOME', 'MUJOCO_GL',
                      'PYOPENGL_PLATFORM', 'ROBOFRONTIER_POLICY_ENV', 'ROBOFRONTIER_POLICY_ENV_BASE', 'ROBOFRONTIER_RUNS_ROOT')


def unit_name(batch):
    return 'robofrontier-batch-' + hashlib.sha256(str(batch).encode()).hexdigest()[:16]


def systemd_available(run=subprocess.run):
    """A systemd user manager this process can start services in."""
    if not shutil.which('systemd-run'): return False
    try: state = run(['systemctl', '--user', 'is-system-running'], capture_output=True, text=True, timeout=20).stdout.strip()
    except (OSError, subprocess.SubprocessError): return False
    return state in ('running', 'degraded')


def command(batch, python=None, continuing=False):
    return [str(python or sys.executable), '-m', 'robofrontier.cli', 'run', str(batch), '--foreground'] + (['--continue'] if continuing else [])


def submit(batch, *, continuing=False, run=subprocess.run, popen=subprocess.Popen, use_systemd=None):
    """Start the batch in the background once; a continuation gets its own service."""
    if not sys.platform.startswith('linux'):
        raise ValueError('The Linux service runs on Linux; on macOS `robofrontier run` uses launchd')
    batch = Path(batch).expanduser().resolve(strict=True)
    data = json.loads((batch/'batch.json').read_text())
    if not continuing and data.get('status') != 'prepared_not_started':
        raise ValueError('Only a freshly prepared batch may be submitted; a world is never restarted automatically')
    folder, name = run_layout.batch_path(batch, 'durable'), unit_name(batch)
    if continuing:
        number = 1 + sum(1 for p in folder.glob('continue-*') if p.is_dir()) if folder.is_dir() else 1
        folder, name = folder/('continue-%d' % number), name+'-continue-%d' % number
    folder.parent.mkdir(parents=True, exist_ok=True)
    folder.mkdir(mode=0o700)  # Atomic: a second submission into the same folder fails here.
    environment = {k: os.environ[k] for k in PASSED_ENVIRONMENT if k in os.environ}
    argv = command(batch, continuing=continuing)
    systemd = systemd_available(run) if use_systemd is None else use_systemd
    record = {'batch': str(batch), 'continuing': continuing, 'submitted_at': time.time(), 'command': argv}
    if systemd:
        unit = name+'.service'
        started = run(['systemd-run', '--user', '--collect', '--unit', unit, '--working-directory', str(ROOT),
                       *[f'--setenv={k}={v}' for k, v in environment.items()],
                       '--property', 'StandardOutput=append:'+str(folder/'stdout.log'),
                       '--property', 'StandardError=append:'+str(folder/'stderr.log'), *argv],
                      capture_output=True, text=True)
        if started.returncode:
            raise RuntimeError('systemd-run failed; inspect '+str(folder)+' before retrying: '+started.stderr.strip())
        record.update(manager='systemd-user', unit=unit)
    else:
        with (folder/'stdout.log').open('a') as out, (folder/'stderr.log').open('a') as err:
            child = popen(argv, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                          start_new_session=True)
        record.update(manager='setsid', pid=child.pid)
    (folder/'service.json').write_text(json.dumps(record, indent=2)+'\n')
    return record


def service_state(batch, run=subprocess.run):
    """The service's record and whether it still runs, or None if the batch was not started this way."""
    folder = run_layout.batch_path(batch, 'durable')
    if not (folder/'service.json').is_file(): return None
    record = json.loads((folder/'service.json').read_text())
    if record.get('manager') == 'systemd-user':
        active = run(['systemctl', '--user', 'is-active', record['unit']], capture_output=True, text=True).stdout.strip()
        return {**record, 'running': active in ('active', 'activating')}
    try: os.kill(record['pid'], 0); running = True
    except (OSError, KeyError, TypeError): running = False
    return {**record, 'running': running}
