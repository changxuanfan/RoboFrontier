"""Resolve and validate one public configuration before preparing frozen inputs."""
from copy import deepcopy
import math
from pathlib import Path
import tomllib

ROOT = Path(__file__).resolve().parents[1]
DEFAULT = ROOT / 'robofrontier.toml'
TOPOLOGIES = {
    'single': 'centralized',
    'controller-worker': 'hierarchical',
    'worker-worker': 'peer',
    'adaptive': 'adaptive',
}
SCHEMA = {
    'schema_version': int,
    'policy': dict.fromkeys(('engine', 'profile', 'effort', 'topology'), str),
    'batch': {'parallel': int, 'startup_interval_s': float, 'task_wall_limit_s': float, 'startup_timeout_s': float},
    'selection': {'families': list, 'cases': list, 'level': int, 'min_arms': bool},
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
    'factory': {'data_root': str, 'asset_lock': str, 'source': str, 'device': str,
                'blender': str, 'mode': str, 'views': list, 'width': int, 'height': int,
                'samples': int, 'duration_s': float, 'import_speedup': float, 'parallel': int},
    'oracle': {'wall_limit_s': float, 'stop_grace_s': float,
               'evaluation_mode': str,
               'mosaic_planning_workers': int, 'mosaic_physics_workers': int,
               'mosaic_max_goals': int},
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


def load_configuration(path=None, overrides=None):
    """Layer a partial user TOML and explicit options over checked-in defaults.

    Secrets and arbitrary environment expansion are deliberately not supported.
    Old prepared runs keep their frozen configuration and are never re-resolved.
    """
    with DEFAULT.open('rb') as stream:
        result = tomllib.load(stream)
    updates = {}
    if path is not None and Path(path).resolve() != DEFAULT.resolve():
        with Path(path).open('rb') as stream:
            updates = tomllib.load(stream)
    version = (overrides or {}).get('schema_version', updates.get('schema_version', result['schema_version']))
    shape = _configuration_shape(version)
    # Select versioned defaults before merging. Only default fields are pruned;
    # explicitly supplied options from a different schema are still errors.
    result = {key: ({field: result[key][field] for field in kind}
                    if isinstance(kind, dict) else result[key]) for key,kind in shape.items()}
    _merge(result, updates)
    if overrides:
        _merge(result, deepcopy(overrides))
    # Engine-only Claude selections use subscription authentication for scripts.
    # Explicit API/saved-login profiles and frozen configurations remain exact.
    if (result['policy']['engine'] == 'claude'
            and 'profile' not in updates.get('policy', {})
            and 'profile' not in (overrides or {}).get('policy', {})):
        result['policy']['profile'] = 'haiku_subscription_token'
    validate_configuration(result)
    return result


def _configuration_shape(version):
    if type(version) is not int or version not in (1, 2, 3, 4, 5, 6, 7, 8):
        raise ValueError('Unsupported configuration schema_version')
    # Older frozen configurations remain exact. Do not append new Factory or
    # Oracle defaults to an already-hashed experiment configuration.
    shape = {k: dict(v) if isinstance(v, dict) else v for k, v in SCHEMA.items()
             if (version >= 2 or k != 'factory') and (version >= 3 or k != 'oracle')}
    if version == 3:
        shape['oracle'].pop('evaluation_mode')
    if version < 5:
        shape['runtime'].pop('codex_tool_backend')
    if version < 6:
        for field in ('auth_mode', 'credential_store'):
            shape['slurm'].pop(field)
    if version < 7:
        for field in ('egress_mode', 'egress_root', 'egress_wait_s'):
            shape['slurm'].pop(field)
    if version < 8:
        shape['slurm'].pop('egress_pause_s')
    return shape


def validate_configuration(config):
    version = config.get('schema_version')
    shape = _configuration_shape(version)
    _validate_shape(config, shape)
    def choice(section, field, allowed):
        if config[section][field] not in allowed:
            raise ValueError(f'Invalid {section}.{field}: choose from {", ".join(map(str, allowed))}')

    choice('policy', 'engine', ('codex', 'claude'))
    choice('policy', 'topology', TOPOLOGIES)
    choice('policy', 'effort', ('minimal', 'low', 'medium', 'high', 'xhigh', 'max'))
    from re import fullmatch
    if not fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', config['policy']['profile']):
        raise ValueError('Invalid policy.profile identifier')
    batch = config['batch']
    if type(batch['parallel']) is not int or not 1 <= batch['parallel'] <= 36:
        raise ValueError('batch.parallel must be 1..36')
    for field in ('startup_interval_s', 'task_wall_limit_s', 'startup_timeout_s'):
        value = batch[field]
        if type(value) not in (int, float) or not math.isfinite(value) or value < 0 or (
                field != 'startup_interval_s' and value == 0):
            raise ValueError('Invalid batch.' + field)
    if config['policy']['engine'] == 'claude' and batch['task_wall_limit_s'] > 86400:
        raise ValueError('The current Claude engineering runner supports at most 86400 seconds')
    choice('selection', 'level', (0, 1, 2, 3))
    if type(config['selection']['level']) is not int:
        raise ValueError('selection.level must be an integer')
    for field in ('families', 'cases'):
        values = config['selection'][field]
        if not all(type(value) is str and value for value in values) or len(set(values)) != len(values):
            raise ValueError('selection.' + field + ' must contain distinct nonempty strings')
    choice('render', 'device', ('nvidia', 'cpu', 'native'))
    choice('render', 'observation_profile', ('jpeg_896x560_q85', 'png_1280x800'))
    choice('runtime', 'codex_home_scope', ('task', 'shared', 'job') if version >= 6 else ('task', 'shared'))
    if version >= 5:
        choice('runtime', 'codex_tool_backend', ('native', 'landlock-v1'))
        if config['policy']['engine'] != 'codex' and config['runtime']['codex_tool_backend'] != 'native':
            raise ValueError('codex_tool_backend applies only to the Codex engine')
    choice('container', 'seccomp_profile', ('default', 'unconfined'))
    choice('evidence', 'archive_format', ('zip',))
    if config['evidence']['auto_archive'] and not config['evidence']['auto_collect']:
        raise ValueError('evidence.auto_archive requires evidence.auto_collect')
    if config['evidence']['delete_sources']:
        raise ValueError('Automatic source deletion is not supported; verify restored evidence before explicit cleanup')
    slurm = config['slurm']
    if version >= 6:
        choice('slurm', 'auth_mode', ('api', 'subscription'))
        subscription = slurm['auth_mode'] == 'subscription'
        if subscription:
            if (config['policy']['engine'] != 'codex'
                    or config['runtime']['codex_home_scope'] != 'job'
                    or config['runtime']['codex_home']
                    or config['runtime']['codex_tool_backend'] != 'landlock-v1'):
                raise ValueError('Slurm subscription requires Codex job scope, an automatic home and landlock-v1')
            path = Path(slurm['credential_store'])
            if not path.is_absolute() or '..' in path.parts:
                raise ValueError('slurm.credential_store must be an absolute private directory')
        elif slurm['credential_store'] or config['runtime']['codex_home_scope'] == 'job':
            raise ValueError('Job scope and credential_store require slurm.auth_mode=subscription')
    if version >= 7:
        choice('slurm', 'egress_mode', ('direct', 'mac-ssh'))
        if version >= 8:
            if not 0 <= slurm['egress_pause_s'] <= 600:
                raise ValueError('slurm.egress_pause_s must be between 0 and 600')
            if slurm['egress_pause_s'] and slurm['egress_mode'] != 'mac-ssh':
                raise ValueError('Short network pause requires mac-ssh egress')
        if not 1 <= slurm['egress_wait_s'] <= 3600:
            raise ValueError('slurm.egress_wait_s must be between 1 and 3600')
        if slurm['egress_mode'] == 'mac-ssh':
            path = Path(slurm['egress_root'])
            if slurm['auth_mode'] != 'subscription' or not path.is_absolute() or '..' in path.parts:
                raise ValueError('Mac egress requires subscription mode and an absolute private egress_root')
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
    if version >= 2:
        factory = config['factory']
        choice('factory', 'source', ('release', 'imported'))
        choice('factory', 'device', ('OPTIX', 'CUDA', 'METAL', 'CPU'))
        choice('factory', 'mode', ('desks', 'promo'))
        if (not factory['views'] or any(type(v) is not str or v not in ('front', 'side') for v in factory['views'])
                or len(set(factory['views'])) != len(factory['views'])):
            raise ValueError('factory.views must select distinct front/side views')
        if not factory['data_root'].strip() or not factory['asset_lock'].strip():
            raise ValueError('Factory data_root and asset_lock must be nonempty paths')
        for field in ('width', 'height', 'samples', 'parallel'):
            if factory[field] <= 0:
                raise ValueError('factory.'+field+' must be positive')
        if factory['width'] % 2 or factory['height'] % 2:
            raise ValueError('Factory video dimensions must be even')
        for field in ('duration_s', 'import_speedup'):
            value = factory[field]
            # duration_s 0 keeps the full timeline; import_speedup 0 uses the family's release speedup.
            if not math.isfinite(value) or value < 0:
                raise ValueError('Invalid factory.'+field)
    if version >= 3:
        oracle = config['oracle']
        if version >= 4:
            choice('oracle', 'evaluation_mode', ('task-reference', 'strict-process'))
        for field in ('wall_limit_s', 'stop_grace_s'):
            if not math.isfinite(oracle[field]) or oracle[field] <= 0:
                raise ValueError('oracle.'+field+' must be positive and finite')
        for field in ('mosaic_planning_workers', 'mosaic_physics_workers', 'mosaic_max_goals'):
            if oracle[field] < 0:
                raise ValueError('oracle.'+field+' must be nonnegative')


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
