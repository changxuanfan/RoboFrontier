"""Engineering-only fault injection: make one independent action's stop fail to settle.

Used to test single-arm recovery (`recover_action`) with real models. The chosen action
times out after `timeout_sim_s`; once stopping, the arm is treated as unsettled for
`hold_unsettled_sim_s` more seconds beyond the usual 3 s stop window, so the action is
reported uncertain with local recovery, and `recover_action` confirms the stop only
afterwards. The setting lives in private/inputs (never readable by the policy), is
frozen in the manifest before the run starts, and marks the run as fault-injected.
"""
import argparse
import hashlib
import json
from pathlib import Path

from .setup import verify_inputs, write_json

SCHEMA = 'robofrontier.fault-injection.v1'
RELATIVE = 'private/inputs/fault-injection.json'


def arm(run, robot, action_index, op='move', timeout_sim_s=1., hold_unsettled_sim_s=8.):
    """Freeze a fault for the `action_index`-th independent `op` of `robot` (1-based);
    robot `*` counts that op across all arms, whichever arm the policy chooses."""
    run = Path(run).resolve()
    from .store import RuntimeStore
    store = RuntimeStore(run / 'private/state/runtime.sqlite')
    try:
        if store.get('lifecycle') != 'prepared': raise ValueError('Faults are set only before a run starts')
    finally: store.close()
    task = json.loads((run / 'private/inputs/task.json').read_text())
    if (robot != '*' and robot not in task['arms']) or op not in ('move', 'gripper') or type(action_index) is not int or action_index < 1:
        raise ValueError('Choose an arm of this task, move or gripper, and a positive action index')
    if not 0 < timeout_sim_s <= 30 or not 0 < hold_unsettled_sim_s <= 120:
        raise ValueError('Timeout and hold must be positive and bounded')
    if verify_inputs(run): raise ValueError('Inputs already changed')
    spec = {'schema': SCHEMA, 'kind': 'unsettled_stop', 'robot': robot, 'op': op, 'action_index': action_index,
            'timeout_sim_s': float(timeout_sim_s), 'hold_unsettled_sim_s': float(hold_unsettled_sim_s),
            'scope': 'Engineering test of single-arm recovery; not a scored trial'}
    path = run / RELATIVE
    with path.open('x') as out: json.dump(spec, out, indent=2)
    manifest_path = run / 'private/inputs/manifest.json'; manifest = json.loads(manifest_path.read_text())
    manifest['input_sha256'][RELATIVE] = hashlib.sha256(path.read_bytes()).hexdigest()
    manifest['fault_injection'] = spec
    write_json(manifest_path, manifest)
    if verify_inputs(run): raise ValueError('Fault setting did not verify')
    return spec


def load(run):
    """This run's frozen fault, or None. A fault not bound to the manifest is refused."""
    path = Path(run) / RELATIVE
    if not path.exists(): return None
    manifest = json.loads((Path(run) / 'private/inputs/manifest.json').read_text())
    if manifest.get('input_sha256', {}).get(RELATIVE) != hashlib.sha256(path.read_bytes()).hexdigest():
        raise ValueError('Fault setting is not bound to the run manifest')
    spec = json.loads(path.read_text())
    if spec.get('schema') != SCHEMA or spec != manifest.get('fault_injection'): raise ValueError('Invalid fault setting')
    return dict(spec)


def main():
    parser = argparse.ArgumentParser(description='Engineering only: make one action stop fail to settle')
    parser.add_argument('run', type=Path); parser.add_argument('--robot', required=True, help="An arm, or '*' for any arm")
    parser.add_argument('--action-index', type=int, required=True); parser.add_argument('--op', default='move')
    parser.add_argument('--timeout-sim-s', type=float, default=1.); parser.add_argument('--hold-unsettled-sim-s', type=float, default=8.)
    args = parser.parse_args()
    print(json.dumps(arm(args.run, args.robot, args.action_index, args.op, args.timeout_sim_s, args.hold_unsettled_sim_s)))


if __name__ == '__main__': main()
