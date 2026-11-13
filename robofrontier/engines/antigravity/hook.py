"""Trusted PreToolUse policy. It never accepts an actor or connection from a model."""
import json
from pathlib import Path
import shlex
import sys


def decision(run, event):
    run = Path(run).resolve()
    call = event.get('toolCall') or {}
    name = call.get('name', event.get('tool_name', event.get('toolName', '')))
    args = call.get('args', event.get('tool_input', event.get('toolInput', {})))
    if not isinstance(args, dict):
        return {'decision': 'deny', 'reason': 'Invalid tool input'}
    from .settings import mcp_tools
    from robofrontier.runtime import tool_mode
    if tool_mode.of_run(run) == tool_mode.ROBOT_ONLY:
        # The CLI still declares manage_task and its MCP resource tools; none may run.
        if name == 'mcp_robofrontier_robot':
            return {'decision': 'allow'}
        return {'decision': 'deny', 'reason': 'robot is your only tool'}
    if name == 'manage_task' and args.get('Action') in ('list', 'status'):
        return {'decision': 'allow'}
    if name in ['mcp_robofrontier_' + tool for tool in mcp_tools(run)]:
        return {'decision': 'allow'}
    return {'decision': 'deny', 'reason': 'Use the bound robot and policy file tools'}



def main():
    try:
        result = decision(sys.argv[1], json.load(sys.stdin))
    except Exception:
        result = {'decision': 'deny', 'reason': 'Policy hook could not verify this call'}
    print(json.dumps(result))


if __name__ == '__main__':
    main()
