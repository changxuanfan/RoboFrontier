"""Claude model profiles, case planning, batch preparation and offline readiness checks.

The unified CLI (`robofrontier prepare|run|continue|status|stop`) uses these; a batch runs
under robofrontier/batch/claude_batch.py."""
import argparse
import hashlib
import secrets
import sys
import time
import json
import os
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from robofrontier.runtime import layout as run_layout
from robofrontier.tasks.families import ROOT, RELEASE, read
from robofrontier.batch.prepare import load_env, select_cases
from robofrontier.batch.handoff import digest
from robofrontier.runtime.setup import write_json
from robofrontier.engines.claude.runner import _oauth_endpoint_allowed
from robofrontier.batch.tasks import check_case_assets

CATALOG = ROOT / 'configs/models.json'
BATCH_SCHEMA = 'robofrontier.claude-batch.v2'
LAUNCH_SCHEMA = 'robofrontier.claude-launch.v2'


def profile(name, catalog=CATALOG):
    from ..configuration import model_catalog
    document = model_catalog('claude', catalog)
    if document.get('schema') != 'robofrontier.claude-models.v1':
        raise ValueError('Unsupported Claude model catalog')
    try:
        selected = dict(document['profiles'][name])
    except KeyError as exc:
        raise ValueError('Unknown Claude model profile: ' + name) from exc
    if not all(isinstance(selected.get(k), str) and selected[k] for k in ('provider', 'model', 'effort')):
        raise ValueError('Incomplete model profile')
    if selected['effort'] not in ('low', 'medium', 'high', 'xhigh', 'max'):
        raise ValueError('Unsupported Claude effort')
    auth_mode=selected.get('auth_mode','api_key')
    if auth_mode not in ('api_key','oauth_token','native_login'):
        raise ValueError('Unsupported Claude authentication mode')
    if auth_mode == 'native_login':
        if selected.get('native_config_scope', 'directory') not in ('default', 'directory'):
            raise ValueError('Unknown native configuration scope')
        if selected['provider'] != 'anthropic' or selected.get('env_key'):
            raise ValueError('Native login requires Anthropic and no credential environment variable')
        name = selected.get('native_config_dir_env')
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError('Native login requires an explicit configuration-directory environment variable')
        value = os.environ.get(name)
        selected['native_config_dir'] = str(Path(value).resolve()) if value and Path(value).is_absolute() else value
    elif not isinstance(selected.get('env_key'), str) or not selected['env_key']:
        raise ValueError('Incomplete model profile')
    if auth_mode=='oauth_token' and (selected['provider']!='anthropic' or selected['env_key']!='CLAUDE_CODE_OAUTH_TOKEN'):
        raise ValueError('OAuth token mode is limited to the Anthropic subscription profile')
    base = selected.get('base_url')
    if 'base_url_env' in selected:
        base = os.environ.get(selected['base_url_env'])
    if base:
        url = urlsplit(base)
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Base URL must be HTTPS without credentials, query or fragment')
    if auth_mode in ('oauth_token', 'native_login') and not _oauth_endpoint_allowed(base):
        raise ValueError('OAuth token may only be sent to the Anthropic endpoint')
    selected['base_url'] = base
    return selected


def plan(names, families=None, cases=None, level=None, min_arms=False, parallel=4, catalog=CATALOG):
    if not names or len(set(names)) != len(names):
        raise ValueError('Choose distinct model profiles')
    if not 1 <= parallel <= 36:
        raise ValueError('Parallel tasks must be 1..36')
    profiles = {name: profile(name, catalog) for name in names}
    rows = select_cases(families, cases, level, min_arms)
    jobs = [dict(profile=name, model=p['model'], provider=p['provider'], **row)
            for name, p in profiles.items() for row in rows]
    return dict(schema='robofrontier.claude-plan.v1',
                model_calls=0, simulator_started=False, parallel=parallel, task_count=len(jobs), jobs=jobs,
                note='Planning only; providers and model capabilities are not verified.')



def exposed_api_keys(profiles, bash_isolation):
    """Profiles whose API key a policy shell could read: Claude Code's bubblewrap on Linux leaves
    the CLI's environment readable, and only a subscription token goes on a pipe instead
    (claude.runner.start_cli)."""
    if not (sys.platform.startswith('linux') and bash_isolation == 'claude-sandbox'): return []
    return sorted(n for n, p in profiles.items() if p.get('auth_mode', 'api_key') == 'api_key')


