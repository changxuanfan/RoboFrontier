"""The first message every policy role receives, generated once at preparation.

Hosts send private/inputs/bootstrap/<actor>.md unchanged. The text is the same for both
engines except its last line (ENGINE_LINES). It carries the role's public text inputs
inline, so no role depends on reading files to start, and states this run's startup
protocol. The run's rules go into the system prompt (system.md), which both engines keep
whole when they compact a long conversation.
"""
import json
from pathlib import Path

from . import layout as run_layout

ENGINE_LINES = {
    'claude': ('To view an image listed in the task (initial_reference_images, robot_layout_image, '
               'target.reference_image), call robot with op public_image and data {"names": ["<listed path>"]}.'),
    'codex': ('View images listed in the task with view_image. Do not use Codex collaboration tools '
              '(spawn_agent and similar); split work only through robot delegate.'),
}
# The first part of every policy turn's system prompt on both engines (system_prompt adds the
# run's rules): it replaces Claude Code's and Codex's own coding-agent instructions, so both
# models see the same text.
SYSTEM_PROMPT = ('You are a RoboFrontier policy agent. Follow the frozen public task, your current role, '
                 'the tool protocol and the evidence boundaries. Command only the robots assigned to your role, '
                 'use other tools within your permissions, and preserve original call IDs across uncertain results. Do not manage the model host, modify '
                 'the benchmark, or read private evaluation data.\n')
# First message of an adaptive delegate; hosts fill {{ACTOR}} and {{SCOPE}} (compact JSON
# of robots, goal, done_when, constraints) from the runtime assignment.
DELEGATE = ('Your current runtime role is {{ACTOR}}, a temporary delegate, not a standing per-robot Worker. '
            'This runtime assignment replaces the inherited parent role, connection and team finish authority; '
            'the task, rules and evidence restrictions remain in force. Inherited pending calls and plans are '
            'history, not work to replay.\n\nAssigned scope, as submitted by the Controller: {{SCOPE}}\n\n'
            'Operate only your assigned robots, and only through your robot tool. The team has started: carry out '
            'the scope autonomously, handle parent messages and report milestones or blockers through the role '
            'protocol. When the scope is done, call return_task with outcome and evidence, then end your turn; '
            'follow skill/references/adaptive.md for waiting, pausing and partial handback, and reread it after a '
            'context gap. Reread the headings of the run\'s skills.md before acting; teammates may have added '
            'entries since you were forked. Do not create delegates or other sessions, use administrative operations, modify the '
            'harness, read private evaluation data or finish the team run.\n')
# Sent to each working role when the run continues after an unexpected exit
# (docs/running/run-segments.md); hosts fill {{SIM_S}} and {{INTERRUPTED}} through fill_resume.
RESUME = ('The host stopped unexpectedly and has now restarted this trial. It is the same trial, continued: your '
          'session, work note, messages, workspace and skills.md are kept, and your role is unchanged. The physical '
          'world was rebuilt from the last recorded pose at sim time {{SIM_S}} s: robot and object poses are as '
          'recorded, but velocities and contact history were reset, and a grasp is held only where one was held when '
          'recorded. Robot actions that were running when the host stopped did not finish; they are recorded as '
          'failed and must not be replayed. Yours: {{INTERRUPTED}}. A tool call cut off by the stop has no result; '
          'check pending and job before relying on it. The time the host was down does not count against the wall '
          'limit. Teammates may have added to skills.md: list its headings again (grep \'^##\' skills.md). Observe '
          'the current scene, then continue the task.\n')
# Sent to each working role when only its model process (Codex app-server or Claude
# CLI) stopped unexpectedly and the host restarted it; the world was never touched.
MODEL_RESTART = ('Your model session was restarted after the model host stopped unexpectedly. The physical world '
                 'kept running and nothing was reset; your session, work note, messages, workspace and skills.md are '
                 'as they were. A tool call cut off by the stop has no result: check pending and job with its '
                 'original ID before relying on it or acting again. Teammates may have added to skills.md: list its '
                 'headings again (grep \'^##\' skills.md). Then continue the task.\n')
