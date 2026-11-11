"""Native Claude Code CLI runner for one policy session.

Offline logic only: building the CLI command and isolated environment, running
one `claude -p` turn, and summarising its stream-json evidence. A process exit
or a `result` event only means the model turn ended; task success is decided by
the runtime and is never inferred here.
"""
import hashlib
import json
import os
import queue
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import weakref
from pathlib import Path
from urllib.parse import urlsplit
from robofrontier.engines.claude.recovery import api_error, capacity_code, usage_limit_of
from robofrontier.engines.claude.native_home import config_directory
from robofrontier.engines.claude.cost_state import amount, baseline, invocation_cost
from robofrontier.batch.metrics import host_event
from robofrontier.runtime import policy_env, layout as run_layout

ENV_PASSTHROUGH = ('PATH', 'LANG', 'LC_ALL', 'TMPDIR')
ROBOT_TOOL = 'mcp__robot__robot'
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
# Runs with a frozen access table (robofrontier/runtime/access.py) give policy turns the
# same working tools as the Codex route: files, shell and the bound robot tool. Web
# tools stay off on both engines.
POLICY_TOOLS = ('Bash', 'Read', 'Write', 'Edit', 'Glob', 'Grep')
# Write and Edit are not pre-allowed: acceptEdits accepts edits inside the working
# folder, and with permission prompts off every other edit is refused.
ALLOWED_POLICY_TOOLS = ('Bash', 'Read', 'Glob', 'Grep', ROBOT_TOOL)
# Claude Code has no compact-at-N setting: it compacts at CLAUDE_CODE_AUTO_COMPACT_WINDOW
# minus a fixed 33,000-token summary buffer (measured on CLI 2.1.312 and 2.1.316), so the
# window is set to land on the run's frozen compaction threshold.
CLAUDE_COMPACT_BUFFER = 33000


def _denied_paths(table):
    """Paths to deny for Claude, whose rules have no "most specific path wins".

    A denied folder that contains an allowed path (the repository holding this run)
    becomes denies on everything beside the route to that path, level by level, as the
    folder stands when the settings are rendered: once per CLI process, which a
    persistent session keeps for the whole run. A folder created later beside the route
    is not on this list; `_private_globs` keeps every run's private/ closed regardless.
    """
    entries = {Path(p): mode for p, mode in table.items()}
    denied = []
    for path, mode in entries.items():
        if mode != 'deny':
            continue
        allowed = [a for a, m in entries.items() if m != 'deny' and a != path and path in a.parents]
        if not allowed:
            denied.append(path)
            continue
        frontier = [path]
        while frontier:
            folder = frontier.pop()
            keep = {a.relative_to(folder).parts[0] for a in allowed if folder in a.parents}
            try:
                children = list(folder.iterdir())
            except OSError:
                continue
            for child in children:
                if child.name not in keep:
                    denied.append(child)
                elif not any(a == child for a in allowed):
                    frontier.append(child)
    return sorted(set(denied))


def _private_globs(run, table):
    """Patterns for every private/ folder below the denied folders that hold this run.

    The rendered deny list is fixed for a CLI process, so a run folder prepared later
    beside the route (another batch under the same runs folder) would be open. These
    patterns cover each run's private/ there, now and later. They also cover a folder
    or file named private inside this run's workspace/, which the policy then cannot
    use; its own public/ and workspace/ stay open. A run that itself lies below a folder
    named private gets no pattern for that root, which would close the whole run.
    """
    roots = [Path(p) for p, mode in table.items() if mode == 'deny' and Path(p) in run.parents]
    return sorted(str(root) + suffix for root in roots if 'private' not in run.relative_to(root).parts
                  for suffix in ('/**/private', '/**/private/**'))