def prepare_batch(output, names, families=None, cases=None, level=None, min_arms=False, catalog=CATALOG, topology='adaptive', record_video=False,
                  *, wall_limit_s=86400, observation_image_profile=None, startup_timeout_s=None, render_device=None,
                  tool_mode='full'):
    """Prepare one run per profile and case, frozen for robofrontier/batch/claude_batch.py."""
    from robofrontier.tasks.families import prepare, policy_task
    from robofrontier.tasks.families import dial_code

    if topology not in ('adaptive', 'centralized', 'hierarchical', 'peer'):
        raise ValueError('Unknown Claude topology')
    if type(record_video) is not bool:
        raise ValueError('record_video must be a boolean')
    selection = plan(names, families, cases, level, min_arms, 1, catalog)
    profiles = {name: profile(name, catalog) for name in names}
    selected = list(dict.fromkeys(job['case_id'] for job in selection['jobs']))
    for p in profiles.values():
        if (p.get('auth_mode') == 'native_login' and p.get('native_config_dir')
                and Path(p['native_config_dir']).resolve().is_relative_to(Path(output).resolve())):
            raise ValueError('Keep the native authentication home outside the evidence batch')
    release = read(ROOT / RELEASE)
    released = {case['id']: case for family in release['families'].values() for case in family['gpt']}
    for case in selected:
        report = check_case_assets(released[case], ROOT)
        if report['missing'] or report['changed']:
            raise ValueError('Missing or changed scene assets for ' + case)
    if not (ROOT / 'vendor/panda/SOURCE.json').is_file():
        raise ValueError('Missing Panda source assets; restore the published policy asset bundle')
    # Prepared on the host that runs it: Claude Code's sandbox, or Landlock where it cannot run.
    from robofrontier.engines.common.landlock import choose
    bash_isolation = choose()
    keyed = exposed_api_keys(profiles, bash_isolation)
    if keyed:
        raise ValueError('API-key Claude profiles would expose their key to policy shells under bubblewrap '
                         'on Linux; use a subscription-token profile: ' + ', '.join(keyed))
    # A policy environment admits only the Bash isolation and Claude Code CLI its check ran.
    from robofrontier.runtime import policy_env
    policy_env.require_combination('claude', bash_isolation)
    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=False)
    for folder in run_layout.BATCH_FOLDERS: (output/folder).mkdir()
    batch = {'schema': BATCH_SCHEMA, 'status': 'preparing',
             'created_at': time.time(), 'model_calls': 0, 'jobs': [],
             **run_layout.batch_record()}
    write_json(output / 'batch.json', batch)
    puzzles = {}
    for case in selected:
        task = policy_task(case)
        if task.get('family') == 'dial':
            target = output / 'private/dial' / (case + '.json')
            write_json(target, {'code_symbols': dial_code(case)})
            puzzles[case] = target
    for name, p in profiles.items():
        cfg = read(ROOT / 'configs/harnesses/policy.json')
        if topology in ('hierarchical', 'peer'): cfg['startup_protocol'] = 'direct_team_v3'
        cfg.update(engine='claude', topology=topology, model=p['model'], effort=p['effort'], record_realtime_video=record_video)
        if observation_image_profile is not None:cfg['observation_image_profile']=observation_image_profile
        if startup_timeout_s is not None:cfg['startup_timeout_s']=startup_timeout_s
        if render_device is not None:cfg['render_device']=render_device
        if tool_mode != 'full':cfg['tool_mode']=tool_mode
        cfg_path = output / 'profiles' / name / 'harness.json'
        write_json(cfg_path, cfg)
        for case in selected:
            run = output / name / case
            prepare(case, run, cfg_path, puzzles.get(case),wall_limit_s=wall_limit_s)
            inputs = run / 'private/inputs'
            launch = inputs / 'claude.json'
            # Both engines share one context budget, frozen with the run (configs/models.json).
            from ..configuration import model_catalog
            context = model_catalog('codex')
            write_json(launch, {'schema': LAUNCH_SCHEMA, 'profile': p,
                                'context_window': context['context_window'],
                                'auto_compact_token_limit': context['auto_compact_token_limit'],
                                'bash_isolation': bash_isolation})
            manifest_path = inputs / 'manifest.json'
            manifest = read(manifest_path)
            for file in (launch,):
                manifest['input_sha256'][str(file.relative_to(run))] = digest(file)
            for file in (ROOT / 'robofrontier/batch/claude_prepare.py', ROOT / 'configs/models.json'):
                relative = file.relative_to(ROOT)
                frozen = inputs / 'frozen-source' / relative
                frozen.parent.mkdir(parents=True, exist_ok=True)
                frozen.write_bytes(file.read_bytes())
                manifest['source_sha256'][str(relative)] = digest(file)
            manifest.update(engine='claude', status='prepared')
            write_json(manifest_path, manifest)
            batch['jobs'].append({'profile': name, 'case_id': case, 'run_directory': str(run), 'status': 'prepared'})
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
            cli = {'available': result.returncode == 0, 'version': (result.stdout or result.stderr).strip().splitlines()[0]}
        except (OSError, subprocess.TimeoutExpired, IndexError):
            cli = {'available': False}
    profiles = {}
    for name in names:
        p = profile(name, catalog)
        profiles[name] = {'model': p['model'], 'provider': p['provider'], 'credential_env': p['env_key'],
                          'credential_set': bool(p.get('native_config_dir')) if p.get('auth_mode') == 'native_login' else bool(os.environ.get(p['env_key'])),
                          'native_login_home': p.get('native_config_dir'),
                          'base_url_configured': bool(p['base_url']), 'live_verified': False}
    assets = [check_case_assets(case, root) for family in read(root / RELEASE)['families'].values() for case in family['gpt']]
    return {'claude': cli, 'profiles': profiles, 'release_sha256': digest(root / RELEASE),
            'assets': {'missing': sum(len(a['missing']) for a in assets), 'changed': sum(len(a['changed']) for a in assets)},
            'recording_tools': {name: bool(shutil.which(name)) for name in ('ffmpeg', 'ffprobe')},
            'panda_manifest_available': (root / 'vendor/panda/SOURCE.json').is_file(),
            'note': 'Offline checks only; no credential validation, model calls or physics.'}