# How many such restarts one run allows in total, across all roles and segments,
# before it is sealed for review.
MAX_MODEL_RESTARTS = 3
NETWORK_RESUME = ('Network connectivity recovered after a recorded infrastructure pause. Your previous native turn is confirmed failed; this is a new continuation in the same session and the original live world. Read your saved work and inbox, inspect pending requests and original action IDs, and obtain fresh observations before choosing further work. Preserve completed results and submitted actions. Never replay an old request or infer that a failed model turn means its robot actions did not execute. Continue within your existing role and delegated scope; explicitly return when its agreed completion or documented failure boundary is reached.\n')
# Sent to a role whose model turn failed on a confirmed capacity or rate limit, after the
# host's wait (at most MAX_CAPACITY_RETRIES per session); the same on both engines. When the
# retries are used up, both hosts pause the run (DISPATCH_PAUSED) instead of sending it again.
CAPACITY_RESUME = ('Your previous model turn failed because of a capacity or rate limit and the host waited before '
                   'this continuation. It is the same session and the same live world; nothing was reset or replayed. '
                   'Read your inbox, check pending and job with the original IDs before acting again, and keep '
                   'submitted actions and completed results. Then continue the task.\n')
MAX_CAPACITY_RETRIES = 3
# Sent once to a role whose turn failed on the plan's usage limit, after the world paused until
# the reset and resumed (runtime/quota.py); the same on both engines.
QUOTA_RESUME = ('Your previous model turn failed because the account\'s usage limit was reached. The trial was '
                'paused until the limit reset; that time was not counted, and the world was held exactly as it was. '
                'It is the same session and the same live world; nothing was reset or replayed. Read your inbox, '
                'check pending and job with the original IDs before acting again, and keep submitted actions and '
                'completed results. Then continue the task.\n')
# What workspace/skills.md holds when a run is prepared.
SKILLS_HEADER = ('# Run skills\nShared by all roles in this run. Rules and format: the "Run skills" section '
                 'of your Skill.\n')
STARTUP = {
    'direct_controller_v2': ('The experiment has started and the task clock is running. Read, observe, then decide '
                             'and act; ready is optional and you continue without waiting for another START.'),
    # Standing teams: every initial role is bound before the single START.
    'direct_team_v3': ('The experiment has started for the whole team and the task clock is running. Read, observe, '
                       'then decide and act within your role; ready is optional and you continue without waiting '
                       'for another START.'),
    'ready_barrier_v1': ('Before START, inspect the task and scene, call ready, save waiting and end the startup '
                         'turn. Await the host START before task actions.'),
}


def bootstrap_text(run, actor):
    """The frozen first message for `actor`, validated against this run's public inputs."""
    run = Path(run).resolve()
    public = run / 'public/inputs'
    task = json.loads((public / 'task.json').read_text())
    roles = json.loads((public / 'roles.json').read_text())
    harness = json.loads((run / 'private/inputs/harness.json').read_text())
    topology = roles['topology']
    if roles['roles'].get(actor, {}).get('kind') in (None, 'manager'):
        raise ValueError('Not a policy role: ' + actor)
    paths = ['rules.md', 'task.json', 'roles.json', 'roles/' + actor + '.md', 'skill/SKILL.md',
             'skill/references/tools.md', 'skill/references/motion-check.md']
    if topology != 'centralized': paths.append('skill/references/communication.md')
    if topology == 'adaptive': paths.append('skill/references/adaptive.md')
    if (public / 'environment.md').is_file(): paths.append('environment.md')
    for name in task.get('family_materials', []):
        if not isinstance(name, str): raise ValueError('Invalid public material reference')
        if name.endswith(('.md', '.json', '.txt')): paths.append(name)
    parts = []
    for relative in dict.fromkeys(paths):
        path = (public / relative).resolve()
        if not path.is_relative_to(public) or not path.is_file():
            raise ValueError('Missing or invalid public input: ' + relative)
        # rules.md is the system prompt's second part (system_prompt); the others follow here.
        if relative != 'rules.md':
            parts.append('--- ' + str(public / relative) + ' ---\n' + path.read_text().rstrip('\n'))
    # Written only while a new run is prepared, before its manifest records the layout.
    lessons = run / run_layout.LAYOUTS[run_layout.CURRENT]['skills_file']
    lessons_line = ('Before acting, read the headings of ' + str(lessons) + ', the run\'s shared lessons; '
                    'teammates may add entries during the run.\n\n' if lessons.is_file() else '')
    startup = STARTUP[harness.get('startup_protocol', 'ready_barrier_v1')]
    text = ('This is a new, independent RoboFrontier trial in ' + str(run) + '. Your role is ' + actor + '.\n\n'
            'The run\'s rules are in your system prompt (also at ' + str(public / 'rules.md') + '). Your other '
            'public inputs follow in full, each under its path.\n\n' + '\n\n'.join(parts) + '\n\n--- end of inputs ---\n\n'
            + (READABLE_ENV if (public / 'environment.md').is_file() else READABLE) + '\n\n' + lessons_line + startup + '\n\n'
            + ENGINE_LINES[harness.get('engine', 'codex')] + '\n')
    if len(text.encode()) > MAX_BOOTSTRAP_BYTES:
        raise ValueError('Public inputs exceed the start message size limit')
    return text


