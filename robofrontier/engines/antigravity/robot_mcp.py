"""Route the shared robot tool using trusted CLI metadata and runtime role bindings."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import threading
import time

from robofrontier.engines.common.robot_mcp import TOOL, RobotBridge, serve
from robofrontier.runtime.store import RuntimeStore
from robofrontier.runtime.setup import write_json
from .driver import native_id
from .profile import fingerprint
from .provenance import steps, tool_call
from .settings import mcp_tools
from robofrontier.engines.common.policy_tools import TOOLS, execute as file_tool


def binding_path(run, call_id):
    return Path(run)/'private/state/antigravity-tool-bindings'/(hashlib.sha256(call_id.encode()).hexdigest()+'.json')


class Router:
    def __init__(self, run):
        self.run = Path(run).resolve()
        # A robot_only run declares and serves the robot tool alone (runtime/tool_mode.py).
        self.file_tools = [tool['name'] for tool in TOOLS if tool['name'] in mcp_tools(self.run)]
        self.tools = [TOOL, *(tool for tool in TOOLS if tool['name'] in self.file_tools)]
        self.bridges = {}
        self.lock = threading.Lock()

    def authorize(self, metadata):
        metadata = metadata or {}
        session = native_id(metadata.get('antigravity.google/conversation_id'))
        progress = metadata.get('progressToken', '')
        store = RuntimeStore(self.run/'private/state/runtime.sqlite')
        try:
            agents = [(actor, agent) for actor, agent in store.agents().items()
                      if agent['thread_id'] == session and agent['kind'] != 'manager']
            if len(agents) != 1 or store.get('lifecycle') != 'running':
                raise ValueError('MCP session is not bound to one running policy role')
            actor, agent = agents[0]
            if agent['kind'] == 'delegate' and agent.get('delegation_state') != 'active':
                raise ValueError('Delegate has not been activated')
        finally:
            store.close()
        return actor, session, progress

    def call_tool(self, name, args, request_id=None, metadata=None):
        if name == 'robot':
            return self.call(args, request_id, metadata)
        if name not in self.file_tools:
            raise ValueError('Unknown tool')
        actor, session, _ = self.authorize(metadata)
        from robofrontier.batch.metrics import host_event
        began = time.monotonic()
        result = file_tool(self.run, name, args)
        host_event(self.run, 'policy_tool_completed', actor=actor, session_id=session,
                   tool=name, duration_s=time.monotonic()-began, is_error=result.get('isError', False))
        return result

    def call(self, args, request_id=None, metadata=None):
        actor, session, progress = self.authorize(metadata)
        with self.lock:
            if session not in self.bridges:
                self.bridges[session] = RobotBridge(self.run, self.run/'private/state/connections'/(actor+'.json'),
                                                   bind_all_delegations=True)
            bridge = self.bridges[session]
        return bridge.call(args, request_id=request_id,
            bind_delegation=lambda *values: self.bind(*values, session=session, progress=progress))

    def bind(self, run, actor, args, call_id, *, session, progress):
        if actor != 'Controller':
            raise ValueError('Only Controller may delegate')
        trajectory, ordinal = progress.rsplit(':', 1)
        native_id(trajectory)
        at = int(ordinal)
        if at < 1:
            raise ValueError('Invalid delegation step')
        launch = json.loads((self.run/'private/inputs/antigravity.json').read_text())
        home = Path(launch['native_home'])
        deadline = time.monotonic() + 10
        while True:
            rows = steps(home, session)
            if len(rows) == at + 1:
                found = tool_call(rows[at])
                original = dict(found['args'])
                original.pop('toolSummary', None)
                if found['name'] != 'mcp_robofrontier_robot' or original != args:
                    raise ValueError('Native delegation parameters differ from MCP request')
                break
            if time.monotonic() >= deadline:
                raise ValueError('Native pending delegation history unavailable')
            time.sleep(.05)
        path = binding_path(run, call_id)
        value = {'session_id': session, 'actor': actor, 'step': at, 'trajectory': trajectory,
                 'tool_id': found['id'], 'input_sha256': fingerprint(args), 'call_id': call_id}
        path.parent.mkdir(parents=True, exist_ok=True)
        with (path.parent/'binding.lock').open('a+') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            for other in path.parent.glob('*.json'):
                saved = json.loads(other.read_text())
                if (saved.get('session_id') == session and saved.get('tool_id') == found['id']
                        and saved.get('call_id') != call_id):
                    raise ValueError('Native tool call was already bound to another delegation')
            if path.exists() and json.loads(path.read_text()) != value:
                raise ValueError('Native delegation binding conflict')
            write_json(path, value)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', required=True, type=Path)
    args = parser.parse_args()
    # Shared MCP protocol handling passes _meta only to a routing bridge.
    serve(Router(args.run_dir))


if __name__ == '__main__':
    main()
