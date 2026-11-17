"""The runtime operations a policy role may call through its robot tool.

One list for every transport: the Claude robot MCP, the Codex CLI robot tool (the
runtime itself rejects anything else) and the Codex Desktop robot MCP. Meta's
administrative methods are never reachable through a policy connection.
"""
POLICY_OPS = frozenset(('public_image', 'ready', 'robot_model', 'check_motion', 'send', 'inbox', 'wait_events',
                        'history', 'work', 'delegate', 'return_task', 'team', 'checkpoint', 'yield',
                        'observe', 'stop', 'move', 'gripper', 'action_batch', 'recover_action', 'job', 'finish',
                        'pending',
                        # Only a robot_only run accepts these (runtime/tool_mode.py); the runtime
                        # refuses them elsewhere.
                        'public_file', 'skills'))


def check_request(op, data):
    """Reject a call with the reason a model can act on: wrong operation or wrong data type."""
    if op not in POLICY_OPS:
        raise ValueError('Unknown or administrative robot operation: ' + str(op))
    if not isinstance(data, dict):
        raise ValueError('data must be a JSON object such as {"to": ["Controller"], "text": "..."}, not '
                         + ('a string holding JSON' if isinstance(data, str) else 'a ' + type(data).__name__))