# A permission list that denies the repository and then allows this run's folder
# inside it read to some models as "denied"; the more specific entry wins.
READABLE = ('The same files stay readable on disk. Your filesystem permissions deny the repository '
            'that holds this run but allow this run\'s folder; the more specific entry wins. Only '
            'the run\'s private/ folder stays closed. Reread any of them with your file tools when needed.')
READABLE_ENV = ('The same files stay readable on disk. Your filesystem permissions deny the folders that '
                'hold this run but allow its public/ and workspace/ folders; the more specific entry wins. '
                'Everything else in the run stays closed. Reread any of them with your file tools when needed.')
MAX_BOOTSTRAP_BYTES = 400_000


def system_prompt(run):
    """The frozen system prompt: the policy role statement, then this run's rules."""
    rules = (Path(run) / 'public/inputs/rules.md').read_text()
    return SYSTEM_PROMPT + '\n' + rules.rstrip('\n') + '\n'


def write_bootstraps(run):
    """Write one frozen first message per policy role; returns their paths."""
    run = Path(run)
    roles = json.loads((run / 'public/inputs/roles.json').read_text())['roles']
    folder = run / 'private/inputs/bootstrap'
    folder.mkdir()
    (folder / 'system.md').write_text(system_prompt(run))
    written = [folder / 'system.md']
    for actor, info in roles.items():
        if info.get('kind') == 'manager': continue
        target = folder / (actor + '.md')
        target.write_text(bootstrap_text(run, actor))
        written.append(target)
    if json.loads((run / 'public/inputs/roles.json').read_text())['topology'] == 'adaptive':
        target = folder / 'delegate.md'
        target.write_text(DELEGATE)
        written.append(target)
    (folder / 'resume.md').write_text(RESUME)
    (folder / 'model-restart.md').write_text(MODEL_RESTART)
    (folder / 'capacity-resume.md').write_text(CAPACITY_RESUME)
    (folder / 'quota-resume.md').write_text(QUOTA_RESUME)
    notice=folder/'network-resume.md'
    notice.write_text(NETWORK_RESUME)
    written += [folder / 'resume.md', folder / 'model-restart.md', folder / 'capacity-resume.md',
                folder / 'quota-resume.md', notice]
    return written


def fill_resume(run, actor, record):
    """The frozen resume message for `actor` in the segment described by `record`."""
    path = Path(run) / 'private/inputs/bootstrap/resume.md'
    if not path.is_file(): raise ValueError('Run was prepared without a resume message')
    mine = (record.get('interrupted') or {}).get(actor) or []
    return (path.read_text().replace('{{SIM_S}}', '%.2f' % record['restored_sim_s'])
            .replace('{{INTERRUPTED}}', ', '.join(mine) if mine else 'none'))


def delegate_prompt(run, actor, child):
    """The frozen delegate message filled for this assignment, or None for an earlier run."""
    path = Path(run) / 'private/inputs/bootstrap/delegate.md'
    if not path.is_file(): return None
    scope = {'robots': child.get('robots'), 'goal': child.get('goal'), 'done_when': child.get('done_when'),
             'constraints': child.get('constraints') or ''}
    return (path.read_text().replace('{{ACTOR}}', actor)
            .replace('{{SCOPE}}', json.dumps(scope, ensure_ascii=False, separators=(',', ':'))))


def frozen_system_prompt(run):
    """The frozen system prompt, or None for a run prepared before it existed."""
    path = Path(run) / 'private/inputs/bootstrap/system.md'
    return path.read_text() if path.is_file() else None


def frozen_bootstrap(run, actor):
    """The frozen first message, or None for a run prepared before it existed."""
    path = Path(run) / 'private/inputs/bootstrap' / (actor + '.md')
    return path.read_text() if path.is_file() else None
