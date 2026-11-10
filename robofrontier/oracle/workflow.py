"""Freeze and supervise privileged native Oracles without a model session.

New executions use current released scene inputs, never the historical witness
paths in the release's ``oracle`` presentation inventory. A prepared execution
is single-use and host-local. Its native evaluator/report remain authoritative;
the supervisor owns only lifecycle, an explicit engineering deadline and logs.
"""
from contextlib import contextmanager
import fcntl
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import subprocess
import sys
import time

from ..configuration import ROOT, load_configuration, rendering_environment, validate_configuration
from ..runtime.setup import write_json

ENTRIES = {
    'transport': 'run_transport_full_oracle.py',
    'mosaic': 'run_mosaic_oracle.py',
    'relay': 'run_relay_live_oracle.py',
    'dial': 'run_blind_dial_oracle.py',
}


def _sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _read(path):
    return json.loads(Path(path).read_text())


def add_arguments(subparsers):
    parser = subparsers.add_parser('oracle', help='Privileged native reference execution; no model calls')
    actions = parser.add_subparsers(dest='oracle_action', required=True)
    for name in ('plan', 'prepare'):
        command = actions.add_parser(name)
        command.add_argument('--cases', nargs='+')
        command.add_argument('--families', nargs='+', choices=tuple(ENTRIES))
        command.add_argument('--level', type=int, choices=(1, 2, 3))
        command.add_argument('--min-arms', action='store_true', default=None)
        if name == 'prepare':
            command.add_argument('--output', type=Path, required=True)
            command.add_argument('--codebook', type=Path, help='Optional evaluator-only Dial puzzle; never sent to its solver')
            command.add_argument('--render', choices=('nvidia', 'cpu', 'native'))
            command.add_argument('--wall-limit-s', type=float)
            command.add_argument('--evaluation-mode', choices=('task-reference', 'strict-process'))
            command.add_argument('--mosaic-max-goals', type=int)
            command.add_argument('--mosaic-planning-workers', type=int)
            command.add_argument('--physics-profile', choices=('realtime-v1', 'realtime-v2'),
                                 help='Frozen into the Oracle harness; default is full physics')
    for name in ('run', 'status', 'stop'):
        command = actions.add_parser(name)
        command.add_argument('execution', type=Path)


def plan(config):
    if 'oracle' not in config:
        raise ValueError('Use current operator settings to prepare a new Oracle execution')
    from robofrontier.batch.prepare import select_cases
    selection = config['selection']
    selected = select_cases(selection['families'] or None, selection['cases'] or None,
                            selection['level'] or None, selection['min_arms'])
    return {'schema': 'robofrontier.oracle-plan.v1', 'model_calls': 0, 'physics_stepped': False,
            'task_count': len(selected), 'jobs': selected,
            'input_scope': 'Current released scenes; historical witness results do not qualify new executions',
            'execution_scope': 'Privileged engineering reference, not a policy benchmark',
            'supervision': config['oracle'], 'prepare_scope': 'Exactly one selected case per execution directory'}


def _committed_source():
    if subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip():
        raise ValueError('Commit the complete Oracle executor before preparation')
    return subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()


def _versions():
    try:
        return {name: importlib.metadata.version(name) for name in ('mujoco', 'numpy', 'greenlet')}
    except importlib.metadata.PackageNotFoundError as error:
        raise ValueError('Install Oracle dependencies with uv sync --locked --extra oracle') from error


def _scene_inventory(scene, case):
    """Verify all frozen source assets without constructing or stepping a world."""
    scene = Path(scene).resolve()
    inventory = dict(case['source_files'])
    workstation = _read(scene/'workstation.json')
    if (workstation['case']['id'] != case['id'] or
            workstation['scene_sha256'] != inventory['scene.xml']):
        raise ValueError('Oracle workstation identity differs from its released case')
    for asset in workstation['assets']:
        name = asset['path']
        path = (scene/name).resolve()
        if not path.is_relative_to(scene) or not path.is_file():
            raise ValueError('Oracle asset missing or outside workstation: '+name)
        if name in inventory and inventory[name] != asset['sha256']:
            raise ValueError('Conflicting Oracle asset checksum: '+name)
        inventory[name] = asset['sha256']
    for name, checksum in inventory.items():
        if _sha(scene/name) != checksum:
            raise ValueError('Oracle scene input changed: '+name)
    task = _read(scene/'task.json')
    if task['id'] != case['id'] or task['scene_sha256'] != inventory['scene.xml']:
        raise ValueError('Oracle task/scene identity mismatch')
    return inventory, task


