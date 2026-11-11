"""Render the frozen access contract, agent and MCP configuration once per run."""
import fcntl
import json
import os
from pathlib import Path
import shlex
import sys

from robofrontier.runtime import tool_mode
from robofrontier.runtime.setup import write_json

ROBOT_TOOL, FILE_TOOLS = 'robot', ('policy_exec', 'policy_image')


def mcp_tools(run):
    """The MCP tools a role of this run is given: the robot tool, and in a full run the file tools."""
    return (ROBOT_TOOL,) if tool_mode.of_run(run) == tool_mode.ROBOT_ONLY else (ROBOT_TOOL, *FILE_TOOLS)


def cli_workspace(run):
    """Keep Linux CLI configuration outside the Landlock-writable workspace."""
    return run/'private/engine/cli-workspace' if sys.platform == 'linux' else run/'workspace'


def prepare_tools(run):
    run = Path(run).resolve()
    path = run/'private/inputs/policy-access.json'
    access = json.loads(path.read_text())
    if sys.platform == 'darwin':
        access['filesystem'][str(run/'workspace/.agents')] = 'deny'
    if sys.platform == 'linux':
        access['filesystem'].update({'/proc': 'deny', '/dev': 'deny', '/dev/shm': 'write'})
    write_json(path, access)
    from robofrontier.engines.common.tool_worker import SCHEMA
    write_json(run/'private/inputs/policy-tools.json', {'schema': SCHEMA, 'backend': 'landlock-v1'})


def isolation():
    if sys.platform == 'darwin':
        return 'seatbelt-broker'
    if sys.platform == 'linux':
        # Antigravity's own namespace sandbox has to pass the environment check
        # on the actual node. No silent unconfined fallback in containers.
        from robofrontier.engines.common.landlock import abi
        import ctypes.util
        if abi() < 1 or not ctypes.util.find_library('seccomp'):
            raise ValueError('Antigravity file tools need Landlock and libseccomp')
        return 'landlock-v1'
    raise ValueError('Antigravity policy execution requires macOS or Linux')


def configure(run, python=sys.executable):
    run = Path(run).resolve()
    access = json.loads((run/'private/inputs/policy-access.json').read_text())
    if access.get('network') or access.get('web_search'):
        raise ValueError('Antigravity policies require network and web search disabled')
    folder = cli_workspace(run)/'.agents'
    # Native filesystem/shell tools are absent from the custom agent. A second
    # permission gate denies them even if the CLI unexpectedly exposes one.
    settings = {'enableTerminalSandbox': True, 'toolPermission': 'proceed-in-sandbox',
                'useG1Credits': False, 'permissions': {'deny': ['read_file(/)', 'write_file(/)', 'unsandboxed']}}
    agent = ('---\nname: robofrontier\ndescription: RoboFrontier policy role.\ntools:\n'
             + '  - manage_task\n'
             + 'subagent: false\nmainAgent: true\n---\n'
             + (run/'private/inputs/bootstrap/system.md').read_text())
    # Nothing is added to the system prompt on any platform. The CLI's own working
    # folder (cli_workspace) is not named to the model: its environment section is
    # removed (context.policy_spec), and file tools run in the policy workspace.
    root = Path(__file__).resolve().parents[3]
    hook = shlex.join([os.path.abspath(python), '-m', 'robofrontier.engines.antigravity.hook', str(run)])
    expected = {
        folder/'agents/robofrontier/agent.md': agent,
        folder/'mcp_config.json': json.dumps({'mcpServers': {'robofrontier': {
            'command': os.path.abspath(python),
            'args': ['-m', 'robofrontier.engines.antigravity.robot_mcp', '--run-dir', str(run)],
            'env': {'PYTHONPATH': str(root)}, 'tools': {name: {'eager': True} for name in mcp_tools(run)}, 'timeoutSeconds': -1}}}, sort_keys=True),
        folder/'hooks.json': json.dumps({'hooks': {'PreToolUse': [{'matcher': '.*', 'hooks': [
            {'type': 'command', 'command': hook}]}]}}, sort_keys=True),
    }
    private = run/'private/engine'
    private.mkdir(parents=True, exist_ok=True)
    with (private/'configuration.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        for path, content in expected.items():
            if path.is_symlink() or path.exists() and path.read_text() != content:
                raise ValueError('Antigravity workspace configuration changed: ' + str(path))
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                with path.open('x') as stream:
                    os.fchmod(stream.fileno(), 0o600)
                    stream.write(content)
        target = private/'settings.json'
        if target.exists() and json.loads(target.read_text()) != settings:
            raise ValueError('Antigravity sandbox settings changed')
        write_json(target, settings)
    return target
