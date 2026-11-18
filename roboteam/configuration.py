"""Resolve and validate one public configuration before preparing frozen inputs."""
from copy import deepcopy
import math
from pathlib import Path
import sys
import tomllib
from .io import ROOT

DEFAULT = ROOT / 'roboteam.toml'
SCHEMA_VERSION = 11
# The model of each harness when none is named (models.json); both use an API key.
DEFAULT_MODELS = {'codex': 'sol', 'claude': 'opus'}
SYSTEMS = ('adaptive', 'single-agent', 'hierarchical', 'decentralized')
SCHEMA = {
    'schema_version': int,
    'policy': dict.fromkeys(('harness', 'model', 'effort', 'system', 'tools'), str),
    'batch': {'parallel': int, 'startup_interval_s': float, 'task_wall_limit_s': float, 'startup_timeout_s': float},
    'selection': {'task_types': list, 'cases': list, 'level': int, 'min_arms': bool},
    'render': {'device': str, 'observation_profile': str, 'record_realtime_video': bool},
    'runtime': {'codex_home_scope': str, 'codex_home': str, 'codex_tool_backend': str},
    'evidence': {'auto_collect': bool, 'auto_archive': bool, 'archive_format': str, 'delete_sources': bool},
    'slurm': {'partition': str, 'account': str, 'qos': str, 'gpus': int,
              'cpus_per_task': int, 'memory_gib': int, 'time_limit_s': int,
              'stop_warning_s': int, 'scratch_root': str,
              'auth_mode': str, 'credential_store': str,
              'egress_mode': str, 'egress_root': str, 'egress_wait_s': int, 'egress_pause_s': int},
    'container': {'image': str, 'workspace': str, 'memory_gib': int, 'cpus': float,
                  'seccomp_profile': str},
    'paths': {'runs_root': str},
}


def _validate_shape(values, schema, prefix=''):
    if not isinstance(values, dict) or set(values) != set(schema):
        raise ValueError('Missing or unknown configuration options in ' + (prefix or 'root'))
    for key, kind in schema.items():
        name = prefix + key
        if isinstance(kind, dict):
            _validate_shape(values[key], kind, name + '.')
        elif type(values[key]) is not kind and not (kind is float and type(values[key]) is int):
            raise ValueError('Incorrect configuration type: ' + name)


def _merge(base, updates, prefix=''):
    for key, value in updates.items():
        name = prefix + key
        if key not in base:
            raise ValueError('Unknown configuration option: ' + name)
        if isinstance(base[key], dict):
            if not isinstance(value, dict):
                raise ValueError('Expected a configuration section: ' + name)
            _merge(base[key], value, name + '.')
        else:
            if type(value) is not type(base[key]) and not (
                    type(base[key]) is float and type(value) is int):
                raise ValueError('Incorrect configuration type: ' + name)
            base[key] = value


def load_configuration(path=None, overrides=None, *, host=None):
    """Layer a partial user TOML and explicit options over checked-in defaults.

    Secrets and arbitrary environment expansion are deliberately not supported.
    """
    with DEFAULT.open('rb') as stream:
        result = tomllib.load(stream)
    updates = {}
    if path is not None and Path(path).resolve() != DEFAULT.resolve():
        with Path(path).open('rb') as stream:
            updates = tomllib.load(stream)
    _merge(result, updates)
    if overrides:
        _merge(result, deepcopy(overrides))
    # An harness chosen without a model gets that harness's default model.
    if ('model' not in updates.get('policy', {})
            and 'model' not in (overrides or {}).get('policy', {})):
        result['policy']['model'] = DEFAULT_MODELS[result['policy']['harness']]
    # `auto` values are settled here, before anything is frozen: for this host, for the Slurm
    # nodes a submission will run on (host='slurm', from the job's GPU request), or for the
    # Linux container a Docker command starts (host='container', with this host's GPU if any).
    if result['render']['device'] == 'auto':
        if host == 'slurm': device = 'nvidia' if result['slurm']['gpus'] else 'cpu'
        elif host == 'container': device = 'nvidia' if detected_render_device() == 'nvidia' else 'cpu'
        else: device = detected_render_device()
        result['render']['device'] = device
    runtime = result['runtime']
    if runtime['codex_tool_backend'] == 'auto':
        linux = host in ('slurm', 'container') or (host is None and sys.platform.startswith('linux'))
        # A robot_only role has no file or shell tool to confine, so no tool worker is used.
        linux = linux and result['policy']['tools'] != 'robot_only'
        # Codex's own sandbox on macOS; on Linux the tool worker under Landlock and seccomp,
        # the backend scripts/release/check_policy_env.py checks there.
        runtime['codex_tool_backend'] = 'landlock-v1' if linux and result['policy']['harness'] == 'codex' else 'native'
    validate_configuration(result)
    return result