def prepare(output, config, *, codebook=None, physics_profile=None):
    from ..tasks.families import RELEASE, resolve_case
    from ..tasks.config import load_harness
    from .source_snapshot import freeze_executor
    from robofrontier.batch.handoff import setup_assets
    selected = plan(config)['jobs']
    if len(selected) != 1:
        raise ValueError('Oracle prepare requires exactly one selected case; use --cases CASE_ID')
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new Oracle directory; existing executions are never overwritten')
    if codebook is not None and selected[0]['family'] != 'dial':
        raise ValueError('An evaluator codebook is supported only for Dial')
    commit, versions = _committed_source(), _versions()
    setup_assets()
    family, _, case = resolve_case(selected[0]['case_id'], purpose='gpt')
    scene = (ROOT/case['directory']).resolve()
    inventory, task = _scene_inventory(scene, case)
    puzzle = None
    if family == 'dial':
        from ..tasks.dial import alphabet
        symbols = alphabet(task)
        puzzle = _read(codebook) if codebook is not None else {
            'code_symbols': [secrets.choice(symbols) for _ in task['dials']]}
        if not isinstance(puzzle, dict):
            raise ValueError('Dial codebook must be an evaluator-only JSON object')
        values = puzzle.get('code_symbols')
        if (set(puzzle) != {'code_symbols'} or not isinstance(values, list) or
                len(values) != len(task['dials']) or any(type(x) is not int or x not in symbols for x in values)):
            raise ValueError('Dial codebook requires one configured nonzero symbol per dial')
    # Absolute host-local scene path avoids silently selecting a legacy folder
    # when each native runner rebinds its imports to the frozen source tree.
    current = _read(ROOT/'benchmark/release.json')['families'][family]['catalog']
    if _sha(ROOT/current['path']) != current['sha256']:
        raise ValueError('Released Oracle catalog changed')
    catalog = _read(ROOT/current['path'])
    native = [row for row in catalog['cases'] if row['id'] == case['id']]
    if len(native) != 1 or native[0]['family'] != family or (ROOT/native[0]['directory']).resolve() != scene:
        raise ValueError('Native Oracle catalog differs from the released scene')
    output.mkdir(parents=True, exist_ok=False)
    private = output/'private'
    private.mkdir(mode=0o700)
    harness = load_harness(ROOT/'configs/harness-frontier-v2-servo2.json')
    harness['observation_image_profile'] = config['render']['observation_profile']
    if physics_profile is not None:
        harness['physics_profile'] = physics_profile
    write_json(private/'harness.json', harness)
    catalog['cases'] = [{**native[0], 'directory': str(scene)}]
    write_json(private/'catalog.json', catalog)
    if puzzle is not None:
        write_json(private/'codebook.json', puzzle)
        (private/'codebook.json').chmod(0o600)
    frozen = freeze_executor(ROOT, private/'executor', private/'harness.json', private/'catalog.json')
    # Relay's native frozen entry reads this original launch provenance.
    write_json(private/'run.json', {'git_commit': commit, 'worktree': str(ROOT), 'case_id': case['id']})
    write_json(output/'effective-config.json', config)
    pinned = ['effective-config.json', 'private/harness.json', 'private/catalog.json',
              'private/run.json', 'private/executor/snapshot.json']
    if puzzle is not None:
        pinned.append('private/codebook.json')
    protocol = None
    if config['schema_version'] >= 4:
        from .protocol import PROTOCOL_SCHEMA
        protocol = dict(schema=PROTOCOL_SCHEMA, mode=config['oracle']['evaluation_mode'],
                        case_id=case['id'], source_task_sha256=inventory['task.json'],
                        source_scene_sha256=inventory['scene.xml'],
                        evaluation_semantics='terminal_outcome_v2')
        write_json(private/'execution-protocol.json', protocol)
        pinned.append('private/execution-protocol.json')
    pinned.extend('private/executor/'+name for name in _read(frozen/'snapshot.json')['files'])
    document = {'schema': 'robofrontier.oracle-execution.v1', 'case_id': case['id'], 'family': family,
                'git_commit': commit, 'source_root': str(ROOT), 'prepared_directory': str(output),
                'source_directory': str(scene), 'source_sha256': inventory,
                'release_sha256': _sha(ROOT/RELEASE), 'versions': versions,
                'input_sha256': {name: _sha(output/name) for name in pinned},
                'qualification': 'Unexecuted privileged reference; no borrowed historical success',
                'clock': 'Owner-launch engineering elapsed time; includes planning and review pauses',
                'dial_puzzle': ('explicit evaluator-only input' if codebook is not None else
                                'fresh uniformly sampled evaluator-only input') if puzzle is not None else None}
    if protocol is not None:
        document['execution_protocol'] = 'private/execution-protocol.json'
    write_json(output/'oracle.json', document)
    write_json(output/'oracle-status.json', {'phase': 'prepared', 'case_id': case['id'], 'model_calls': 0})
    return {'execution': str(output), 'case_id': case['id'], 'model_calls': 0, 'physics_stepped': False,
            'manifest_sha256': _sha(output/'oracle.json')}