def policy_settings(run_dir):
    """Settings for a policy turn rendered from the run's frozen access table, or None
    for runs prepared before the table existed.

    Permission rules cover the file tools; the sandbox covers Bash. Both are needed
    because neither applies to the other. Harness processes (the robot MCP, the CLI's
    own configuration) are not sandboxed and keep their access.
    """
    run = Path(run_dir).resolve()
    path = run/'private/inputs/policy-access.json'
    if not path.is_file():
        return None
    access = json.loads(path.read_text())
    table = access['filesystem']
    hidden = [str(p) for p in _denied_paths(table)]
    private = _private_globs(run, table)
    # A run with a policy environment renders its table as written: the sandbox lets a more
    # specific allowRead win, so a folder created during the run is closed too. The private/
    # patterns are matched by the macOS sandbox; Claude Code's Linux sandbox ignores glob
    # patterns, so there Bash keeps the literal list only.
    sandbox_read = ({'denyRead': sorted(p for p, mode in table.items() if mode == 'deny') + private,
                     'allowRead': sorted(p for p, mode in table.items() if mode != 'deny' and p != '/')}
                    if access.get('policy_env') else {'denyRead': hidden + private})
    writable = sorted(p for p, mode in table.items() if mode == 'write')
    # Claude rules take absolute paths as //path. acceptEdits accepts edits only inside
    # the working folder and every other edit is refused; these rules also keep hidden
    # paths and the frozen inputs out of reach. Rules follow gitignore matching, where
    # 'path/**' covers only what lies inside path, so each path also gets an exact rule:
    # a hidden file (the repository's .env beside the runs folder) is denied by that one.
    def rules(tool, paths):
        return [tool+'(//'+p.lstrip('/')+suffix+')' for p in paths for suffix in ('', '/**')]
    deny = rules('Read', hidden) + rules('Edit', hidden+[str(run/'public')])
    # Glob rules are matched when a tool runs, so they also cover run folders created later.
    deny += ['%s(//%s)' % (tool, p.lstrip('/')) for tool in ('Read', 'Edit') for p in private]
    return {'permissions': {'deny': deny},
            'sandbox': {'enabled': True, 'allowUnsandboxedCommands': False,
                        'filesystem': {'allowWrite': writable, **sandbox_read},
                        'network': {'allowedDomains': ['*'] if access.get('network') else []}}}


def confine(run_dir, settings, config_dir):
    """A policy turn's settings and extra environment for its frozen Bash isolation.

    'claude-sandbox' (the default, and every earlier run) keeps Claude Code's sandbox.
    'landlock-v1' turns it off and confines each Bash command instead through
    CLAUDE_CODE_SHELL_PREFIX (robofrontier/engines/common/landlock.py), with rules
    rendered now from the same access table; the permission rules are unchanged.
    """
    run = Path(run_dir).resolve()
    launch = run/'private/inputs/claude.json'
    mode = (json.loads(launch.read_text()) if launch.is_file() else {}).get('bash_isolation', 'claude-sandbox')
    extra = {}
    if settings is not None and json.loads((run/'private/inputs/policy-access.json').read_text()).get('policy_env'):
        # Sourced before each Bash command, so only policy shells get the frozen variables;
        # the CLI keeps its own environment.
        extra['CLAUDE_ENV_FILE'] = str(run/'public/inputs'/policy_env.SHELL_FILE)
    if settings is None or mode == 'claude-sandbox':
        return settings, extra
    if mode != 'landlock-v1':
        raise ValueError('Unknown Bash isolation: ' + str(mode))
    from robofrontier.engines.common import landlock as landlock_shell
    table = json.loads((run/'private/inputs/policy-access.json').read_text())['filesystem']
    folder = run_layout.path(run, 'engine_mcp', 'claude').parent/'bash-isolation'
    folder.mkdir(parents=True, exist_ok=True)
    rules = folder/'rules.json'
    # The exact strings Claude Code passes to the prefix to start this run's robot MCP servers.
    servers = [json.loads(p.read_text())['mcpServers']['robot']
               for p in sorted(run_layout.path(run, 'engine_mcp', 'claude').glob('*.json'))]
    unconfined = [shlex.join([s['command'], *s['args']]) for s in servers]
    # Claude Code sources a snapshot of its shell from its configuration directory first.
    landlock_shell.write_rules(rules, landlock_shell.allowlist(
        table, read=[Path(config_dir).resolve()/'shell-snapshots'], write=landlock_shell.DEVICES), unconfined)
    prefix = folder/'bash-prefix'
    landlock_shell.write_atomic(prefix, '#!/bin/sh\nexec ' + ' '.join(shlex.quote(str(part)) for part in (
        sys.executable, '-I', Path(landlock_shell.__file__).resolve(), rules)) + ' "$@"\n', mode=0o755)
    return {**settings, 'sandbox': {'enabled': False}}, {**extra, 'CLAUDE_CODE_SHELL_PREFIX': str(prefix)}


def policy_system_prompt(run_dir):
    path = Path(run_dir)/'private/inputs/bootstrap/system.md'
    return path.read_text() if path.is_file() else None


def policy_cwd(run_dir):
    return run_layout.path(run_dir, 'policy_cwd', 'claude')


def _oauth_endpoint_allowed(base):
    if not base: return True  # Claude's default Anthropic endpoint.
    try:
        url=urlsplit(base)
        return (url.scheme=='https' and url.hostname=='api.anthropic.com' and url.port in (None,443)
                and not url.username and not url.password and url.path in ('','/') and not url.query and not url.fragment)
    except ValueError:
        return False


