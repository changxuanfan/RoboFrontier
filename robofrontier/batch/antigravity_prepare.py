"""Prepare Antigravity runs with the released tasks and shared harness contract."""
import json
import os
from pathlib import Path
import time

from robofrontier.configuration import ROOT, model_catalog
from robofrontier.engines.antigravity.profile import profile
from robofrontier.engines.antigravity.auth import home_directory
from robofrontier.engines.antigravity.settings import isolation
from robofrontier.batch.prepare import select_cases
from robofrontier.batch.handoff import digest
from robofrontier.runtime import layout, policy_env
from robofrontier.runtime.setup import write_json

BATCH_SCHEMA = 'robofrontier.antigravity-batch.v1'
LAUNCH_SCHEMA = 'robofrontier.antigravity-launch.v1'


def prepare_batch(output, names, families=None, cases=None, level=None, min_arms=False, catalog=None,
                  topology='adaptive', record_video=False, *, wall_limit_s=86400,
                  observation_image_profile=None, startup_timeout_s=None, render_device=None):
    from robofrontier.tasks.families import prepare, policy_task, dial_code
    from robofrontier.batch.tasks import check_case_assets
    from robofrontier.tasks.families import RELEASE, read
    if topology not in ('centralized', 'hierarchical', 'peer', 'adaptive'):
        raise ValueError('Unknown Antigravity topology')
    profiles = {name: profile(name, catalog) for name in names}
    selected = select_cases(families, cases, level, min_arms)
    released = {case['id']: case for family in read(ROOT/RELEASE)['families'].values() for case in family['gpt']}
    for item in selected:
        report = check_case_assets(released[item['case_id']], ROOT)
        if report['missing'] or report['changed']:
            raise ValueError('Missing or changed scene assets: ' + item['case_id'])
    backend = isolation()
    policy_env.require_combination('antigravity', backend)
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    for folder in layout.BATCH_FOLDERS:
        (output/folder).mkdir()
    batch = {'schema': BATCH_SCHEMA, 'engine': 'antigravity', 'status': 'preparing', 'model_calls': 0,
             'created_at': time.time(), 'jobs': [], **layout.batch_record()}
    write_json(output/'batch.json', batch)
    for name, selected_profile in profiles.items():
        cfg = json.loads((ROOT/'configs/harnesses/policy.json').read_text())
        cfg.update(engine='antigravity', topology=topology, model=selected_profile['model'], effort=selected_profile['effort'],
                   record_realtime_video=record_video)
        if topology in ('hierarchical', 'peer'):
            cfg['startup_protocol'] = 'direct_team_v3'
        for key, value in (('observation_image_profile', observation_image_profile),
                           ('startup_timeout_s', startup_timeout_s), ('render_device', render_device)):
            if value is not None:
                cfg[key] = value
        cfg_path = output/'profiles'/name/'harness.json'
        write_json(cfg_path, cfg)
        for item in selected:
            case = item['case_id']
            run = output/name/case
            puzzle = None
            if policy_task(case).get('family') == 'dial':
                puzzle = output/'private/dial'/(case+'.json')
                write_json(puzzle, {'code_symbols': dial_code(case)})
            prepare(case, run, cfg_path, puzzle, wall_limit_s=wall_limit_s)
            home = home_directory(run, selected_profile)
            launch = run/'private/inputs/antigravity.json'
            write_json(launch, {'schema': LAUNCH_SCHEMA, 'profile': selected_profile,
                'native_home': str(home/'.gemini/antigravity-cli'), 'terminal_isolation': backend,
                'context_window': model_catalog('codex')['context_window'],
                'requested_auto_compact_token_limit': model_catalog('codex')['auto_compact_token_limit'],
                'effective_auto_compact_token_limit': None,
                'compaction_configuration': 'native_static_config',
                'differences': ['user_wrappers', 'native_tools', 'fork_resume_notices',
                                'provider_context_capacity_unverified']})
            manifest_file = run/'private/inputs/manifest.json'
            manifest = json.loads(manifest_file.read_text())
            manifest['input_sha256'][str(launch.relative_to(run))] = digest(launch)
            manifest.update(status='prepared', engine='antigravity')
            write_json(manifest_file, manifest)
            batch['jobs'].append({'profile': name, 'case_id': case, 'run_directory': str(run), 'status': 'prepared'})
    batch['status'] = 'prepared_not_started'
    write_json(output/'batch.json', batch)
    return output/'batch.json'