def _load(execution):
    root = Path(execution).resolve()
    document = _read(root/'oracle.json')
    if document.get('schema') != 'robofrontier.oracle-execution.v1' or document.get('prepared_directory') != str(root):
        raise ValueError('Expected an unchanged host-local Oracle preparation')
    if document.get('family') not in ENTRIES:
        raise ValueError('Unknown Oracle family')
    for name, checksum in document['input_sha256'].items():
        path = root/name
        if not path.resolve().is_relative_to(root) or _sha(path) != checksum:
            raise ValueError('Frozen Oracle input changed: '+name)
    snapshot = _read(root/'private/executor/snapshot.json')
    expected = {'effective-config.json', 'private/harness.json', 'private/catalog.json',
                'private/run.json', 'private/executor/snapshot.json'}
    expected.update('private/executor/'+name for name in snapshot['files'])
    if document['family'] == 'dial':
        expected.add('private/codebook.json')
    if document.get('execution_protocol'):
        if document['execution_protocol'] != 'private/execution-protocol.json':
            raise ValueError('Unknown Oracle execution protocol path')
        expected.add('private/execution-protocol.json')
    if set(document['input_sha256']) != expected:
        raise ValueError('Oracle frozen-input inventory is incomplete or has unknown entries')
    for name, checksum in snapshot['files'].items():
        if document['input_sha256'].get('private/executor/'+name) != checksum:
            raise ValueError('Oracle source snapshot inventory differs: '+name)
    catalog = _read(root/'private/executor/inputs/catalog.json')['cases']
    if (len(catalog) != 1 or catalog[0]['id'] != document['case_id'] or
            catalog[0]['family'] != document['family'] or catalog[0]['directory'] != document['source_directory']):
        raise ValueError('Oracle manifest and frozen catalog identify different scenes')
    config = _read(root/'effective-config.json')
    validate_configuration(config)
    if 'oracle' not in config:
        raise ValueError('Expected an Oracle configuration')
    if (config['schema_version'] >= 4) != bool(document.get('execution_protocol')):
        raise ValueError('Oracle execution protocol missing or unexpected')
    if document.get('execution_protocol'):
        from .protocol import effective_task
        protocol = _read(root/document['execution_protocol'])
        effective_task(document['source_directory'], _read(Path(document['source_directory'])/'task.json'), protocol)
        if protocol['mode'] != config['oracle']['evaluation_mode']:
            raise ValueError('Oracle execution mode differs from its frozen configuration')
    for name, checksum in document['source_sha256'].items():
        if _sha(Path(document['source_directory'])/name) != checksum:
            raise ValueError('Oracle source scene changed since preparation: '+name)
    return root, document, config