def gate_settings(gate):
    """A PreToolUse hook that holds every tool call until `gate['open']` exists.

    It refuses the call once `gate['closed']` exists or `gate['deadline']` (epoch seconds)
    passes. A forked delegate starts its first turn before its runtime activation; this
    keeps it from running any tool until then. The hook's own timeout outlasts its
    deadline, so it never times out into allowing a call.
    """
    deadline = int(gate['deadline'])
    opened, closed = shlex.quote(str(gate['open'])), shlex.quote(str(gate['closed']))
    script = (f'while :; do [ -e {opened} ] && exit 0; [ -e {closed} ] && break; '
              f'[ "$(date +%s)" -lt {deadline} ] || break; sleep 0.1; done; '
              'echo "Delegate setup has not completed; this tool call was not run." >&2; exit 2')
    timeout = max(0, deadline - int(time.time())) + 30
    return {'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [
        {'type': 'command', 'command': script, 'timeout': timeout}]}]}}


def settings_argument(settings, folder=None):
    """The --settings value: the JSON itself, or with `folder` the path of a file holding it.

    One argv string is limited to 128 KiB on Linux, and the deny list grows with every
    folder beside the run route, so runners pass a file. Its name is the content's hash,
    so turns with the same settings share one file and a file is never rewritten.
    """
    text = json.dumps(settings, sort_keys=True)
    if folder is None:
        return text
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    path = folder/('settings-' + hashlib.sha256(text.encode()).hexdigest()[:24] + '.json')
    if not path.is_file():
        fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=folder)
        try:
            with os.fdopen(fd, 'w') as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(text)
            os.replace(temporary, path)
        finally:
            try: os.unlink(temporary)
            except FileNotFoundError: pass
    return str(path)


def settings_folder(run_dir):
    """Where runners keep the settings files of a run's policy turns (private to the harness)."""
    return run_layout.path(Path(run_dir).resolve(), 'engine_mcp', 'claude').parent/'policy-settings'


def build_command(model, effort, mcp_config, prompt, session_id=None, max_budget_usd=None, binary='claude', resume=None,
                  fork_from=None, enable_robot=True, auth_mode='api_key', prompt_via_stdin=False, settings=None,
                  system_prompt=None, stream_input=False, gate=None, settings_dir=None):
    """Return argv for one headless turn.

    With `settings` (see `policy_settings`) a policy turn gets the bound robot tool plus
    file and shell tools confined by those settings; without it, only the robot tool.
    `resume` continues an existing session by its explicit ID; it never picks the most
    recent one. `fork_from` starts session `session_id` as a fork of that session;
    a delegate fork passes `gate` (see `gate_settings`). With `settings_dir` the
    settings are passed as a file written there (see `settings_argument`).
    """
    if effort not in EFFORTS:
        raise ValueError('Unsupported effort: ' + str(effort))
    if not model or not isinstance(model, str):
        raise ValueError('Model ID is required')
    if resume and (session_id or fork_from):
        raise ValueError('Give either session_id or resume, not both')
    if fork_from and not session_id:
        raise ValueError('Fork creation requires an explicit child ID')
    hooks = gate_settings(gate) if gate is not None else None
    session_flags = (['--resume', fork_from, '--fork-session', '--session-id', session_id] if fork_from else
                     ['--resume', resume] if resume else ['--session-id', session_id or str(uuid.uuid4())])
    mcp_arg = str(mcp_config) if enable_robot else '{"mcpServers":{}}'
    if auth_mode not in ('api_key','oauth_token','native_login'):
        raise ValueError('Unsupported Claude authentication mode')
    # --bare would expose only Bash, Read and Edit, so confined policy turns load no
    # user, project or local settings instead. --bare also skips hooks, so a gated turn
    # does the same.
    isolation = (['--bare'] if auth_mode == 'api_key' and settings is None and hooks is None
                 else ['--setting-sources', ''])
    cmd = [binary, '-p'] + isolation + ['--model', model, '--effort', effort] + session_flags + [
           '--mcp-config', mcp_arg, '--strict-mcp-config']
    if enable_robot and settings is not None:
        cmd += ['--tools', ','.join(POLICY_TOOLS), '--permission-mode', 'acceptEdits', '--permission-prompts', 'none',
                '--settings', settings_argument({**settings, **(hooks or {})}, settings_dir),
                '--allowedTools', *ALLOWED_POLICY_TOOLS]
    else:
        cmd += ['--tools', '', '--permission-mode', 'dontAsk']
        if hooks is not None:
            cmd += ['--settings', settings_argument(hooks, settings_dir)]
        if enable_robot:
            cmd += ['--allowedTools', ROBOT_TOOL]
    if system_prompt is not None:
        # Replaces Claude Code's own system prompt, as the Codex route replaces Codex's.
        cmd += ['--system-prompt', system_prompt]
    cmd += ['--output-format', 'stream-json', '--verbose']
    if max_budget_usd is not None:
        if not isinstance(max_budget_usd, (int, float)) or max_budget_usd <= 0:
            raise ValueError('max_budget_usd must be a positive number')
        cmd += ['--max-budget-usd', str(max_budget_usd)]
    # Native runners stream the complete prompt to avoid per-argument OS limits.
    # Keep positional construction for existing direct build_command callers.
    if stream_input:
        # One long-lived process reads user messages as stream-json (PersistentSession).
        return cmd + ['--input-format', 'stream-json']
    if prompt_via_stdin:
        cmd += ['--input-format', 'text', '--']
    else:
        cmd += ['--', prompt]
    return cmd


