"""Construct a policy bootstrap solely from frozen, allowlisted public inputs."""
import json
from pathlib import Path

from robofrontier.runtime.bootstrap import frozen_bootstrap
from robofrontier.runtime.store import current_kind


MAX_BOOTSTRAP_BYTES = 400_000


def bootstrap_prompt(run_dir, *, topology='centralized', startup_protocol='ready_barrier_v1', actor='Controller'):
    run = Path(run_dir).resolve()
    # Runs prepared with robofrontier/runtime/bootstrap.py send that frozen message unchanged,
    # the same one the Codex route sends. The text below is for earlier runs.
    frozen = frozen_bootstrap(run, actor)
    if frozen is not None:
        return frozen
    public = (run / 'public/inputs').resolve()
    task = json.loads((public / 'task.json').read_text())
    roles = json.loads((public / 'roles.json').read_text())
    standing = topology in ('hierarchical', 'peer')
    role = current_kind(dict(roles.get('roles', {}).get(actor, {})))
    if roles.get('topology') != topology:
        raise ValueError('Expected a policy role in the selected topology')
    if standing:
        if startup_protocol != 'direct_team_v3' or role.get('kind') not in ('team-controller', 'worker'):
            raise ValueError('Expected a direct-start standing policy role')
    elif topology not in ('centralized', 'adaptive') or actor != 'Controller' or role.get('kind') != 'controller':
        raise ValueError('Expected the selected Controller topology')
    # No filesystem tools are exposed to the policy, so its complete textual
    # public materials must be supplied in the prompt. Images use public_image.
    paths = [('claude-roles/' + actor + '.md') if standing else 'claude-controller.md',
             'task.json', 'roles.json', 'skill/SKILL.md',
             'skill/references/tools.md', 'skill/references/communication.md',
             'skill/references/motion-check.md']
    # Earlier frozen drafts do not contain the shared contract; preserve their
    # existing inputs instead of silently injecting a newer protocol.
    if (public / 'policy-rules.md').is_file(): paths.insert(1, 'policy-rules.md')
    if standing: paths.insert(1, 'claude-controller.md')
    if topology == 'adaptive': paths.append('skill/references/adaptive.md')
    for name in task.get('family_materials', []):
        if not isinstance(name, str): raise ValueError('Invalid public material reference')
        if name.endswith(('.md', '.json', '.txt')): paths.append(name)
    parts = []
    for relative in dict.fromkeys(paths):
        path = (public / relative).resolve()
        if not path.is_relative_to(public) or not path.is_file():
            raise ValueError('Missing or invalid public input: ' + relative)
        parts.append('--- ' + relative + ' ---\n' + path.read_text())
    text = '\n\n'.join(parts)
    if len(text.encode()) > MAX_BOOTSTRAP_BYTES:
        raise ValueError('Public inputs exceed bootstrap size limit')
    extra = ('\n\nThe adaptive role may request bounded delegates through the robot delegate operation. '
             'Native session-management tools and filesystem access are unavailable; use robot work, '
             'history, inbox and authorized messages for status and handback evidence. To read a returned '
             'delegate report, call robot work with data {"delegate_id":"Delegate_..."}; '
             'the authorized report is returned inline as delegate_report.' if topology == 'adaptive' else '')
    if startup_protocol in ('direct_controller_v2', 'direct_team_v3'):
        extra += ('\n\nThe experiment has STARTED and the task clock is running. Read the task and '
                  'observe the scene, then decide and act. You may call ready for robot capabilities; '
                  'continue without waiting for another START.')
        private_task = run / 'private/inputs/task.json'
        protocol = json.loads(private_task.read_text()).get('run_protocol', {}) if private_task.exists() else {}
        if protocol.get('evaluation_semantics') == 'terminal_outcome_v2':
            extra += (' Completion follows the task conditions; supported process events are reported '
                      'according to the task detection rules and do not by themselves veto completion. '
                      'Observe and recover after problems.')
    else:
        extra += ('\n\nBefore START, inspect the task and scene, call ready, save waiting and end '
                  'the startup turn. Await the host START before task actions.')
    return text + ('\n\nTo view a task initial_reference_images entry, robot_layout_image, '
                   'or target.reference_image (such as the Mosaic target pattern), '
                   'call robot with op public_image and data {"names": ["the exact listed path"]}. '
                   'For live observations use observe with cameras and views. You have no filesystem tools. '
                   'To get detailed static geometry, call robot_model with data {"robot":"A"} '
                   '(substitute a robot ID from the task); details are returned inline.') + extra
