"""Where a run and a batch keep their host files.

Every host (including the Node Codex host, through `python -m roboteam.runtime.layout RUN`)
resolves the same files from this one table. Paths are relative to the run or batch
directory. A prepared run records the layout name in private/inputs/manifest.json, a
batch in batch.json.

The run root holds public/ (host-written policy inputs and results), workspace/ (the
policy's only writable folder and working directory, with one shared lessons file,
skills.md) and private/. private/ is split by lifecycle: inputs (frozen), state (live;
control files in state/control), outputs (results), logs and engine (CLI configuration,
MCP configuration, per-turn evidence and transcripts). A stopped run continues in the
same directory; segment k >= 1 keeps its restore pose in
private/inputs/segments/<k>/ and its process outputs in
private/outputs/segments/<k>/ (docs/running/continuation.md).
"""
import argparse
import json
from pathlib import Path

CURRENT = 'run-v6'
PATHS = {
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
}
# Folders a run creates at preparation.
FOLDERS = ('workspace', 'private/logs', 'private/state/control', 'private/engine')


def manifest_record():
    """What a prepared run stores in its manifest."""
    return {'layout': CURRENT}


def path(run, key):
    """Absolute path of `key` in this run."""
    return Path(run)/PATHS[key]


def for_store(store_path, key):
    """A host path found from the run's runtime database, for code that has only the database."""
    store = Path(store_path)
    if store.name == 'runtime.sqlite' and store.parent.name == 'state' and store.parent.parent.name == 'private':
        return path(store.parents[2], key)
    if key != 'admin_log':
        raise KeyError(key+' has no location next to a standalone runtime database')
    return store.parent/'admin-client.log'


# A batch folder holds batch.json, effective-config.json, profiles/ and its
# <profile>/<case>/ runs, with control files in control/ and logs in logs/, the
# same for both engines.
BATCH_CURRENT = 'batch-v2'
BATCH_PATHS = {
    'stop': 'control/STOP',
    'engineering_claim': 'control/engineering-claim.json',
    'engineering_status': 'control/engineering-status.json',
    'engineering_lock': 'control/engineering-supervisor.lock',
    'supervisor_lock': 'control/supervisor.lock',
    'codex_home_marker': 'control/codex-home.json',
    'codex_init_log': 'logs/codex-initialize.log',
    'durable': 'control/durable',
}
BATCH_FOLDERS = ('control', 'logs')


def batch_record():
    """What a prepared batch stores in batch.json."""
    return {'layout': BATCH_CURRENT}


def batch_path(batch, key):
    """Absolute path of `key` in this batch."""
    return Path(batch)/BATCH_PATHS[key]


def main():
    parser = argparse.ArgumentParser(description='Print a run\'s host paths as JSON (for the Node hosts).')
    parser.add_argument('run', type=Path)
    args = parser.parse_args()
    print(json.dumps({'layout': CURRENT, 'paths': PATHS}, sort_keys=True))


if __name__ == '__main__':
    main()
