"""Command-line entry point shared by native policy engines and evidence tools."""
import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile

from .configuration import ROOT, TOPOLOGIES, load_configuration, rendering_environment, runs_root
from .runtime import policy_env, layout as run_layout


def _print(value):
    print(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False))


def _catalog(config):
    policy = config['policy']
    from .configuration import model_catalog
    catalog = model_catalog(policy['engine'])
    if policy['profile'] not in catalog['profiles']:
        raise ValueError('Unknown ' + policy['engine'] + ' profile: ' + policy['profile'])
    catalog['profiles'][policy['profile']]['effort'] = policy['effort']
    if policy['engine'] == 'codex':
        # New portable batches and their preflight use the same checked-in
        # template, independent of another Desktop session's mutable cache.
        catalog['profiles'][policy['profile']]['use_cached_model_metadata'] = False
        catalog['profiles'][policy['profile']]['tool_backend'] = config['runtime'].get('codex_tool_backend', 'native')
        if config['runtime']['codex_home_scope'] == 'job':
            catalog['profiles'][policy['profile']]['runner_backend'] = 'slurm-managed-v1'
    return catalog


@contextmanager
def _catalog_file(config):
    with tempfile.TemporaryDirectory(prefix='robofrontier-catalog-') as temporary:
        path = Path(temporary)/'models.json'
        path.write_text(json.dumps(_catalog(config)))
        yield path


def _policy_environment():
    """What `prepare` would freeze for policy scripts, without changing anything."""
    from .runtime.policy_env import ENV_VAR, default_root, selected
    try:
        root = selected() if os.environ.get(ENV_VAR) else default_root()
    except ValueError as error:
        return {'status': 'unavailable', 'error': str(error)}
    return {'status': 'host_python', 'root': None} if root is None else {'status': 'frozen', 'root': str(root)}


def plan(config):
    from robofrontier.batch.prepare import select_cases
    selection = config['selection']
    selected = select_cases(selection['families'] or None, selection['cases'] or None,
                            selection['level'] or None, selection['min_arms'])
    policy = config['policy']
    model = _catalog(config)['profiles'][policy['profile']]['model']
    return {'schema': 'robofrontier.plan.v1', 'model_calls': 0, 'simulator_started': False,
            'engine': policy['engine'], 'model': model, 'effort': policy['effort'],
            'topology': policy['topology'], 'parallel': config['batch']['parallel'],
            'startup_interval_s': config['batch']['startup_interval_s'],
            'task_wall_limit_s': config['batch']['task_wall_limit_s'],
            'task_count': len(selected), 'jobs': selected, 'policy_environment': _policy_environment(),
            'qualification': 'Requires matching live provider compatibility receipts (robofrontier preflight)'}