# The subscription token reaches the CLI on a pipe, never in its environment: a policy shell can
# read its parent's environment where the Bash sandbox does not hide other processes (Claude
# Code's bubblewrap on Linux; check_policy_env's read_parent_environ probe).
TOKEN_FD_VARIABLE = 'CLAUDE_CODE_OAUTH_TOKEN_FILE_DESCRIPTOR'


def start_cli(cmd, env, **options):
    """Popen for a Claude CLI process, with a subscription token moved from `env` to a pipe."""
    env = dict(env)
    token = env.pop('CLAUDE_CODE_OAUTH_TOKEN', None)
    if token is None:
        return subprocess.Popen(cmd, env=env, **options)
    read, write = os.pipe()
    try:
        os.write(write, token.encode())
    finally:
        os.close(write)
    try:
        env[TOKEN_FD_VARIABLE] = str(read)
        return subprocess.Popen(cmd, env=env, pass_fds=(read,), **options)
    finally:
        os.close(read)


def build_env(profile, base_env, config_dir):
    """Pass only this profile's endpoint and credential; never inherit other providers' keys."""
    auth_mode=profile.get('auth_mode','api_key')
    key = base_env.get(profile.get('env_key')) if profile.get('env_key') else None
    if auth_mode != 'native_login' and not key:
        raise ValueError('Missing credential variable: ' + str(profile.get('env_key')))
    if profile.get('provider') not in (None, 'anthropic') and not profile.get('base_url'):
        raise ValueError('Non-Anthropic profiles require an explicit base URL before launch')
    env = {name: base_env[name] for name in ENV_PASSTHROUGH if name in base_env}
    if auth_mode == 'native_login':
        home = config_directory('.', profile)
        if home != Path(config_dir).resolve():
            raise ValueError('Native login directory differs from the selected profile')
        config_dir = home
        if not _oauth_endpoint_allowed(profile.get('base_url')):
            raise ValueError('Native login may only use the Anthropic endpoint')
        scope = profile.get('native_config_scope', 'directory')
        if scope not in ('default', 'directory'):
            raise ValueError('Unknown native configuration scope')
        if scope == 'default':
            user_home = base_env.get('HOME')
            if (not isinstance(user_home, str) or not Path(user_home).is_absolute()
                    or (Path(user_home)/'.claude').resolve() != home):
                raise ValueError('Default native login requires HOME matching the frozen configuration directory')
        if base_env.get('HOME'):
            env['HOME'] = base_env['HOME']
        credential_name=None
    elif auth_mode == 'oauth_token':
        if profile.get('provider') != 'anthropic' or profile['env_key'] != 'CLAUDE_CODE_OAUTH_TOKEN':
            raise ValueError('OAuth token mode is limited to the Anthropic subscription profile')
        if not _oauth_endpoint_allowed(profile.get('base_url')):
            raise ValueError('OAuth token may only be sent to the Anthropic endpoint')
        credential_name='CLAUDE_CODE_OAUTH_TOKEN'
    elif auth_mode == 'api_key':
        credential_name='ANTHROPIC_API_KEY'
    else:
        raise ValueError('Unsupported Claude authentication mode')
    env.update({
        'CLAUDE_CONFIG_DIR': str(config_dir),
        'DISABLE_TELEMETRY': '1',
        'DISABLE_ERROR_REPORTING': '1',
        'CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC': '1',
        # wait_events can run for 600 seconds; reserve time for transport.
        'MCP_TOOL_TIMEOUT': '660000',
        'ENABLE_TOOL_SEARCH': 'false',
        'ENABLE_CLAUDEAI_MCP_SERVERS': 'false',
    })
    if credential_name is not None:
        env[credential_name] = key
    if auth_mode == 'native_login' and scope == 'default':
        # An explicitly set CLAUDE_CONFIG_DIR selects a different credential
        # namespace even when its path equals the native default directory.
        env.pop('CLAUDE_CONFIG_DIR', None)
    if profile.get('base_url'):
        env['ANTHROPIC_BASE_URL'] = profile['base_url']
    if base_env.get('ROBOFRONTIER_EGRESS_INSTANCE'):
        # A managed allocation route (robofrontier/batch/slurm_proxy.py) is the CLI's only way out.
        env.update({name: base_env[name] for name in ('HTTPS_PROXY', 'NO_PROXY') if name in base_env})
    return env


