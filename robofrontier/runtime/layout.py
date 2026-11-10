"""Where a run and a batch keep their host files.

A newly prepared run records its layout name and resolved paths in
private/inputs/manifest.json, so every host (including the Node Codex host,
through `python -m robofrontier.runtime.layout RUN`) resolves the same files. A run
prepared before that record existed uses run-v3, the legacy locations. Paths are
relative to the run or batch directory.

run-v6 keeps the run root to public/ (host-written policy inputs and results),
workspace/ (the policy's only writable folder and working directory, with one
shared lessons file, skills.md) and private/. private/ is split by lifecycle:
inputs (frozen), state (live; control files in state/control), outputs
(results), logs and engine (CLI configuration, MCP configuration, per-turn
evidence and transcripts). A stopped run continues in the
same directory; segment k >= 1 keeps its restore pose in
private/inputs/segments/<k>/ and its process outputs in
private/outputs/segments/<k>/ (docs/running/run-segments.md).
"""
import argparse
import json
from pathlib import Path, PurePosixPath

CURRENT = 'run-v6'

LAYOUTS = {
    'run-v3': {
        'stop': 'STOP',
        'owner_log': 'private/outputs/owner.log',
        'host_log': {'claude': 'private/outputs/claude-host.jsonl', 'codex': 'private/outputs/codex-host.jsonl'},
        'server_log': 'private/outputs/codex-server.log',
        'supervisor_log': 'private/outputs/supervisor.log',
        'admin_log': 'private/state/admin-client.log',
        'engineering_status': 'private/outputs/claude-engineering-status.json',
        'engineering_claim': 'private/state/claude-engineering-claim.json',
        'engineering_lock': 'private/state/claude-engineering.lock',
        'host_process': 'private/state/host-process.json',
        'world_lock': 'private/state/world.lock',
        'engine_config': 'private/claude-config',
        'engine_mcp': 'private/claude-mcp',
        'engine_turns': 'private/evidence',
        'collected_sessions': 'private/state/claude-collected-sessions.json',
        'codex_home_marker': 'codex-home.json',
        'budget_ledger': 'private/state/claude-budget.sqlite',
        'policy_cwd': '.',
    },
    'run-v6': {
        'stop': 'private/state/control/STOP',
        'owner_log': 'private/logs/owner.log',
        'host_log': 'private/logs/host.jsonl',
        'server_log': 'private/logs/server.log',
        'supervisor_log': 'private/logs/supervisor.log',
        'admin_log': 'private/logs/admin-client.log',
        'engineering_status': 'private/state/control/engineering-status.json',
        'engineering_claim': 'private/state/control/engineering-claim.json',
        'engineering_lock': 'private/state/control/engineering.lock',
        'host_process': 'private/state/control/host-process.json',
        'world_lock': 'private/state/control/world.lock',
        'engine_config': 'private/engine/config',
        'engine_mcp': 'private/engine/mcp',
        'engine_turns': 'private/engine/turns',
        'engine_transcripts': 'private/engine/transcripts',
        'collected_sessions': 'private/engine/collected-sessions.json',
        'codex_home_marker': 'private/engine/codex-home.json',
        # The run's cost ledger, shared by every role, model restart and segment.
        'budget_ledger': 'private/state/budget.sqlite',
        # The policy's only writable folder and its working directory. Claude's sandbox
        # always lets a session write its working directory, so it is not the run root.
        'policy_cwd': 'workspace',
        # One lessons file shared by every role of the run.
        'skills_file': 'workspace/skills.md',
        'segment_inputs': 'private/inputs/segments',
        'segment_outputs': 'private/outputs/segments',
    },
}
# Folders a run-v6 run creates at preparation.
FOLDERS = ('workspace', 'private/logs', 'private/state/control', 'private/engine')


class LayoutError(ValueError):
    pass


def _relative(value, what):
    """A recorded path must be a plain relative path that stays inside its folder."""
    if not isinstance(value, str) or not value:
        raise LayoutError(what+' must be a non-empty string')
    parts = PurePosixPath(value).parts
    if value.startswith('/') or '\\' in value or '..' in parts or parts[0] in ('~',) or ':' in parts[0]:
        raise LayoutError(what+' must stay inside its folder: '+value)
    return value


def _inside(root, relative):
    target = root/relative
    resolved, base = target.resolve(), root.resolve()
    if resolved != base and base not in resolved.parents:
        raise LayoutError('Layout path escapes its folder: '+relative)
    return target


def manifest_record(engine):
    """What a newly prepared run stores in its manifest: the layout and its resolved paths."""
    paths = {key: value[engine] if isinstance(value, dict) else value for key, value in LAYOUTS[CURRENT].items()}
    return {'layout': CURRENT, 'layout_paths': paths}


def _manifest(run):
    """The run's manifest. A missing one means a legacy run; an unreadable one is an error."""
    path = Path(run)/'private/inputs/manifest.json'
    if not path.exists():
        return {}
    try:
        manifest = json.loads(path.read_text())
    except (OSError, ValueError) as error:
        raise LayoutError('Run manifest cannot be read: '+str(error)) from error
    if not isinstance(manifest, dict):
        raise LayoutError('Run manifest must be a JSON object')
    return manifest