def prepare(output, config):
    from robofrontier.batch.handoff import setup_assets
    from robofrontier.batch.prepare import load_env
    from .runtime.setup import write_json
    policy, selection = config['policy'], config['selection']
    load_env(ROOT/'.env')
    plan(config)  # Reject invalid model and selection before any installation.
    from .runtime import versions
    pinned = versions.require(policy['engine'])
    policy_env.require_private_route(config)
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new output directory; prepared runs are never overwritten')
    setup_assets()
    topology = TOPOLOGIES[policy['topology']]
    harness = {'topology': topology,
               'startup_protocol': 'direct_controller_v2' if topology in ('centralized', 'adaptive') else 'direct_team_v3',
               'observation_image_profile': config['render']['observation_profile'],
               'startup_timeout_s': config['batch']['startup_timeout_s'],
               'render_device': config['render']['device'],
               'record_realtime_video': config['render']['record_realtime_video']}
    with _catalog_file(config) as catalog:
        if policy['engine'] == 'claude':
            from robofrontier.batch.claude_prepare import prepare_batch as prepare_claude
            result = prepare_claude(output, [policy['profile']], families=selection['families'] or None,
                                   cases=selection['cases'] or None, catalog=catalog,
                                   level=selection['level'] or None, min_arms=selection['min_arms'],
                                   topology=topology, record_video=config['render']['record_realtime_video'],
                                   wall_limit_s=config['batch']['task_wall_limit_s'],
                                   observation_image_profile=config['render']['observation_profile'],
                                   startup_timeout_s=config['batch']['startup_timeout_s'],
                                   render_device=config['render']['device'])
        else:
            from robofrontier.batch.codex_batch import prepare_batch as prepare_codex
            result = prepare_codex(output, [policy['profile']], families=selection['families'] or None,
                                   cases=selection['cases'] or None, config=catalog,
                                   level=selection['level'] or None, min_arms=selection['min_arms'],
                                   wall_limit_s=config['batch']['task_wall_limit_s'], harness_overrides=harness)
    batch = json.loads(result.read_text())
    batch['execution'] = {**config['runtime'], 'startup_interval_s': config['batch']['startup_interval_s']}
    batch['versions'] = pinned
    batch['effective_configuration_sha256'] = hashlib.sha256(
        json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()
    write_json(output/'effective-config.json', config)
    # Include the effective settings in each run's immutable input inventory.
    for job in batch['jobs']:
        run = Path(job['run_directory'])
        frozen = run/'private/inputs/effective-config.json'
        write_json(frozen, config)
        manifest_path = run/'private/inputs/manifest.json'
        manifest = json.loads(manifest_path.read_text())
        manifest['input_sha256'][str(frozen.relative_to(run))] = hashlib.sha256(frozen.read_bytes()).hexdigest()
        write_json(manifest_path, manifest)
    write_json(result, batch)
    return result


def preflight(config, *, confirm_spend=False, smoke_only=False, max_budget_usd=None):
    """Explicit paid connectivity check; preparation and planning never call it."""
    from robofrontier.batch.prepare import load_env
    load_env(ROOT/'.env')
    policy = config['policy']
    if not confirm_spend:
        return {'status': 'not_run', 'model_calls': 0,
                'reason': 'Add --confirm-spend to authorize real provider calls',
                'engine': policy['engine'], 'profile': policy['profile']}
    from .runtime.diagnostics import require_runtime
    require_runtime(config, render=False)
    with _catalog_file(config) as catalog:
        if policy['engine'] == 'claude':
            if max_budget_usd is None:
                raise ValueError('Claude preflight requires an explicit --max-budget-usd estimate')
            from robofrontier.engines.claude.preflight import run_precheck
            import uuid
            output = runs_root()/'engineering/claude-precheck'/uuid.uuid4().hex
            return run_precheck(policy['profile'], output, max_budget_usd, dict(os.environ),
                                check_fork=not smoke_only, catalog=catalog)
        from robofrontier.engines.codex.launch import profile, launch_config, initialize_codex_home
        selected = profile(policy['profile'], catalog)
        if config['runtime']['codex_home_scope'] == 'job':
            from .batch.slurm_job import subscription_environment, _local_storage
            # Explicitly authorized live preflight, inside an allocation, with
            # its own local credential owner and no physical task START.
            scratch = config['slurm']['scratch_root'] or os.environ.get('SLURM_TMPDIR')
            if not scratch:
                raise ValueError('Job preflight requires node-local Slurm scratch')
            _local_storage(scratch)
            with tempfile.TemporaryDirectory(prefix='rf-pf-', dir=scratch) as temporary:
                with subscription_environment(config, temporary, on_failure=lambda: None):
                    command = [sys.executable, '-m', 'robofrontier.batch.codex_batch', 'preflight', '--models', policy['profile'],
                               '--model-config', str(catalog)]
                    if smoke_only:
                        command.append('--smoke-only')
                    subprocess.run(command, cwd=ROOT, check=True)
            folder = runs_root(config)/'engineering'/('model-smoke' if smoke_only else 'model-compatibility')/policy['profile']
            return json.loads((folder/'report.json').read_text())
        key = selected.get('env_key')
        if key and not os.environ.get(key):
            raise ValueError('Missing credential environment variable: ' + key)
        env = dict(os.environ)
        if config['runtime']['codex_home_scope'] == 'task':
            if selected['provider'] == 'openai':
                raise ValueError('Native subscription preflight requires explicit shared authentication configuration')
            fingerprint = hashlib.sha256(json.dumps(selected, sort_keys=True).encode()).hexdigest()[:20]
            home = ROOT/'.robofrontier/preflight'/fingerprint
        else:
            from robofrontier.engines.codex.launch import codex_home
            home = Path(config['runtime']['codex_home']).expanduser().resolve() if config['runtime']['codex_home'] else codex_home(env)
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        env['CODEX_HOME'] = str(home)
        folder = runs_root(config)/'engineering'/('model-smoke' if smoke_only else 'model-compatibility')/policy['profile']
        folder.mkdir(parents=True, exist_ok=True)
        initialize_codex_home(launch_config(selected, folder), folder, env=env)
        command = [sys.executable, '-m', 'robofrontier.batch.codex_batch', 'preflight', '--models', policy['profile'],
                   '--model-config', str(catalog)]
        if smoke_only:
            command.append('--smoke-only')
        subprocess.run(command, cwd=ROOT, env=env, check=True)
        return json.loads((folder/'report.json').read_text())


def _frozen_configuration(batch):
    # New CLI runs never reinterpret a prepared batch using a changed local TOML.
    path = Path(batch)/'effective-config.json'
    config = json.loads(path.read_text())
    from .configuration import validate_configuration
    validate_configuration(config)
    document = json.loads((Path(batch)/'batch.json').read_text())
    expected = hashlib.sha256(json.dumps(config, sort_keys=True, allow_nan=False).encode()).hexdigest()
    if document.get('effective_configuration_sha256') != expected:
        raise ValueError('Effective batch configuration changed; prepare a new batch')
    execution = {**config['runtime'], 'startup_interval_s': config['batch']['startup_interval_s']}
    if document.get('execution') != execution:
        raise ValueError('Batch launch settings differ from its frozen configuration')
    return config


def run(batch, *, continuing=False):
    """Run a prepared batch. `continuing` picks up a batch whose supervisor died: a run that
    had started continues in its next segment when its stop allows it, and unstarted runs start
    (docs/running/run-segments.md)."""
    config = _frozen_configuration(batch)
    if config['policy']['engine'] == 'claude':
        # Both engines need passed compatibility receipts; Codex checks its own per run.
        from .engines.claude.claude_readiness import require_ready
        require_ready(config['policy']['profile'])
    from .runtime.diagnostics import require_runtime
    from .runtime import versions
    require_runtime(config)
    document = json.loads((Path(batch)/'batch.json').read_text())
    # Every run uses a policy environment and the closed access table (E12).
    for job in document.get('jobs', []):
        access = json.loads((Path(job['run_directory'])/'private/inputs/policy-access.json').read_text())
        if access.get('schema') != 'robofrontier.policy-access.v2':
            raise ValueError('Run prepared without a policy environment: '+job['run_directory'])
    pinned = document.get('versions')
    if pinned != versions.require(config['policy']['engine']):
        raise ValueError('This batch was prepared with other program versions: '+json.dumps(pinned))
    environment = {**rendering_environment(config['render']['device'], platform.system(), os.environ),
                   **versions.ENGINE_ENVIRONMENT[config['policy']['engine']]}
    os.environ.clear()
    os.environ.update(environment)
    if config['policy']['engine'] == 'claude':
        from .batch.claude_batch import run_until_signal
        state = run_until_signal(batch, dict(os.environ), parallel=config['batch']['parallel'],
                          startup_interval_s=config['batch']['startup_interval_s'],
                          startup_timeout_s=config['batch']['startup_timeout_s'],
                          wall_limit_s=config['batch']['task_wall_limit_s'], continuing=continuing)
    else:
        from robofrontier.batch.codex_batch import run_batch
        run_batch(batch, config['batch']['parallel'], continuing=continuing)
        state = json.loads((Path(batch)/'batch.json').read_text())
    result = {'batch': str(Path(batch).resolve()), 'status': state['status']}
    if config['evidence']['auto_collect']:
        output = runs_root(config)/'exports'/(Path(batch).name+'-'+hashlib.sha256(str(Path(batch).resolve()).encode()).hexdigest()[:8])
        result['collection'] = str(collect(batch, output))
        result['collection_complete'] = json.loads((output/'collection.json').read_text())['complete']
        if config['evidence']['auto_archive']:
            result['archive'] = str(archive_collection(output, output.with_suffix('.zip')))
            with Path(result['archive']).open('rb') as stream:
                result['archive_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    return result


def _lock_held(path):
    import fcntl
    if not path.exists(): return False
    with path.open('a+') as lock:
        try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError: return True
        fcntl.flock(lock, fcntl.LOCK_UN)
    return False


def continue_runs(batch, cases=None):
    """Continue stopped runs of a batch by hand, as the same trials (docs/running/run-segments.md).

    Any stop but an integrity abort may be continued, as often as needed: after an
    unexpected stop, an operator's STOP, the finish, the cutoff or the wall backstop. A
    continuation after the finish or the cutoff keeps the score recorded then. Each named
    run (default: every run that may continue) gets its next segment; the batch then runs
    them like `run --continue`. Returns what was prepared and what was not, with why."""
    from .runtime import segments
    from .runtime.setup import write_json
    batch = Path(batch).resolve()
    config = _frozen_configuration(batch)
    engine = config['policy']['engine']
    lock = run_layout.batch_path(batch, 'engineering_lock' if engine == 'claude' else 'supervisor_lock')
    if _lock_held(lock): raise ValueError('The batch is still running; stop it or wait before continuing runs')
    document = json.loads((batch/'batch.json').read_text())
    jobs = document['jobs']
    if cases:
        unknown = set(cases) - {job['case_id'] for job in jobs}
        if unknown: raise ValueError('Not in this batch: '+', '.join(sorted(unknown)))
        jobs = [job for job in jobs if job['case_id'] in cases]
    prepared, refused = [], {}
    for job in jobs:
        run = Path(job['run_directory'])
        from .runtime.store import RuntimeStore
        store = RuntimeStore(run/'private/state/runtime.sqlite')
        try:
            ok, why = segments.retry_eligibility(run, store, manual=True)
            if ok: segments.prepare_retry(run, store, 'manual continue', manual=True)
        finally: store.close()
        if ok: prepared.append(job['case_id'])
        else: refused[job['case_id']] = why
    if cases and refused:
        raise ValueError('Cannot continue: '+'; '.join(f'{k}: {v}' for k, v in refused.items()))
    if not prepared: return {'batch': str(batch), 'prepared': [], 'refused': refused}
    # Reopen the batch for exactly these runs; the others keep their final status.
    if engine == 'claude':
        path = run_layout.batch_path(batch, 'engineering_status')
        state = json.loads(path.read_text())
        for job, entry in zip(document['jobs'], state['jobs']):
            if job['case_id'] in prepared: entry['status'] = 'queued'
        state['status'] = 'running'; write_json(path, state)
    else:
        for job in document['jobs']:
            if job['case_id'] in prepared: job['status'] = 'prepared'
        document['status'] = 'running'; write_json(batch/'batch.json', document)
    run_layout.batch_path(batch, 'stop').unlink(missing_ok=True)
    return {'batch': str(batch), 'prepared': prepared, 'refused': refused}


def collect(batch, output):
    from robofrontier.batch.collect import collect_batch
    collect_batch(Path(batch), Path(output))
    return Path(output).resolve()


def archive_collection(collection, output):
    from robofrontier.batch.archive_policy_batch import create
    from .batch.archive import pack
    output = Path(output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.rf-archive-', dir=output.parent) as temporary:
        directory = Path(temporary)/'archive'
        # Preserve reviewed/incomplete evidence too; its manifest keeps every
        # issue and does not certify physical actions, task success or scores.
        create(Path(collection), directory, allow_incomplete=True)
        return pack(directory, output)


def argument_parser(*, prog=None):
    parser = argparse.ArgumentParser(prog=prog, description=__doc__)
    parser.add_argument('--config', type=Path, help='Partial TOML overriding repository defaults')
    parser.add_argument('--result-file', type=Path, help='Write the terminal command result as atomic JSON')
    sub = parser.add_subparsers(dest='command', required=True)
    for name in ('config', 'plan', 'prepare', 'doctor', 'preflight', 'slurm-submit'):
        p = sub.add_parser(name)
        p.add_argument('--engine', choices=('codex', 'claude'))
        p.add_argument('--profile')
        p.add_argument('--effort', choices=('minimal', 'low', 'medium', 'high', 'xhigh', 'max'))
        p.add_argument('--topology', choices=TOPOLOGIES)
        p.add_argument('--parallel', type=int)
        p.add_argument('--render', choices=('nvidia', 'cpu', 'native'))
        p.add_argument('--level', type=int, choices=(1, 2, 3))
        p.add_argument('--min-arms', action='store_true', default=None)
        p.add_argument('--cases', nargs='+')
        p.add_argument('--families', nargs='+', choices=('transport', 'mosaic', 'relay', 'dial'))
        if name == 'prepare':
            p.add_argument('--output', type=Path, required=True)
        elif name == 'slurm-submit':
            p.add_argument('--output', type=Path, required=True)
            p.add_argument('--queue', action='store_true', help='Submit to sbatch; otherwise only freeze a submission')
        elif name == 'preflight':
            p.add_argument('--confirm-spend', action='store_true')
            p.add_argument('--smoke-only', action='store_true')
            p.add_argument('--max-budget-usd', type=float)
    sub.add_parser('bootstrap', help='Restore and verify pinned policy assets; never calls a model')
    for name in ('run', 'continue', 'status', 'stop'):
        p = sub.add_parser(name, help='Continue stopped runs by hand, as the same trials (docs/running/run-segments.md)'
                           if name == 'continue' else None)
        p.add_argument('batch', type=Path)
        if name == 'continue':
            p.add_argument('--cases', nargs='+', help='The runs to continue (default: every run that may continue)')
        if name in ('run', 'continue'):
            p.add_argument('--durable', action='store_true',
                           help='Run as a background service that outlives this terminal: launchd with Interactive '
                                'priority on macOS (the default there, a continuation included), a systemd user service '
                                'or setsid daemon on Linux')
            p.add_argument('--foreground', action='store_true',
                           help='On macOS, run in this process at its own priority instead of the launchd service')
        if name == 'run':
            p.add_argument('--continue', dest='continuing', action='store_true',
                           help='Continue a batch whose supervisor died; a started run continues by itself once '
                                '(docs/running/run-segments.md)')
    p = sub.add_parser('collect', help='Collect stopped native sessions, motion and evidence')
    p.add_argument('batch', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('archive', help='Package a stopped collection as a verified ZIP')
    p.add_argument('collection', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('extract', help='Verify and extract an evidence ZIP archive')
    p.add_argument('archive', type=Path)
    p.add_argument('--output', type=Path, required=True)
    p = sub.add_parser('container', help='Run the native CLI in persistent local Docker volumes')
    p.add_argument('arguments', nargs=argparse.REMAINDER)
    from .factory.workflow import add_arguments
    add_arguments(sub)
    from .oracle.workflow import add_arguments as oracle_arguments
    oracle_arguments(sub)
    return parser


def main(argv=None):
    parser = argument_parser()
    args = parser.parse_args(argv)
    def emit(value):
        if args.result_file:
            from .runtime.setup import write_json
            write_json(args.result_file, value)
        _print(value)
    try:
        if args.command == 'oracle':
            from .oracle.workflow import execute
            report = execute(args)
            emit(report)
            if args.oracle_action == 'run':
                return 0 if report.get('passed') or report.get('commissioning_passed') else 1
            return 0
        if args.command == 'factory':
            from contextlib import redirect_stdout
            from .factory.workflow import execute
            # Native exporters can print progress. Keep the unified command's
            # stdout as one machine-readable result; diagnostics use stderr.
            with redirect_stdout(sys.stderr):
                report = execute(args)
            emit(report)
            return 0
        if args.command == 'container':
            from .batch.container import execute, validate_arguments
            # Resolve help and invalid syntax before configuration, Docker or auth.
            arguments = validate_arguments(args.arguments)
            report = execute(arguments, load_configuration(args.config))
            emit(report)
            return report['exit_code']
        if args.command == 'bootstrap':
            from robofrontier.batch.handoff import setup_assets
            emit(setup_assets())
            return 0
        if args.command in ('config', 'plan', 'prepare', 'doctor', 'preflight', 'slurm-submit'):
            overrides = {}
            for section, fields in (('policy', ('engine', 'profile', 'effort', 'topology')),
                                    ('batch', ('parallel',)),
                                    ('selection', ('level', 'min_arms', 'cases', 'families'))):
                updates = {field: getattr(args, field) for field in fields if getattr(args, field) is not None}
                if updates:
                    overrides[section] = updates
            if args.render:
                overrides['render'] = {'device': args.render}
            config = load_configuration(args.config, overrides)
            if args.command == 'config':
                emit(config)
            elif args.command == 'plan':
                emit(plan(config))
            elif args.command == 'doctor':
                from .runtime.diagnostics import inspect_runtime
                report = inspect_runtime(config)
                emit(report)
                return 0 if report['passed'] else 2
            elif args.command == 'preflight':
                report = preflight(config, confirm_spend=args.confirm_spend,
                                   smoke_only=args.smoke_only, max_budget_usd=args.max_budget_usd)
                emit(report)
                return 0 if report.get('passed') else 2
            elif args.command == 'slurm-submit':
                from robofrontier.batch.prepare import load_env
                from .batch.slurm_job import submit
                load_env(ROOT/'.env')
                emit(submit(config, args.output, queue=args.queue))
            else:
                # New runs use the frozen policy Python environment by default (policy_env.default_root).
                from .runtime.policy_env import apply_default
                apply_default()
                emit({'batch': str(prepare(args.output, config)), 'model_calls': 0})
        elif args.command == 'continue':
            report = continue_runs(args.batch, args.cases)
            if report['prepared']:
                if args.durable or (sys.platform == 'darwin' and not args.foreground):
                    if args.foreground: raise ValueError('--durable and --foreground are exclusive')
                    if sys.platform == 'darwin': from .batch.mac import submit as submit_durable
                    else: from .batch.linux import submit as submit_durable
                    report['service'] = submit_durable(args.batch, continuing=True)
                else:
                    from robofrontier.batch.prepare import load_env
                    load_env(ROOT/'.env')
                    report['result'] = run(args.batch, continuing=True)
            emit(report)
        elif args.command == 'run' and (args.durable or (sys.platform == 'darwin' and not args.foreground)):
            # On macOS a batch, a continuation included, runs under launchd with ProcessType=Interactive
            # by default, so it outlives the terminal or agent session that started it.
            if args.foreground: raise ValueError('--durable and --foreground are exclusive')
            # On Linux (a RunPod pod) --durable starts a background service (batch/linux.py).
            if sys.platform == 'darwin': from .batch.mac import submit as submit_durable
            else: from .batch.linux import submit as submit_durable
            emit(submit_durable(args.batch, continuing=args.continuing))
        elif args.command == 'run':
            from robofrontier.batch.prepare import load_env
            load_env(ROOT/'.env')
            emit(run(args.batch, continuing=args.continuing))
        elif args.command == 'status':
            # Read the supervisor's atomic snapshot, never open a writer's SQLite.
            snapshot = run_layout.batch_path(args.batch, 'engineering_status')
            state = json.loads((snapshot if snapshot.is_file() else args.batch/'batch.json').read_text())
            if sys.platform == 'darwin': from .batch.mac import service_state
            else: from .batch.linux import service_state
            durable = service_state(args.batch)
            emit({**state, 'durable': durable} if durable else state)
        elif args.command == 'stop':
            batch = json.loads((args.batch/'batch.json').read_text())
            folder = args.batch.resolve()
            paths = [Path(job['run_directory']).resolve() for job in batch['jobs']]
            if any(not path.is_relative_to(folder) or path == folder for path in paths):
                raise ValueError('Invalid run directory in batch')
            for stop in [run_layout.batch_path(folder, 'stop'), *(run_layout.path(path, 'stop') for path in paths)]:
                stop.parent.mkdir(parents=True, exist_ok=True)
                stop.touch()
            emit({'stop_requested': True, 'note': 'Inspect status and final sealing outcome'})
        elif args.command == 'collect':
            emit({'collection': str(collect(args.batch, args.output))})
        elif args.command == 'archive':
            archive = archive_collection(args.collection, args.output)
            with archive.open('rb') as stream:
                checksum = hashlib.file_digest(stream, 'sha256').hexdigest()
            emit({'archive': str(archive), 'archive_sha256': checksum})
        elif args.command == 'extract':
            from .batch.archive import unpack
            emit(unpack(args.archive, args.output))
        return 0
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, 'robofrontier: ' + str(error) + '\n')


if __name__ == '__main__':
    raise SystemExit(main())