def _command(root, document, config):
    frozen = root/'private/executor'
    family = document['family']
    command = [sys.executable, str(frozen/'scripts'/ENTRIES[family]),
               '--case', document['case_id'], '--output', str(root/'trial'),
               '--harness', str(frozen/'inputs/harness.json')]
    if family in ('transport', 'mosaic'):
        command.extend(['--catalog', str(frozen/'inputs/catalog.json')])
    if family == 'mosaic':
        options = config['oracle']
        command.extend(['--planning-workers', str(options['mosaic_planning_workers']),
                        '--physics-workers', str(options['mosaic_physics_workers'])])
        if options['mosaic_max_goals']:
            command.extend(['--max-goals', str(options['mosaic_max_goals'])])
    elif family == 'relay':
        command.extend(['--frozen', '--scene', document['source_directory'], '--wall-s', '0'])
    elif family == 'dial':
        command.extend(['--codebook', str(root/'private/codebook.json'), '--wall-s', '0'])
    env = rendering_environment(config['render']['device'], platform.system(), os.environ)
    from .protocol import PROTOCOL_ENV
    env.pop(PROTOCOL_ENV, None)
    if document.get('execution_protocol'):
        env[PROTOCOL_ENV] = str(root/document['execution_protocol'])
    env.update(PYTHONPATH=str(frozen), ROBOFRONTIER_ORACLE_FROZEN_ROOT=str(frozen),
               TRANSPORT_ORACLE_COMMIT=document['git_commit'], TRANSPORT_ORACLE_WORKTREE=document['source_root'],
               ROBOFRONTIER_MOSAIC_COMMIT=document['git_commit'], PYTHONUNBUFFERED='1',
               OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1', MKL_NUM_THREADS='1')
    return command, env


@contextmanager
def _owner(root):
    with (root/'private/owner.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise ValueError('This Oracle execution already has a live owner') from error
        yield


# Darwin answers kill(-pgid, ...) with EPERM, not ESRCH, while every member of
# the group is an exited but unreaped zombie. Such members can no longer write.
_GROUP_GONE = (ProcessLookupError, PermissionError)
# Interpreter helpers (multiprocessing's resource tracker) leave the group a
# few milliseconds after a clean owner exit. They are not leaked writers.
NATURAL_EXIT_DRAIN_S = .5


def _group_alive(pid):
    try:
        os.killpg(pid, 0)
    except _GROUP_GONE:
        return False
    return True


def _close_remaining_group(pid, grace_s):
    """An exited owner must not leave solver/planner writers behind."""
    began = time.monotonic()
    while _group_alive(pid):
        if time.monotonic()-began >= min(grace_s, NATURAL_EXIT_DRAIN_S):
            break
        time.sleep(.01)
    else:
        return False
    try:
        os.killpg(pid, signal.SIGTERM)
    except _GROUP_GONE:
        return True
    began = time.monotonic()
    while time.monotonic()-began < grace_s:
        if not _group_alive(pid):
            return True
        time.sleep(.05)
    try:
        os.killpg(pid, signal.SIGKILL)
    except _GROUP_GONE:
        pass
    return True


def run(execution):
    root, document, config = _load(execution)
    if _versions() != document['versions']:
        raise ValueError('Oracle runtime dependency versions changed since preparation')
    command, env = _command(root, document, config)
    with _owner(root):
        claim = root/'private/claim.json'
        if claim.exists() or (root/'trial').exists() or (root/'STOP').exists():
            raise ValueError('Oracle execution is single-use; inspect its status or prepare a fresh attempt')
        began = time.time()
        began_monotonic = time.monotonic()
        row = {'schema': 'robofrontier.oracle-status.v1', 'phase': 'launching', 'case_id': document['case_id'],
               'model_calls': 0, 'owner_pid': os.getpid(), 'started_unix_s': began,
               'deadline_unix_s': began+config['oracle']['wall_limit_s'],
               'manifest_sha256': _sha(root/'oracle.json')}
        write_json(claim, row)
        interrupted = [False]
        previous = {}
        for number in (signal.SIGTERM, signal.SIGINT):
            previous[number] = signal.signal(number, lambda *_: interrupted.__setitem__(0, True))
        process = None
        try:
            with (root/'oracle.log').open('x') as log:
                process = subprocess.Popen(command, cwd=root/'private/executor', env=env,
                                           stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
                row.update(phase='running', pid=process.pid)
                write_json(root/'oracle-status.json', row)
                stopped_at = None
                while process.poll() is None:
                    now = time.time()
                    reason = ('owner_signal' if interrupted[0] else 'explicit_stop' if (root/'STOP').exists()
                              else 'engineering_deadline' if time.monotonic()-began_monotonic >= config['oracle']['wall_limit_s'] else None)
                    if reason is not None and stopped_at is None:
                        stopped_at = time.monotonic()
                        row.update(phase='stopping', stop_reason=reason, stop_requested_unix_s=now)
                        write_json(root/'oracle-status.json', row)
                        # The native owner drains/reports its own world. Its scratch
                        # planners/solver children get the full cleanup interval.
                        try:
                            process.send_signal(signal.SIGTERM)
                        except ProcessLookupError:
                            pass
                    if stopped_at is not None and time.monotonic()-stopped_at >= config['oracle']['stop_grace_s']:
                        try:
                            os.killpg(process.pid, signal.SIGKILL)
                        except _GROUP_GONE:
                            pass
                        row['forced_kill'] = True
                        break
                    time.sleep(.1)
                process.wait()
                remaining = (max(0., config['oracle']['stop_grace_s']-(time.monotonic()-stopped_at))
                             if stopped_at is not None else config['oracle']['stop_grace_s'])
                if _close_remaining_group(process.pid, remaining):
                    row['descendant_cleanup_required'] = True
            report_path = root/'trial/report.json'
            report = _read(report_path) if report_path.is_file() else {}
            evaluated = report.get('evaluation', {})
            clean = (process.returncode == 0 and not row.get('stop_reason') and
                     not row.get('descendant_cleanup_required') and not report.get('error') and
                     not report.get('unresolved_robot_actions'))
            commissioning = bool(report.get('commissioning_only'))
            passed = bool(clean and not commissioning and report.get('passed') and evaluated.get('task_success'))
            commissioned = bool(clean and commissioning and report.get('commissioning_passed'))
            row.update(phase='interrupted' if row.get('stop_reason') else 'passed' if passed else
                       'commissioning_complete' if commissioned else 'incomplete', passed=passed,
                       commissioning_passed=commissioned, task_completed=bool(evaluated.get('task_success')),
                       returncode=process.returncode, finished_unix_s=time.time(),
                       report='trial/report.json' if report else None,
                       scope='Privileged Oracle engineering; not a policy benchmark result')
            if report.get('report_schema') == 'robofrontier.oracle-report.v2':
                for key in ('report_schema','task_completed','task_goal_met','process_clean',
                            'execution_resolved','physics_valid','strategy_completed'):
                    row[key]=report[key]
            if not report:
                row['error'] = 'Native Oracle produced no report; inspect oracle.log and retained evidence'
        except BaseException as error:
            if process is not None and process.poll() is None:
                # Never return while a known child keeps mutating this world.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except _GROUP_GONE:
                    pass
                process.wait()
            row.update(phase='execution_error', error=type(error).__name__+': '+str(error),
                       finished_unix_s=time.time(), passed=False)
            write_json(root/'oracle-status.json', row)
            raise
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)
        write_json(root/'oracle-status.json', row)
        return row


def status(execution):
    root = Path(execution).resolve()
    document = _read(root/'oracle.json')
    if document.get('schema') != 'robofrontier.oracle-execution.v1':
        raise ValueError('Expected an Oracle execution directory')
    # Atomic JSON only. Never open another owner's SQLite or manipulate its world.
    result = _read(root/'oracle-status.json')
    for name in ('runner-status.json', 'planning-status.json', 'status.json'):
        path = root/'trial'/name
        if path.is_file():
            result.setdefault('native', {})[name] = _read(path)
    with (root/'private/owner.lock').open('a') as stream:
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            result['owner_lock_held'] = True
        else:
            result['owner_lock_held'] = False
            if result['phase'] in ('launching', 'running', 'stopping'):
                result['warning'] = ('Owner lock is no longer held; a native child may still be running. '
                                     'Inspect its recorded PID before collection; this is not a restart checkpoint')
    return result


def execute(args):
    if args.oracle_action in ('run', 'status', 'stop'):
        if args.oracle_action == 'run':
            return run(args.execution)
        result = status(args.execution)
        if args.oracle_action == 'stop':
            (args.execution.resolve()/'STOP').touch()
            return {'stop_requested': True, 'previous_phase': result['phase'],
                    'note': 'Wait for the owner to finish; inspect native cleanup and unresolved actions'}
        return result
    updates = {field: getattr(args, field) for field in ('families', 'cases', 'level', 'min_arms')
               if getattr(args, field, None) is not None}
    options = {field: getattr(args, field) for field in ('wall_limit_s', 'mosaic_max_goals', 'mosaic_planning_workers', 'evaluation_mode')
               if getattr(args, field, None) is not None}
    overrides = {}
    if updates:
        overrides['selection'] = updates
    if options:
        overrides['oracle'] = options
    if getattr(args, 'render', None):
        overrides['render'] = {'device': args.render}
    config = load_configuration(args.config, overrides)
    if args.oracle_action == 'plan':
        return plan(config)
    return prepare(args.output, config, codebook=args.codebook,
                   physics_profile=getattr(args, 'physics_profile', None))
