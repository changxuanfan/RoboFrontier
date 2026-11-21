"""Claude models, case planning, batch preparation and offline readiness checks.

The unified CLI (`roboteam prepare|run|continue|status|stop`) uses these; a batch runs
under roboteam/launch/claude_batch.py."""

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from roboteam.harness.claude.models import BATCH_SCHEMA, CATALOG, LAUNCH_SCHEMA, model_entry  # noqa: F401
from roboteam.io import load_env, write_json
from roboteam.launch.cases import check_case_assets
from roboteam.launch.prepare import select_cases
from roboteam.launch.results.assets import digest
from roboteam.runtime.run import layout as run_layout
from roboteam.tasks.config import DEFAULT_RUN_SETTINGS
from roboteam.tasks.task_types import RELEASE, ROOT, read


def plan(names, task_types=None, cases=None, level=None, min_arms=False, parallel=4, catalog=CATALOG):
    if not names or len(set(names)) != len(names):
        raise ValueError('Choose distinct models')
    if not 1 <= parallel <= 36:
        raise ValueError('Parallel tasks must be 1..36')
    model_entries = {name: model_entry(name, catalog) for name in names}
    rows = select_cases(task_types, cases, level, min_arms)
    jobs = [
        dict(model_entry=name, model=p['model'], provider=p['provider'], **row)
        for name, p in model_entries.items()
        for row in rows
    ]
    return dict(
        schema='roboteam.claude-plan.v1',
        model_calls=0,
        simulator_started=False,
        parallel=parallel,
        task_count=len(jobs),
        jobs=jobs,
        note='Planning only; providers and model capabilities are not verified.',
    )


def exposed_api_keys(model_entries, bash_isolation):
    """Models whose API key a policy shell could read: Claude Code's bubblewrap on Linux leaves
    the CLI's environment readable, and only a subscription token goes on a pipe instead
    (claude.runner.start_cli)."""
    if not (sys.platform.startswith('linux') and bash_isolation == 'claude-sandbox'):
        return []
    return sorted(n for n, p in model_entries.items() if p.get('auth_mode', 'api_key') == 'api_key')