def detected_render_device(system=None):
    """What `render.device = "auto"` selects here: macOS's own OpenGL, NVIDIA EGL on a Linux host
    with an NVIDIA device, else Mesa's CPU renderer. A prepared batch freezes the choice."""
    import platform
    import shutil
    system = system or platform.system()
    if system == 'Darwin':
        return 'native'
    if Path('/dev/nvidia0').exists() or shutil.which('nvidia-smi'):
        return 'nvidia'
    return 'cpu'


def runs_root(config=None):
    """Where run data goes, whichever checkout runs: $ROBOTEAM_RUNS_ROOT, else the
    configuration's paths.runs_root (relative to the repository), else <repo>/runs."""
    import os
    value = os.environ.get('ROBOTEAM_RUNS_ROOT')
    if not value:
        if config is None:
            try: config = load_configuration()
            except (OSError, ValueError): config = {}
        value = (config.get('paths') or {}).get('runs_root') or ''
    path = Path(value).expanduser() if value else ROOT / 'runs'
    return path if path.is_absolute() else ROOT / path


# The longest a route outage may hold a Slurm world: the wall backstop (tasks.task_types.WALL_BACKSTOP_S).
MAX_EGRESS_PAUSE_S = 172800


def validate_configuration(config):
    if config.get('schema_version') != SCHEMA_VERSION or type(config['schema_version']) is not int:
        raise ValueError('Unsupported configuration schema_version: this code reads version %d' % SCHEMA_VERSION)
    _validate_shape(config, SCHEMA)
    def choice(section, field, allowed):
        if config[section][field] not in allowed:
            raise ValueError(f'Invalid {section}.{field}: choose from {", ".join(map(str, allowed))}')

    choice('policy', 'harness', ('codex', 'claude'))
    choice('policy', 'system', SYSTEMS)
    choice('policy', 'effort', ('minimal', 'low', 'medium', 'high', 'xhigh', 'max'))
    from roboteam.runtime.tools.tools_mode import MODES, ROBOT_ONLY
    choice('policy', 'tools', MODES)
    robot_only = config['policy']['tools'] == ROBOT_ONLY
    from re import fullmatch
    if not fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', config['policy']['model']):
        raise ValueError('Invalid policy.model identifier')
    batch = config['batch']
    if type(batch['parallel']) is not int or not 1 <= batch['parallel'] <= 36:
        raise ValueError('batch.parallel must be 1..36')
    for field in ('startup_interval_s', 'task_wall_limit_s', 'startup_timeout_s'):
        value = batch[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (
                field != 'startup_interval_s' and value == 0):
            raise ValueError('Invalid batch.' + field)
    if config['policy']['harness'] == 'claude' and batch['task_wall_limit_s'] > 86400:
        raise ValueError('The current Claude engineering runner supports at most 86400 seconds')
    choice('selection', 'level', (0, 1, 2, 3))
    if type(config['selection']['level']) is not int:
        raise ValueError('selection.level must be an integer')
    for field in ('task_types', 'cases'):
        values = config['selection'][field]
        if not all(type(value) is str and value for value in values) or len(set(values)) != len(values):
            raise ValueError('selection.' + field + ' must contain distinct nonempty strings')
    choice('render', 'device', ('nvidia', 'cpu', 'native'))
    choice('render', 'observation_profile', ('jpeg_1280x800_q90', 'jpeg_128x80_q95'))
    choice('runtime', 'codex_home_scope', ('task', 'shared', 'job'))
    choice('runtime', 'codex_tool_backend', ('native', 'landlock-v1'))
    if config['policy']['harness'] != 'codex' and config['runtime']['codex_tool_backend'] != 'native':
        raise ValueError('codex_tool_backend applies only to the Codex harness')
    if robot_only and config['runtime']['codex_tool_backend'] != 'native':
        # landlock-v1 confines policy_exec and policy_image, which a robot_only role does not
        # have; the Slurm subscription route requires that backend and is not supported yet.
        raise ValueError('policy.tools = "robot_only" uses codex_tool_backend = "native": '
                         'there are no file or shell tools to confine')
    choice('container', 'seccomp_profile', ('default', 'unconfined'))
    choice('evidence', 'archive_format', ('zip',))
    if config['evidence']['auto_archive'] and not config['evidence']['auto_collect']:
        raise ValueError('evidence.auto_archive requires evidence.auto_collect')
    if config['evidence']['delete_sources']:
        raise ValueError('Automatic source deletion is not supported; verify restored evidence before explicit cleanup')
    slurm = config['slurm']
    choice('slurm', 'auth_mode', ('api', 'subscription'))
    subscription = slurm['auth_mode'] == 'subscription'
    if subscription:
        if (config['policy']['harness'] != 'codex'
                or config['runtime']['codex_home_scope'] != 'job'
                or config['runtime']['codex_home']
                or config['runtime']['codex_tool_backend'] != 'landlock-v1'):
            raise ValueError('Slurm subscription requires Codex job scope, an automatic home and landlock-v1')
        path = Path(slurm['credential_store'])
        if not path.is_absolute() or '..' in path.parts:
            raise ValueError('slurm.credential_store must be an absolute private directory')
    elif slurm['credential_store'] or config['runtime']['codex_home_scope'] == 'job':
        raise ValueError('Job scope and credential_store require slurm.auth_mode=subscription')
    choice('slurm', 'egress_mode', ('direct', 'mac-ssh'))
    # A route outage holds the world like any other outage, up to the wall backstop;
    # only the mac-ssh route has a pause of its own, direct egress uses the outage probe.
    if not 0 <= slurm['egress_pause_s'] <= MAX_EGRESS_PAUSE_S:
        raise ValueError('slurm.egress_pause_s must be between 0 and %d' % MAX_EGRESS_PAUSE_S)
    if not 1 <= slurm['egress_wait_s'] <= 3600:
        raise ValueError('slurm.egress_wait_s must be between 1 and 3600')
    if slurm['egress_mode'] == 'mac-ssh':
        path = Path(slurm['egress_root'])
        # Claude reads its token from .env inside the job (launch/slurm/job.py execute) and needs only the route.
        routed = slurm['auth_mode'] == 'subscription' or config['policy']['harness'] == 'claude'
        if not routed or not path.is_absolute() or '..' in path.parts:
            raise ValueError('Mac egress requires subscription mode or Claude, and an absolute private egress_root')
    elif slurm['egress_root']:
        raise ValueError('egress_root requires slurm.egress_mode=mac-ssh')
    for field in ('gpus', 'cpus_per_task', 'memory_gib', 'time_limit_s', 'stop_warning_s'):
        if slurm[field] < (0 if field == 'gpus' else 1):
            raise ValueError('Invalid slurm.' + field)
    if not 120 <= slurm['stop_warning_s'] < slurm['time_limit_s']:
        raise ValueError('slurm.stop_warning_s must be at least 120 and less than time_limit_s')
    for field in ('partition', 'account', 'qos'):
        if slurm[field] and not fullmatch(r'[A-Za-z0-9_.-]+', slurm[field]):
            raise ValueError('Invalid slurm.' + field)
    container = config['container']
    if not fullmatch(r'[a-z0-9][a-z0-9_.-]{0,63}', container['workspace']):
        raise ValueError('Invalid container.workspace')
    if container['image'] and not fullmatch(r'[A-Za-z0-9][A-Za-z0-9._:/@-]{0,255}', container['image']):
        raise ValueError('Invalid container.image')
    if container['memory_gib'] < 0 or not math.isfinite(container['cpus']) or container['cpus'] < 0:
        raise ValueError('Container resource limits must be finite and nonnegative')


def rendering_environment(device, system, base):
    """Set the chosen backend explicitly; never silently fall back to software."""
    env = dict(base)
    for key in ('MUJOCO_GL', 'PYOPENGL_PLATFORM', 'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER'):
        env.pop(key, None)
    if device == 'native':
        if system != 'Darwin':
            raise ValueError('native rendering requires macOS; select nvidia or cpu on Linux')
    elif device == 'cpu':
        if system != 'Linux':
            raise ValueError('CPU OSMesa rendering requires Linux, including a Linux Docker container')
        env.update(MUJOCO_GL='osmesa', PYOPENGL_PLATFORM='osmesa',
                   LIBGL_ALWAYS_SOFTWARE='true', GALLIUM_DRIVER='llvmpipe', CUDA_VISIBLE_DEVICES='')
    elif device == 'nvidia':
        if system != 'Linux':
            raise ValueError('NVIDIA EGL rendering requires Linux; select native on macOS')
        env.update(MUJOCO_GL='egl', PYOPENGL_PLATFORM='egl', LIBGL_ALWAYS_SOFTWARE='false')
    else:
        raise ValueError('Unknown rendering device')
    return env


MODELS = ROOT/'models.json'


def model_catalog(harness, path=None):
    """One harness's model catalog: its section of models.json, or a file holding
    only that section (a run's frozen copy, or one written for a batch)."""
    import json
    document = json.loads(Path(path or MODELS).read_text())
    if 'harnesses' in document:
        if harness not in document['harnesses']: raise ValueError('No model catalog for harness: '+str(harness))
        return document['harnesses'][harness]
    return document
