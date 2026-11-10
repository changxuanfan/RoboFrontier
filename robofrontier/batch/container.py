"""Run native benchmark commands in local Docker volumes, exporting stopped ZIPs."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid

from ..configuration import ROOT, validate_configuration
from ..runtime.setup import write_json

CONTAINER_ROOT = '/opt/RoboFrontier'
COMMANDS = {'bootstrap', 'config', 'plan', 'prepare', 'doctor', 'preflight', 'run', 'status',
            'stop', 'collect', 'archive', 'extract'}


def _auth_arguments(arguments):
    native = arguments[1:]
    valid = (native[:2] in (['codex', 'login'], ['codex', 'logout']) or
             native == ['claude', 'setup-token'])
    if not valid:
        raise ValueError('Supported auth actions: codex login/logout or claude setup-token')
    return native


def validate_arguments(arguments):
    """Resolve native syntax/help before any Docker, configuration or auth work."""
    arguments = list(arguments or ['plan'])
    action = arguments[0]
    if action not in COMMANDS | {'build', 'auth'}:
        raise ValueError('Unsupported container command')
    if '--config' in arguments or '--result-file' in arguments:
        raise ValueError('Pass the host --config before container; result-file is managed by the wrapper')
    if action == 'build':
        parser = argparse.ArgumentParser(prog='robofrontier container build',
            description='Build the committed source image. This command accepts no options.')
        parser.parse_args(arguments[1:])
    elif action == 'auth':
        if any(value in ('-h', '--help') for value in arguments[1:]):
            parser = argparse.ArgumentParser(prog='robofrontier container auth',
                description='Authenticate native Codex or Claude in persistent private state.',
                epilog='Supported actions: codex login [options], codex logout [options], '
                       'or claude setup-token. Native login options are forwarded unchanged.')
            parser.print_help()
            parser.exit()
        _auth_arguments(arguments)
    else:
        from ..cli import argument_parser
        argument_parser(prog='robofrontier container').parse_args(arguments)
    return arguments


def _digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _toml(config):
    """Encode the validated, secret-free public schema without environment expansion."""
    validate_configuration(config)
    def value(item):
        if isinstance(item, bool):
            return str(item).lower()
        return json.dumps(item, ensure_ascii=True, allow_nan=False)
    lines = []
    for key, item in config.items():
        if not isinstance(item, dict):
            lines.append(key+' = '+value(item))
    for section, fields in config.items():
        if isinstance(fields, dict):
            lines.extend(['', '['+section+']'])
            lines.extend(key+' = '+value(item) for key, item in fields.items())
    return '\n'.join(lines)+'\n'


def _settings(arguments, config):
    # Provider/render overrides use the same fully spelled native CLI flags.
    parser = argparse.ArgumentParser(add_help=False, allow_abbrev=False)
    for option in ('engine', 'profile', 'effort', 'render'):
        parser.add_argument('--'+option)
    options, _ = parser.parse_known_args(arguments[1:])
    result = deepcopy(config)
    for option in ('engine', 'profile', 'effort'):
        if getattr(options, option) is not None:
            result['policy'][option] = getattr(options, option)
    if options.engine is not None and options.engine != config['policy']['engine'] and options.profile is None:
        # The host profile belongs to the other engine. Select by engine only, as the
        # native CLI does (Claude: the subscription-token profile).
        from ..configuration import load_configuration
        result['policy']['profile'] = load_configuration(overrides={'policy': {'engine': options.engine}})['policy']['profile']
    if options.render is not None:
        result['render']['device'] = options.render
    validate_configuration(result)
    return result


def _volumes(config, root):
    scope = hashlib.sha256(str(Path(root).resolve()).encode()).hexdigest()[:12]
    prefix = 'robofrontier-'+scope+'-'+config['container']['workspace'].lower()
    return {'runs': prefix+'-runs', 'state': prefix+'-state'}


def _mounts(volumes):
    return ['--mount', 'type=volume,src='+volumes['runs']+',dst='+CONTAINER_ROOT+'/runs',
            '--mount', 'type=volume,src='+volumes['state']+',dst='+CONTAINER_ROOT+'/.robofrontier']


def _ensure_volumes(volumes):
    for name in volumes.values():
        subprocess.run(['docker', 'volume', 'create', '--driver', 'local', name],
                       check=True, stdout=subprocess.DEVNULL)
        result = subprocess.check_output(['docker', 'volume', 'inspect', '--format',
            '{{json .}}', name], text=True)
        info = json.loads(result)
        if info['Driver'] != 'local' or info.get('Options'):
            raise ValueError('Use a plain local Docker volume; network/custom volume options are unsupported')


def _image(config, root):
    commit = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=root, text=True).strip()
    image = config['container']['image'] or 'robofrontier:'+commit[:12]
    return image, commit


def _ensure_image(image, commit, root, *, rebuild=False):
    inspected = subprocess.run(['docker', 'image', 'inspect', '--format',
        '{{index .Config.Labels "org.opencontainers.image.revision"}}', image],
        capture_output=True, text=True)
    if inspected.returncode == 0 and not rebuild:
        if inspected.stdout.strip() != commit:
            raise ValueError('Container image source revision differs; rebuild or select the matching image')
        return
    if subprocess.check_output(['git', 'status', '--porcelain', '--untracked-files=no'], cwd=root, text=True):
        raise ValueError('Commit tracked changes before building a frozen container image')
    with tempfile.TemporaryDirectory(prefix='rf-build-') as temporary:
        snapshot = Path(temporary)/'source.tar'
        subprocess.run(['git', 'archive', '--format=tar', '--output='+str(snapshot), commit], cwd=root, check=True)
        # Building from Git's tracked snapshot excludes .env, auth and run data
        # regardless of what happens to exist in the operator's worktree.
        with snapshot.open('rb') as stream:
            subprocess.run(['docker', 'build', '--file', 'docker/Dockerfile', '--tag', image,
                '--label', 'org.opencontainers.image.revision='+commit, '-'], stdin=stream, check=True)


def _batch_argument(arguments):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument('batch')
    parser.add_argument('--engineering', action='store_true')
    parsed, _ = parser.parse_known_args(arguments[1:])
    path = Path(parsed.batch)
    if path.is_absolute() or not path.parts or path.parts[0] != 'runs' or '..' in path.parts:
        raise ValueError('Container batch paths must be relative paths under runs/')
    return parsed.batch


def _frozen_settings(arguments, config, image, volumes):
    if arguments[0] != 'run':
        return config
    batch = _batch_argument(arguments)
    code = 'import json,sys;print(json.dumps(json.load(open(sys.argv[1]))))'
    document = subprocess.check_output(['docker', 'run', '--rm', *_mounts(volumes),
        '--entrypoint', 'python', image, '-c', code,
        CONTAINER_ROOT+'/'+batch+'/effective-config.json'], text=True)
    result = json.loads(document)
    validate_configuration(result)
    return result


def _credential_environment(config, base):
    from ..cli import _catalog
    selected = _catalog(config)['profiles'][config['policy']['profile']]
    result = {}
    for field in ('env_key', 'base_url_env'):
        name = selected.get(field)
        if name and base.get(name):
            result[name] = base[name]
    return result


def _command(arguments, config, image, volumes, name, settings_file, environment):
    command = ['docker', 'run', '--name', name, '--init', '--sig-proxy=false', *_mounts(volumes),
               '--mount', 'type=bind,src='+str(settings_file)+',dst=/run/robofrontier.toml,readonly',
               '--env', 'CODEX_HOME='+CONTAINER_ROOT+'/.robofrontier/subscription',
               '--env', 'TMPDIR=/tmp/robofrontier',
               '--env', 'CLAUDE_CONFIG_DIR='+CONTAINER_ROOT+'/.robofrontier/claude-auth',
               '--env', 'OMP_NUM_THREADS=1', '--env', 'OPENBLAS_NUM_THREADS=1']
    resources = config['container']
    if (resources['seccomp_profile'] == 'unconfined' and
            config['policy']['engine'] == 'codex' and arguments[0] in ('doctor', 'preflight', 'run')):
        command.extend(['--security-opt', 'seccomp=unconfined'])
    if resources['memory_gib']:
        command.append('--memory='+str(resources['memory_gib'])+'g')
    if resources['cpus']:
        command.append('--cpus='+str(resources['cpus']))
    for key in sorted(environment):
        command.extend(['--env', key])  # Values stay in the process environment.
    if arguments[0] in ('doctor', 'run') and config['render']['device'] == 'nvidia':
        if platform.system() != 'Linux':
            raise ValueError('NVIDIA Docker execution requires Linux; prepare CPU-rendered tasks for macOS Docker')
        command.extend(['--gpus', 'all', '--env', 'NVIDIA_DRIVER_CAPABILITIES=compute,graphics,utility'])
    if arguments[0] == 'auth':
        native = _auth_arguments(arguments)
        if sys.stdin.isatty():
            command.extend(['--interactive', '--tty'])
        else:
            command.append('--interactive')
        command.extend(['--entrypoint', native[0], image])
        if native[0] == 'codex':
            command.extend(['-c', 'cli_auth_credentials_store="file"'])
        return [*command, *native[1:]]
    return [*command, image, '--config', '/run/robofrontier.toml',
            '--result-file', '/tmp/robofrontier-result.json', *arguments]


def _running(name):
    result = subprocess.run(['docker', 'inspect', '--format', '{{.State.Running}}', name],
                            capture_output=True, text=True)
    if result.returncode:
        return None
    return result.stdout.strip() == 'true'


def _copy_result(name, output):
    result = subprocess.run(['docker', 'cp', name+':/tmp/robofrontier-result.json', str(output)],
                            capture_output=True, text=True)
    return json.loads(output.read_text()) if result.returncode == 0 else None


def _export_archive(name, receipt, destination):
    archive = receipt.get('archive')
    expected = receipt.get('archive_sha256')
    if not archive:
        return None
    path = Path(archive)
    if (not path.is_relative_to(CONTAINER_ROOT+'/runs/exports') or path.suffix != '.zip'
            or '..' in path.parts or not isinstance(expected, str) or len(expected) != 64):
        raise ValueError('Unexpected container evidence archive reference')
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    output = destination/path.name
    if output.exists():
        if _digest(output) != expected:
            raise ValueError('A different exported archive already exists: ' + str(output))
        return output
    with tempfile.TemporaryDirectory(prefix='.rf-export-', dir=destination) as temporary:
        staged = Path(temporary)/path.name
        subprocess.run(['docker', 'cp', name+':'+str(path), str(staged)], check=True)
        if _digest(staged) != expected:
            raise ValueError('Exported archive SHA-256 mismatch')
        with staged.open('rb') as stream:
            os.fsync(stream.fileno())
        os.link(staged, output)  # Publish without replacing another result.
    return output


def execute(arguments, config, *, root=ROOT):
    """Prepare all directories/volumes and run one explicit native command.

    A disconnected/live container is retained for review; it is never blindly
    restarted. Only stopped ZIP evidence is exported to the host.
    """
    from robofrontier.batch.prepare import load_env
    arguments = validate_arguments(arguments)
    if shutil.which('docker') is None:
        raise ValueError('Docker CLI is not installed')
    daemon = subprocess.run(['docker', 'version', '--format', '{{.Server.Version}}'],
                            capture_output=True, text=True)
    if daemon.returncode or not daemon.stdout.strip():
        raise ValueError('Docker daemon is unavailable; start Docker Desktop or the Linux Docker service')
    root = Path(root).resolve()
    load_env(root/'.env')
    config = _settings(arguments, config)
    image, commit = _image(config, root)
    _ensure_image(image, commit, root, rebuild=arguments[0] == 'build')
    volumes = _volumes(config, root)
    if arguments[0] == 'build':
        return {'exit_code': 0, 'image': image, 'source_commit': commit, 'model_calls': 0}
    _ensure_volumes(volumes)
    launch_workspace = config['container']['workspace']
    config = _frozen_settings(arguments, config, image, volumes)
    if config['container']['workspace'] != launch_workspace:
        raise ValueError('Frozen batch belongs to a different container workspace')
    credentials = {} if arguments[0] == 'auth' else _credential_environment(config, os.environ)
    name = 'rf-'+uuid.uuid4().hex[:20]
    record = root/'.robofrontier/containers'/config['container']['workspace']/'commands'/(name+'.json')
    state = {'schema': 'robofrontier.container-command.v1', 'container': name, 'image': image,
             'source_commit': commit, 'volumes': volumes, 'started_at': time.time(),
             'command': arguments[:3] if arguments[0] == 'auth' else arguments, 'status': 'starting'}
    write_json(record, state)
    with tempfile.TemporaryDirectory(prefix='rf-container-') as temporary:
        settings = Path(temporary)/'effective.toml'
        settings.write_text(_toml(config))
        settings.chmod(0o600)
        command = _command(arguments, config, image, volumes, name, settings, credentials)
        env = {**os.environ, **credentials}
        process = subprocess.Popen(command, env=env, start_new_session=True)
        interrupted = False
        try:
            code = process.wait()
        except KeyboardInterrupt:
            interrupted = True
            # Whatever happens while stopping (a slow docker command, a second Ctrl-C), fall
            # through to the record below so a live container is retained for review.
            try:
                if arguments[0] == 'run':
                    subprocess.run(['docker', 'exec', name, 'python', '-m', 'robofrontier.cli',
                        'stop', _batch_argument(arguments)], check=False, timeout=30)
                else:
                    subprocess.run(['docker', 'stop', '--time', '30', name], check=False, timeout=45)
            except (subprocess.SubprocessError, OSError, KeyboardInterrupt):
                pass
            try:
                code = process.wait(timeout=180)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                code = 130
        live = _running(name)
        if live is not False and code == 0:
            code = 2
        state.update(exit_code=code, interrupted=interrupted, finished_at=time.time(),
                     status='still_running_needs_review' if live else 'closed' if code == 0 else 'needs_review')
        if live:
            state['note'] = 'Container retained; inspect/stop it. No automatic restart or active database export.'
        elif live is False:
            try:
                receipt = _copy_result(name, Path(temporary)/'result.json')
                if receipt:
                    state['result'] = receipt
                    output = _export_archive(name, receipt, root/'runs/container-exports'/config['container']['workspace'])
                    if output:
                        state['exported_archive'] = str(output)
                elif code == 0 and arguments[0] != 'auth':
                    state.update(exit_code=2, status='missing_result_needs_review')
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                state.update(status='export_failed_needs_review', exit_code=2,
                             error_type=type(error).__name__, container_retained=True)
                write_json(record, state)
                raise
            # Native traces/auth remain in their separate persistent volumes.
            subprocess.run(['docker', 'rm', name], check=True, stdout=subprocess.DEVNULL)
        write_json(record, state)
    return state