def summarize(lines):
    """Reduce stream-json lines to turn-level facts. `task_success` is always None here."""
    events, malformed = [], 0
    for line in lines:
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if isinstance(event, dict):
            events.append(event)
        else:
            malformed += 1
    init = next((e for e in events if e.get('type') == 'system' and e.get('subtype') == 'init'), {})
    results = [e for e in events if e.get('type') == 'result']
    result = results[-1] if results else None
    tool_calls = sum(
        1 for e in events if e.get('type') == 'assistant'
        for block in (e.get('message') or {}).get('content') or []
        if isinstance(block, dict) and block.get('type') == 'tool_use')
    observe_top_ids = {
        block.get('id') for e in events if e.get('type') == 'assistant'
        for block in (e.get('message') or {}).get('content') or []
        if isinstance(block, dict) and block.get('type') == 'tool_use'
        and block.get('name') == ROBOT_TOOL and isinstance(block.get('input'), dict)
        and block['input'].get('op') == 'observe' and isinstance(block['input'].get('views'), list)
        and 'top' in block['input']['views'] and isinstance(block.get('id'), str) and block['id']}
    observe_top_image_results = sum(
        1 for e in events if e.get('type') == 'user'
        for block in (e.get('message') or {}).get('content') or []
        if isinstance(block, dict) and block.get('type') == 'tool_result'
        and block.get('tool_use_id') in observe_top_ids and not block.get('is_error')
        and isinstance(block.get('content'), list)
        and any(isinstance(item, dict) and item.get('type') == 'image' for item in block['content']))
    if result is None:
        turn = 'unknown'
    elif result.get('is_error') or result.get('subtype') != 'success':
        turn = 'failed'
    else:
        turn = 'ended'
    return {
        'session_id': (result or init).get('session_id') or init.get('session_id'),
        'reported_model': init.get('model'),
        'turn_status': turn,
        'capacity_error_code': capacity_code(events),
        'usage_limit': usage_limit_of(events) if turn == 'failed' else None,
        'api_error': api_error(events),
        'result_subtype': (result or {}).get('subtype'),
        'num_turns': (result or {}).get('num_turns'),
        'result_text': ((result or {}).get('result') or '')[:2000],
        'tool_calls': tool_calls,
        'observe_top_calls': len(observe_top_ids),
        'observe_top_image_results': observe_top_image_results,
        'usage': (result or {}).get('usage'),
        'model_usage': (result or {}).get('modelUsage'),
        'total_cost_usd': (result or {}).get('total_cost_usd'),
        'malformed_lines': malformed,
        'task_success': None,
    }


def _redact(text, secret):
    if not secret:
        return text
    # JSON escaping can change how a credential appears in the event stream.
    variants = {secret, json.dumps(secret, ensure_ascii=True)[1:-1],
                json.dumps(secret, ensure_ascii=False)[1:-1]}
    for variant in sorted(variants, key=len, reverse=True):
        if variant:
            text = text.replace(variant, '[redacted]')
    return text


class PreLaunchCancelled(InterruptedError):
    """Cancellation was observed before a CLI subprocess was created."""