def _recorded(record, known, what):
    layout, paths = record.get('layout'), record.get('layout_paths')
    if layout is None and paths is None:
        return None
    if layout not in known or not isinstance(paths, dict):
        raise LayoutError(what+' records an unknown layout: '+str(layout))
    for key, value in paths.items():
        _relative(value, what+' path '+str(key))
    return paths


def layout(run):
    """The layout name a run was prepared with."""
    manifest = _manifest(run)
    return manifest.get('layout', 'run-v3') if _recorded(manifest, LAYOUTS, 'Run manifest') else 'run-v3'


def path(run, key, engine=None):
    """Absolute path of `key` in this run, honoring the layout the run was prepared with."""
    run = Path(run)
    manifest = _manifest(run)
    recorded = _recorded(manifest, LAYOUTS, 'Run manifest')
    if recorded is not None:
        if key not in recorded:
            raise KeyError(key+' is not part of layout '+manifest['layout'])
        return _inside(run, recorded[key])
    value = LAYOUTS['run-v3'].get(key)
    if value is None:
        raise KeyError(key+' is not part of layout run-v3')
    if isinstance(value, dict):
        value = value[engine or manifest.get('engine', 'codex')]
    return run/value


def paths(run, engine=None):
    """Every key of this run's layout, resolved relative to the run directory."""
    run = Path(run)
    manifest = _manifest(run)
    recorded = _recorded(manifest, LAYOUTS, 'Run manifest')
    keys = recorded if recorded is not None else LAYOUTS['run-v3']
    return {key: str(path(run, key, engine).relative_to(run)) for key in keys}


def for_store(store_path, key):
    """A host path found from the runtime database, for code that has only the database."""
    store = Path(store_path)
    if store.name == 'runtime.sqlite' and store.parent.name == 'state' and store.parent.parent.name == 'private':
        return path(store.parents[2], key)
    legacy = {'admin_log': store.parent/'admin-client.log'}
    if key not in legacy:
        raise KeyError(key+' has no location next to a standalone runtime database')
    return legacy[key]


# A batch folder holds batch.json, effective-config.json, profiles/ and its
# <profile>/<case>/ runs. batch-v2 moves control files to control/ and logs to
# logs/, the same for both engines.
BATCH_CURRENT = 'batch-v2'
BATCH_LAYOUTS = {
    'batch-v1': {
        'stop': 'STOP',
        'engineering_claim': 'engineering-claim.json',
        'engineering_status': 'engineering-status.json',
        'engineering_lock': 'engineering-supervisor.lock',
        'supervisor_lock': 'supervisor.lock',
        'codex_home_marker': 'codex-home.json',
        'codex_init_log': 'codex-initialize.log',
        'durable': 'durable',
    },
    'batch-v2': {
        'stop': 'control/STOP',
        'engineering_claim': 'control/engineering-claim.json',
        'engineering_status': 'control/engineering-status.json',
        'engineering_lock': 'control/engineering-supervisor.lock',
        'supervisor_lock': 'control/supervisor.lock',
        'codex_home_marker': 'control/codex-home.json',
        'codex_init_log': 'logs/codex-initialize.log',
        'durable': 'control/durable',
    },
}
BATCH_FOLDERS = ('control', 'logs')


def batch_record():
    """What a newly prepared batch stores in batch.json."""
    return {'layout': BATCH_CURRENT, 'layout_paths': dict(BATCH_LAYOUTS[BATCH_CURRENT])}


def batch_path(batch, key):
    """Absolute path of `key` in this batch, honoring the layout recorded in batch.json."""
    batch = Path(batch)
    record = {}
    if (batch/'batch.json').exists():
        try:
            record = json.loads((batch/'batch.json').read_text())
        except (OSError, ValueError) as error:
            raise LayoutError('batch.json cannot be read: '+str(error)) from error
        if not isinstance(record, dict):
            raise LayoutError('batch.json must be a JSON object')
    recorded = _recorded(record, BATCH_LAYOUTS, 'batch.json')
    if recorded is not None:
        if key not in recorded:
            raise KeyError(key+' is not part of layout '+record['layout'])
        return _inside(batch, recorded[key])
    if key not in BATCH_LAYOUTS['batch-v1']:
        raise KeyError(key+' is not part of layout batch-v1')
    return batch/BATCH_LAYOUTS['batch-v1'][key]


def main():
    parser = argparse.ArgumentParser(description='Print a run\'s resolved host paths as JSON (for the Node hosts).')
    parser.add_argument('run', type=Path)
    parser.add_argument('--engine', choices=['claude', 'codex'])
    args = parser.parse_args()
    print(json.dumps({'layout': layout(args.run), 'paths': paths(args.run, args.engine)}, sort_keys=True))


if __name__ == '__main__':
    main()
