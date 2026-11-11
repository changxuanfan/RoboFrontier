"""Inspect local execution prerequisites without authenticating or calling models."""
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from ..configuration import ROOT, rendering_environment


def _checked(command, *, env, timeout=60):
    result = subprocess.run(command, cwd=ROOT, env=env, text=True,
                            capture_output=True, timeout=timeout)
    if result.returncode:
        # These probes receive no credentials and run only fixed local commands.
        raise RuntimeError((result.stderr or result.stdout).strip()[-1600:] or
                           'Local probe exited with code '+str(result.returncode))
    return result.stdout.strip()


def _native_probe(engine, backend='native', robot_only=False):
    with tempfile.TemporaryDirectory(prefix='rf-native-probe-') as temporary:
        # Do not import another Desktop/session's mutable config or credentials.
        env = {key: value for key, value in os.environ.items() if key in (
            'PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT')}
        env.update(CODEX_HOME=str(Path(temporary)/'codex'),
                   CLAUDE_CONFIG_DIR=str(Path(temporary)/'claude'))
        for name in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR'):
            Path(env[name]).mkdir(mode=0o700)
        version = _checked([engine, '--version'], env=env)
        if engine == 'codex':
            if backend == 'landlock-v1':
                checked = json.loads(_checked([sys.executable, '-m', 'robofrontier.engines.codex.tool_backend'], env=env))
                return {'version': version, **checked}
            if backend != 'native':
                raise ValueError('Unknown Codex tool backend')
            if robot_only:
                # No command is ever run for a robot_only role, so Codex's own sandbox is not
                # needed; a host that forbids user namespaces (a RunPod pod) can run it.
                return {'version': version, 'sandbox_checked': False, 'tool_mode': 'robot_only'}
            _checked(['codex', 'sandbox', '--', 'sh', '-c', 'test -r configs/models.json'], env=env, timeout=30)
        return {'version': version, 'sandbox_checked': engine == 'codex'}


def _render_probe(device):
    env = rendering_environment(device, platform.system(), {})
    # Keep the dynamic loader/runtime environment, but no model credentials.
    for key in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL', 'SYSTEMROOT',
                'LD_LIBRARY_PATH', 'NVIDIA_VISIBLE_DEVICES', 'NVIDIA_DRIVER_CAPABILITIES',
                '__EGL_VENDOR_LIBRARY_FILENAMES'):
        if key in os.environ:
            env[key] = os.environ[key]
    if device != 'cpu' and 'CUDA_VISIBLE_DEVICES' in os.environ:
        env['CUDA_VISIBLE_DEVICES'] = os.environ['CUDA_VISIBLE_DEVICES']
    code = '''import json,sys
import mujoco
from robofrontier.physics.render_backend import current_backend
model=mujoco.MjModel.from_xml_string('<mujoco><worldbody><geom type="sphere" size="0.1"/></worldbody></mujoco>')
data=mujoco.MjData(model)
mujoco.mj_step(model,data)
with mujoco.Renderer(model,width=64,height=64) as renderer:
    renderer.update_scene(data)
    image=renderer.render()
    result=current_backend(sys.argv[1])
    result.update(image_shape=list(image.shape),physics_time_s=float(data.time))
print(json.dumps(result))
'''
    return json.loads(_checked([sys.executable, '-c', code, device], env=env))


def inspect_runtime(config, *, render=True):
    """Return separate local checks; success does not qualify a provider or run."""
    checks = {}
    backend = config['runtime'].get('codex_tool_backend', 'native')
    robot_only = config['policy'].get('tool_mode', 'full') == 'robot_only'
    probes = [('native_cli', lambda: _native_probe(config['policy']['engine'], backend, robot_only))]
    if render:
        probes.append(('render', lambda: _render_probe(config['render']['device'])))
    for name, probe in probes:
        try:
            checks[name] = {'passed': True, **probe()}
        except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as error:
            checks[name] = {'passed': False, 'error': str(error)}
    return {'schema': 'robofrontier.local-doctor.v1', 'model_calls': 0,
            'engine': config['policy']['engine'],
            'passed': all(check['passed'] for check in checks.values()), 'checks': checks,
            'scope': 'Local CLI/sandbox/render only; no provider, task completion or concurrency qualification'}


def require_runtime(config, *, render=True):
    report = inspect_runtime(config, render=render)
    if not report['passed']:
        errors = '; '.join(name+': '+check['error'] for name, check in report['checks'].items()
                           if not check['passed'])
        raise ValueError('Local execution prerequisites failed before model calls. '+errors+
                         ' Run robofrontier doctor (or container doctor); see docs/running/docker.md for nested sandbox settings.')
    return report