def run_turn(profile, model, effort, mcp_config, prompt, run_dir, base_env,
             session_id=None, timeout=None, max_budget_usd=None, binary='claude', resume=None, events_name='events.jsonl',
             cancel_event=None, fork_from=None, enable_robot=True, actor=None, phase='policy', gate=None):
    """Run one turn, persist its raw events under run_dir, and return a status record.

    `timeout=None` removes the per-turn deadline; cancellation remains active.
    Status is `timeout` when the process is killed at the deadline, otherwise
    `ended` or `failed` from the turn result. Callers must still verify physical
    outcomes through the runtime before treating a task as finished.
    """
    run_dir = Path(run_dir).resolve()
    evidence = run_layout.path(run_dir, 'engine_turns', 'claude')
    evidence.mkdir(parents=True, exist_ok=True)
    config_dir = config_directory(run_dir, profile)
    if profile.get('auth_mode') != 'native_login':
        config_dir.mkdir(parents=True, exist_ok=True)
    before = baseline(config_dir, fork_from or resume)
    native_limit = max_budget_usd
    if max_budget_usd is not None:
        if isinstance(max_budget_usd, bool) or not isinstance(max_budget_usd, (int, float)):
            raise ValueError('max_budget_usd must be a positive number')
        maximum = amount(max_budget_usd)
        if maximum is None or maximum <= 0:
            raise ValueError('max_budget_usd must be a positive number')
        # Native reports retain session history, but the CLI budget limits
        # this invocation. Adding historical cost here would enlarge the cap.
        native_limit = float(maximum)
    settings, confined = confine(run_dir, policy_settings(run_dir) if enable_robot else None, config_dir)
    cmd = build_command(model, effort, mcp_config, prompt, session_id, native_limit, binary, resume,
                        fork_from=fork_from, enable_robot=enable_robot, auth_mode=profile.get('auth_mode','api_key'),
                        prompt_via_stdin=True, settings=settings, system_prompt=policy_system_prompt(run_dir),
                        gate=gate, settings_dir=settings_folder(run_dir))
    env = {**build_env(profile, base_env, config_dir), **confined}
    launch = run_dir/'private/inputs/claude.json'
    frozen = json.loads(launch.read_text()) if launch.is_file() else {}
    if frozen.get('auto_compact_token_limit'):
        env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'] = str(int(frozen['auto_compact_token_limit'])+CLAUDE_COMPACT_BUFFER)
    cwd = policy_cwd(run_dir)
    raw = evidence / events_name
    # A queued worker may reach this point after its supervisor has stopped it.
    # Do not launch a potentially paid CLI turn when cancellation is already set.
    # Cancellation racing with Popen is still treated as an unknown outcome.
    if cancel_event is not None and cancel_event.is_set():
        raise PreLaunchCancelled('Claude turn cancelled before launch')
    began = time.monotonic()
    host_event(run_dir, 'cli_turn_started', actor=actor, session_id=session_id or resume,
               events_name=events_name, phase=phase)
    # Spool before launch so timeout polling never has to resume a partial pipe
    # write. The unlinked file is private, and the child inherits its own fd.
    with tempfile.TemporaryFile() as prompt_input:
        prompt_input.write(prompt.encode('utf-8'))
        prompt_input.seek(0)
        process = start_cli(cmd, env, cwd=cwd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, stdin=prompt_input, start_new_session=True)
    deadline = None if timeout is None else time.monotonic() + timeout
    while True:
        remaining = None if deadline is None else deadline - time.monotonic()
        cancelled = cancel_event is not None and cancel_event.is_set()
        if cancelled or (remaining is not None and remaining <= 0):
            # The owner must reconcile outstanding physical operations separately.
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except (ProcessLookupError, PermissionError):
                # macOS refuses (EPERM) to signal a group whose members are all zombies.
                pass
            stdout, stderr = process.communicate()
            status = 'cancelled' if cancelled else 'timeout'
            break
        try:
            wait = remaining
            if cancel_event is not None:
                wait = 0.25 if remaining is None else min(0.25, remaining)
            stdout, stderr = process.communicate(timeout=wait)
            status = 'exited'
            break
        except subprocess.TimeoutExpired:
            continue
    secret = base_env.get(profile.get('env_key')) if profile.get('env_key') else None
    stdout = _redact(stdout, secret)
    # Evidence can contain model output and private task observations.
    fd = os.open(raw, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, 'w') as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(stdout)
    summary = summarize(stdout.splitlines())
    invocation_cost(summary, before)
    try:
        after = baseline(config_dir, summary.get('session_id')) if summary.get('session_id') else None
        if after is not None and amount(summary.get('native_session_total_cost_usd')) != after:
            summary.update(total_cost_usd=None, cost_scope='unknown')
    except ValueError:
        summary.update(total_cost_usd=None, cost_scope='unknown')
    if status in ('timeout', 'cancelled'):
        summary['turn_status'] = 'unknown'
    duration = time.monotonic()-began
    host_event(run_dir, 'cli_turn_completed', actor=actor, session_id=summary.get('session_id'),
               events_name=events_name, phase=phase, duration_s=duration,
               usage=summary.get('usage'), reported_cost_usd=summary.get('total_cost_usd'),
               native_session_total_cost_usd=summary.get('native_session_total_cost_usd'),
               cost_scope=summary.get('cost_scope'),
               model_usage=summary.get('model_usage'),
               process=status, exit_code=process.returncode)
    return {
        'duration_s': duration,
        'process': status,
        'exit_code': process.returncode,
        'requested_session_id': session_id or resume,
        'summary': summary,
        'stderr_tail': _redact(stderr, secret)[-1000:],
        'events_path': str(raw.relative_to(run_dir)),
    }