def prepare_batch(
    output,
    names,
    task_types=None,
    cases=None,
    level=None,
    min_arms=False,
    catalog=CATALOG,
    system='adaptive',
    record_video=False,
    *,
    wall_limit_s=86400,
    observation_image_profile=None,
    startup_timeout_s=None,
    render_device=None,
    tools='full',
    observation='images',
):
    """Prepare one run per model and case, frozen for roboteam/launch/claude_batch.py."""
    from roboteam.runtime.run.setup import prepare_case
    from roboteam.tasks.task_types import dial_code, policy_task

    if system not in ('adaptive', 'single-agent', 'hierarchical', 'decentralized'):
        raise ValueError('Unknown Claude system')
    if type(record_video) is not bool:
        raise ValueError('record_video must be a boolean')
    selection = plan(names, task_types, cases, level, min_arms, 1, catalog)
    model_entries = {name: model_entry(name, catalog) for name in names}
    selected = list(dict.fromkeys(job['case_id'] for job in selection['jobs']))
    for p in model_entries.values():
        if (
            p.get('auth_mode') == 'native_login'
            and p.get('native_config_dir')
            and Path(p['native_config_dir']).resolve().is_relative_to(Path(output).resolve())
        ):
            raise ValueError('Keep the native authentication home outside the evidence batch')
    release = read(ROOT / RELEASE)
    released = {
        case['id']: case for task_type in release['task_types'].values() for case in task_type['policy']
    }
    for case in selected:
        report = check_case_assets(released[case], ROOT)
        if report['missing'] or report['changed']:
            raise ValueError('Missing or changed scene assets for ' + case)
    if not (ROOT / 'vendor/panda/SOURCE.json').is_file():
        raise ValueError('Missing Panda source assets; restore the published policy asset bundle')
    # Prepared on the host that runs it: Claude Code's sandbox, or Landlock where it cannot run.
    from roboteam.harness.shared.landlock import choose

    bash_isolation = choose()
    keyed = exposed_api_keys(model_entries, bash_isolation)
    if keyed:
        raise ValueError(
            'API-key Claude models would expose their key to policy shells under bubblewrap '
            'on Linux; use a subscription-token model: ' + ', '.join(keyed)
        )
    # A policy environment admits only the Bash isolation and Claude Code CLI its check ran.
    from roboteam.runtime.sandbox import policy_env

    policy_env.require_combination('claude', bash_isolation)
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    for folder in run_layout.BATCH_FOLDERS:
        (output / folder).mkdir()
    batch = {
        'schema': BATCH_SCHEMA,
        'status': 'preparing',
        'created_at': time.time(),
        'model_calls': 0,
        'jobs': [],
        **run_layout.batch_record(),
    }
    write_json(output / 'batch.json', batch)
    puzzles = {}
    for case in selected:
        task = policy_task(case)
        if task.get('task_type') == 'dial':
            target = output / 'private/dial' / (case + '.json')
            write_json(target, {'code_symbols': dial_code(case)})
            puzzles[case] = target
    for name, p in model_entries.items():
        cfg = read(DEFAULT_RUN_SETTINGS)
        if system in ('hierarchical', 'decentralized'):
            cfg['startup_protocol'] = 'direct_team'
        cfg.update(
            harness='claude',
            system=system,
            model=p['model'],
            effort=p['effort'],
            record_realtime_video=record_video,
        )
        if observation_image_profile is not None:
            cfg['observation_image_profile'] = observation_image_profile
        if startup_timeout_s is not None:
            cfg['startup_timeout_s'] = startup_timeout_s
        if render_device is not None:
            cfg['render_device'] = render_device
        if tools != 'full':
            cfg['tools'] = tools
        if observation != 'images':
            cfg['observation'] = observation
        cfg_path = output / 'models' / name / 'run.json'
        write_json(cfg_path, cfg)
        for case in selected:
            run = output / name / case
            prepare_case(case, run, cfg_path, puzzles.get(case), wall_limit_s=wall_limit_s)
            inputs = run / 'private/inputs'
            launch = inputs / 'claude.json'
            # Both harnesses share one context budget, frozen with the run (models.json).
            from roboteam.configuration import model_catalog

            context = model_catalog('codex')
            write_json(
                launch,
                {
                    'schema': LAUNCH_SCHEMA,
                    'model_entry': p,
                    'context_window': context['context_window'],
                    'auto_compact_token_limit': context['auto_compact_token_limit'],
                    'bash_isolation': bash_isolation,
                },
            )
            manifest_path = inputs / 'manifest.json'
            manifest = read(manifest_path)
            for file in (launch,):
                manifest['input_sha256'][str(file.relative_to(run))] = digest(file)
            for file in (ROOT / 'roboteam/launch/claude_prepare.py', ROOT / 'models.json'):
                relative = file.relative_to(ROOT)
                frozen = inputs / 'frozen-source' / relative
                frozen.parent.mkdir(parents=True, exist_ok=True)
                frozen.write_bytes(file.read_bytes())
                manifest['source_sha256'][str(relative)] = digest(file)
            manifest.update(harness='claude', status='prepared')
            write_json(manifest_path, manifest)
            batch['jobs'].append(
                {'model_entry': name, 'case_id': case, 'run_directory': str(run), 'status': 'prepared'}
            )
            write_json(output / 'batch.json', batch)
    batch['status'] = 'prepared_not_started'
    write_json(output / 'batch.json', batch)
    return output / 'batch.json'


def doctor(names, root=ROOT, catalog=CATALOG):
    load_env(root / '.env')
    binary = shutil.which('claude')
    cli = {'available': False}
    if binary:
        try:
            result = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=15)
            cli = {
                'available': result.returncode == 0,
                'version': (result.stdout or result.stderr).strip().splitlines()[0],
            }
        except (OSError, subprocess.TimeoutExpired, IndexError):
            cli = {'available': False}
    model_entries = {}
    for name in names:
        p = model_entry(name, catalog)
        model_entries[name] = {
            'model': p['model'],
            'provider': p['provider'],
            'credential_env': p['env_key'],
            'credential_set': bool(p.get('native_config_dir'))
            if p.get('auth_mode') == 'native_login'
            else bool(os.environ.get(p['env_key'])),
            'native_login_home': p.get('native_config_dir'),
            'base_url_configured': bool(p['base_url']),
            'live_verified': False,
        }
    assets = [
        check_case_assets(case, root)
        for task_type in read(root / RELEASE)['task_types'].values()
        for case in task_type['policy']
    ]
    return {
        'claude': cli,
        'models': model_entries,
        'release_sha256': digest(root / RELEASE),
        'assets': {
            'missing': sum(len(a['missing']) for a in assets),
            'changed': sum(len(a['changed']) for a in assets),
        },
        'recording_tools': {name: bool(shutil.which(name)) for name in ('ffmpeg', 'ffprobe')},
        'panda_manifest_available': (root / 'vendor/panda/SOURCE.json').is_file(),
        'note': 'Offline checks only; no credential validation, model calls or physics.',
    }