def _stop_process(process):
    if process is None or process.poll() is not None: return
    try: process.stdin.close()
    except (OSError, ValueError): pass
    try: process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        try: os.killpg(process.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError): pass  # EPERM: only zombies left (macOS).
        process.wait()


# An interrupted turn has this long to end before its CLI process is closed (and, after
# another 10 s, killed). Hosts wait up to STOP_WAIT_S for every role to stop.
INTERRUPT_GRACE_S = 30
STOP_WAIT_S = INTERRUPT_GRACE_S + 15


class PersistentSession:
    """Run one policy session's turns through a single long-lived CLI process.

    `claude -p --input-format stream-json` keeps the session and its robot MCP server
    alive between turns, as the Codex app-server does. Each call writes one user
    message, reads events until that turn's result and returns a record shaped like
    run_turn's. A stop or deadline interrupts the turn instead of killing the process;
    its outcome is still unknown. A dead process is replaced on the next turn with
    --resume, continuing the same transcript.

    --max-budget-usd binds at process launch, so a turn with a per-turn budget and a
    tool-free turn close the live process and use run_turn. A delegate's fork is its
    first turn and starts the process.
    Reported cost is cumulative for the session: each turn is charged its increase
    over the previous report of the same process (the first turn of a process over
    the native transcript's recorded total, as run_turn does).
    """
    def __init__(self, interrupt_grace_s=INTERRUPT_GRACE_S):
        self.interrupt_grace_s = interrupt_grace_s
        self.process = None; self.events = None; self.stderr = []; self.secret = None
        self.reported_total = None
        self.lock = threading.Lock()
        self._finalizer = None

    def close(self):
        with self.lock:
            _stop_process(self.process); self.process = None

    def _start(self, profile, model, effort, mcp_config, run_dir, base_env, binary, session_id, resume,
               fork_from=None, gate=None):
        config_dir = config_directory(run_dir, profile)
        if profile.get('auth_mode') != 'native_login':
            config_dir.mkdir(parents=True, exist_ok=True)
        settings, confined = confine(run_dir, policy_settings(run_dir), config_dir)
        cmd = build_command(model, effort, mcp_config, None, session_id, None, binary, resume, fork_from=fork_from,
                            auth_mode=profile.get('auth_mode', 'api_key'), settings=settings,
                            system_prompt=policy_system_prompt(run_dir), stream_input=True, gate=gate,
                            settings_dir=settings_folder(run_dir))
        env = {**build_env(profile, base_env, config_dir), **confined}
        launch = Path(run_dir)/'private/inputs/claude.json'
        frozen = json.loads(launch.read_text()) if launch.is_file() else {}
        if frozen.get('auto_compact_token_limit'):
            env['CLAUDE_CODE_AUTO_COMPACT_WINDOW'] = str(int(frozen['auto_compact_token_limit'])+CLAUDE_COMPACT_BUFFER)
        try:
            source = fork_from or resume
            self.reported_total = baseline(config_dir, source) if source else amount(0)
        except ValueError:
            self.reported_total = None
        self.process = start_cli(cmd, env, cwd=policy_cwd(run_dir), text=True,
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                 start_new_session=True, bufsize=1)
        self.events, self.stderr = queue.Queue(), []
        process, events, stderr = self.process, self.events, self.stderr
        def read_stdout():
            with process.stdout:
                for line in process.stdout: events.put(line)
            events.put(None)
        def read_stderr():
            with process.stderr:
                for line in process.stderr: stderr.append(line); del stderr[:-200]
        threading.Thread(target=read_stdout, daemon=True).start()
        threading.Thread(target=read_stderr, daemon=True).start()
        if self._finalizer: self._finalizer.detach()
        self._finalizer = weakref.finalize(self, _stop_process, process)

    def _write(self, message):
        self.process.stdin.write(json.dumps(message) + '\n'); self.process.stdin.flush()

    def __call__(self, profile, model, effort, mcp_config, prompt, run_dir, base_env, session_id=None, timeout=None,
                 max_budget_usd=None, binary='claude', resume=None, events_name='events.jsonl', cancel_event=None,
                 actor=None, phase='policy', **one_shot):
        if (max_budget_usd is not None or one_shot.get('enable_robot') is False
                or policy_settings(run_dir) is None):
            self.close()
            return run_turn(profile, model, effort, mcp_config, prompt, run_dir, base_env, session_id=session_id,
                            timeout=timeout, max_budget_usd=max_budget_usd, binary=binary, resume=resume,
                            events_name=events_name, cancel_event=cancel_event, actor=actor, phase=phase, **one_shot)
        fork_from, gate = one_shot.pop('fork_from', None), one_shot.pop('gate', None)
        one_shot.pop('enable_robot', None)
        if one_shot: raise TypeError('Unexpected turn options: ' + ', '.join(sorted(one_shot)))
        run_dir = Path(run_dir).resolve()
        evidence = run_layout.path(run_dir, 'engine_turns', 'claude'); evidence.mkdir(parents=True, exist_ok=True)
        if cancel_event is not None and cancel_event.is_set():
            raise PreLaunchCancelled('Claude turn cancelled before launch')
        with self.lock:
            self.secret = base_env.get(profile.get('env_key')) if profile.get('env_key') else None
            if fork_from and self.process is not None and self.process.poll() is None:
                raise ValueError('A fork is the first turn of its process')
            if self.process is None or self.process.poll() is not None:
                # A new process continues the transcript; only the first turn creates it.
                self._start(profile, model, effort, mcp_config, run_dir, base_env, binary,
                            session_id, None if session_id else resume, fork_from, gate)
            before = self.reported_total
            began = time.monotonic()
            host_event(run_dir, 'cli_turn_started', actor=actor, session_id=session_id or resume,
                       events_name=events_name, phase=phase, transport='persistent', pid=self.process.pid)
            lines, status, interrupted_at = [], None, None
            try:
                self._write({'type': 'user', 'message': {'role': 'user', 'content': prompt}})
            except (OSError, ValueError):
                # The CLI exited after the liveness check, before this turn began: a lost CLI
                # (which a run may restart), not a turn of unknown outcome.
                _stop_process(self.process)
                status = 'process_exited'
            deadline = None if timeout is None else began + timeout
            while status is None:
                stopping = (cancel_event is not None and cancel_event.is_set()) or (deadline and time.monotonic() >= deadline)
                if stopping and interrupted_at is None:
                    interrupted_at = time.monotonic()
                    try: self._write({'type': 'control_request', 'request_id': uuid.uuid4().hex, 'request': {'subtype': 'interrupt'}})
                    except (OSError, ValueError): pass
                if interrupted_at and time.monotonic() - interrupted_at > self.interrupt_grace_s:
                    _stop_process(self.process)
                    status = 'cancelled' if cancel_event is not None and cancel_event.is_set() else 'timeout'
                    break
                try: line = self.events.get(timeout=.25)
                except queue.Empty: continue
                if line is None:
                    status = 'process_exited'; break
                lines.append(line)
                try: event = json.loads(line)
                except ValueError: continue
                if event.get('type') == 'result':
                    status = 'exited' if interrupted_at is None else (
                        'cancelled' if cancel_event is not None and cancel_event.is_set() else 'timeout')
            text = _redact(''.join(lines), self.secret)
            raw = evidence / events_name
            fd = os.open(raw, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, 'w') as output:
                os.fchmod(output.fileno(), 0o600); output.write(text)
            summary = summarize(text.splitlines())
            invocation_cost(summary, before)
            raw_total = amount(summary.get('native_session_total_cost_usd'))
            self.reported_total = raw_total if raw_total is not None and status == 'exited' else None
            if status != 'exited': summary['turn_status'] = 'unknown'
            duration = time.monotonic() - began
            # 'exited' with exit code 0 means this turn's result arrived; the process stays up.
            exit_code = 0 if status == 'exited' else self.process.poll()
            host_event(run_dir, 'cli_turn_completed', actor=actor, session_id=summary.get('session_id'),
                       events_name=events_name, phase=phase, duration_s=duration, usage=summary.get('usage'),
                       reported_cost_usd=summary.get('total_cost_usd'),
                       native_session_total_cost_usd=summary.get('native_session_total_cost_usd'),
                       cost_scope=summary.get('cost_scope'), model_usage=summary.get('model_usage'),
                       process=status, exit_code=exit_code, transport='persistent')
            return {'duration_s': duration, 'process': status, 'exit_code': exit_code, 'transport': 'persistent',
                    'requested_session_id': session_id or resume, 'summary': summary,
                    'stderr_tail': _redact(''.join(self.stderr), self.secret)[-1000:],
                    'events_path': str(raw.relative_to(run_dir))}
