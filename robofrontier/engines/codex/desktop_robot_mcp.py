"""Robot tool for Codex Desktop sessions, as one global MCP stdio server.

Desktop threads are created by Codex Desktop, so the CLI host cannot attach its
dynamic `robot` tool to them. This server gives them the same role API. Codex
puts the calling thread in every tool call's `_meta`; the server maps that
thread to the role bound to it in a run's runtime database and uses that role's
connection. The model never names its role or sees a connection file.

Register it once in the Desktop Codex config (see `--print-config`); it needs
`default_tools_approval_mode = "approve"` because MCP calls otherwise wait for
a person.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
import sqlite3
import sys
import threading
import time
import uuid

from robofrontier.runtime.pipeline_client import client_call
from robofrontier.batch.metrics import host_event
from robofrontier.runtime.tool_errors import CallIdConflict, conflict_error, uncertain_error

ROOT = Path(__file__).resolve().parents[3]
SERVER = 'robofrontier_robot'
# One description for every engine's robot tool (engines/common/robot_tool.json).
TOOL = json.loads((Path(__file__).resolve().parents[1]/'common/robot_tool.json').read_text())
# Same policy surface as the CLI robot tool; administrative methods stay with Meta.
from robofrontier.runtime.robot_ops import POLICY_OPS, check_request
MAX_RUN_DEPTH = 6


def calling_thread(params):
    meta = params.get('_meta') or {}
    thread = meta.get('threadId') or (meta.get('x-codex-turn-metadata') or {}).get('thread_id')
    if not isinstance(thread, str) or not re.fullmatch(r'[0-9a-f-]{36}', thread):
        raise ValueError('No calling Codex thread; this tool only works in a session bound to a run role')
    return thread


def bound_role(database, thread):
    """Return the policy role bound to `thread` in one runtime DB, read-only, or None."""
    db = sqlite3.connect('file:%s?mode=ro' % database, uri=True, timeout=5)
    try:
        rows = db.execute('SELECT id, value FROM agents').fetchall()
    finally:
        db.close()
    matches = [(actor, json.loads(value)) for actor, value in rows if json.loads(value).get('thread_id') == thread]
    if len(matches) != 1: return None
    actor, agent = matches[0]
    if agent.get('kind') == 'manager': return None
    if agent.get('kind') == 'delegate' and agent.get('delegation_state') != 'active': return None
    return actor


class DesktopRobotBridge:
    def __init__(self, runs_root, invoke=client_call):
        self.runs_root = Path(runs_root).resolve()
        self.invoke = invoke
        self.cache = {}
        self.lock = threading.Lock()

    def databases(self):
        for depth in range(1, MAX_RUN_DEPTH + 1):
            yield from self.runs_root.glob('/'.join(['*'] * depth) + '/private/state/runtime.sqlite')

    def resolve(self, thread):
        """Map a thread to (run, actor, connection); the binding is rechecked on every call."""
        with self.lock:
            cached = self.cache.get(thread)
        candidates = [cached[0] / 'private/state/runtime.sqlite'] if cached else self.databases()
        for database in candidates:
            try:
                actor = bound_role(database, thread)
            except (sqlite3.Error, ValueError, OSError):
                continue
            if actor is None: continue
            run = database.parents[2]
            connection = run / 'private/state/connections' / (actor + '.json')
            config = json.loads(connection.read_text())
            if config.get('actor') != actor or config.get('run_id') != run.name:
                raise ValueError('Role connection does not match its run')
            with self.lock:
                self.cache[thread] = (run, actor)
            return run, actor, connection
        if cached:
            with self.lock:
                self.cache.pop(thread, None)
        raise ValueError('This session is not bound to an active policy role')

    def call(self, args, params):
        thread = calling_thread(params)
        run, actor, connection = self.resolve(thread)
        if not isinstance(args, dict) or set(args) - {'op', 'data', 'call_id', 'views'}:
            raise ValueError('Invalid robot arguments')
        op, data, views = args.get('op'), args.get('data'), args.get('views', [])
        check_request(op, data)
        if not isinstance(views, list) or not all(isinstance(v, str) and v for v in views):
            raise ValueError('views must be an array of camera names')
        # Like the CLI host: native call IDs are scoped by role and stable across retries.
        native = (params.get('_meta') or {}).get('callId')
        call_id = args.get('call_id') or (actor + '-' + native if isinstance(native, str) and native else uuid.uuid4().hex)
        call_id = re.sub(r'[^A-Za-z0-9_-]', '_', call_id)[:128]
        began = time.monotonic()
        host_event(run, 'robot_tool_started', actor=actor, op=op, call_id=call_id, transport='desktop_mcp')
        if op == 'public_image':
            result = public_images(run, data)
            result['content'].append({'type': 'text', 'text': json.dumps({'call_id': call_id})})
            host_event(run, 'robot_tool_completed', actor=actor, op=op, call_id=call_id, duration_s=time.monotonic()-began)
            return result
        if op in ('move', 'gripper', 'action_batch') and 'cameras' not in data:
            data = {**data, 'cameras': views}
        try:
            result = self.invoke(connection, op, data, call_id, log_call_id=False)
        except CallIdConflict:
            host_event(run, 'robot_tool_failed', actor=actor, op=op, call_id=call_id,
                       duration_s=time.monotonic()-began, error_code='CALL_ID_CONFLICT')
            return {'isError': True, 'content': [{'type': 'text', 'text': json.dumps(conflict_error(call_id), ensure_ascii=False)}]}
        except Exception:
            host_event(run, 'robot_tool_failed', actor=actor, op=op, call_id=call_id,
                       duration_s=time.monotonic()-began, error_code='TRANSPORT_UNCERTAIN')
            return {'isError': True, 'content': [{'type': 'text', 'text': json.dumps(uncertain_error(call_id), ensure_ascii=False)}]}
        result = {**result, 'call_id': call_id}
        host_event(run, 'robot_tool_completed', actor=actor, op=op, call_id=call_id, duration_s=time.monotonic()-began)
        content = [{'type': 'text', 'text': json.dumps(result, ensure_ascii=False, allow_nan=False)}]
        observation = result.get('observation') or (result.get('original_result') or {}).get('observation') or {}
        for view in views:
            content.append(view_image(run, view, observation.get('images', {}).get(view)))
        return {'content': content}


def view_image(run, view, name):
    """Return a selected observation image from this run's public directory only."""
    if not name: return {'type': 'text', 'text': 'Selected view unavailable: ' + view}
    try:
        image = Path(name).resolve()
        if not image.is_relative_to((run / 'public').resolve()) or not image.is_file():
            raise ValueError('Observation image is outside this run public directory')
        data = image.read_bytes()
        mime = 'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else None
        if mime is None: raise ValueError('Observation is not a PNG or JPEG image')
    except (OSError, ValueError, TypeError, RuntimeError):
        # The action already ran; keep its result even when the image cannot be returned.
        return {'type': 'text', 'text': 'Selected view could not be loaded: ' + view}
    return {'type': 'image', 'data': base64.b64encode(data).decode('ascii'), 'mimeType': mime}


def public_images(run, data):
    """Return only reference images explicitly listed in the frozen public task."""
    if set(data) != {'names'} or not isinstance(data['names'], list) or not data['names']:
        raise ValueError('Provide names from the public task initial_reference_images')
    if len(data['names']) > 8 or len(set(data['names'])) != len(data['names']):
        raise ValueError('Select at most eight distinct public reference images')
    root = (run / 'public/inputs').resolve()
    task = json.loads((root / 'task.json').read_text())
    allowed = set(task.get('initial_reference_images', []))
    if task.get('robot_layout_image'): allowed.add(task['robot_layout_image'])
    target = task.get('target')
    if isinstance(target, dict) and isinstance(target.get('reference_image'), str): allowed.add(target['reference_image'])
    content = []
    for name in data['names']:
        if not isinstance(name, str) or name not in allowed: raise ValueError('Image is not in the frozen public task')
        path = ((run / name) if name.startswith('public/inputs/') else (root / name)).resolve()
        if not path.is_relative_to(root) or not path.is_file(): raise ValueError('Public reference image is unavailable')
        data_bytes = path.read_bytes()
        if not data_bytes.startswith(b'\x89PNG\r\n\x1a\n'): raise ValueError('Public reference is not a PNG image')
        content.append({'type': 'text', 'text': 'Public reference: ' + name})
        content.append({'type': 'image', 'data': base64.b64encode(data_bytes).decode('ascii'), 'mimeType': 'image/png'})
    return {'content': content}


def handle(request, bridge):
    method, params = request.get('method'), request.get('params') or {}
    if method == 'initialize':
        return {'protocolVersion': params.get('protocolVersion', '2025-06-18'), 'capabilities': {'tools': {}},
                'serverInfo': {'name': SERVER, 'version': '0.1.0'}}
    if method == 'ping': return {}
    if method == 'tools/list': return {'tools': [TOOL]}
    if method == 'tools/call':
        if params.get('name') != 'robot': raise ValueError('Unknown tool')
        return bridge.call(params.get('arguments'), params)
    raise ValueError('Unknown MCP method')


def serve(bridge):
    lock = threading.Lock()
    def reply(request):
        if 'id' not in request: return
        try:
            response = {'jsonrpc': '2.0', 'id': request['id'], 'result': handle(request, bridge)}
        except Exception as error:
            response = {'jsonrpc': '2.0', 'id': request['id'], 'error': {'code': -32603, 'message': str(error)}}
        with lock: print(json.dumps(response, ensure_ascii=False), flush=True)
    with ThreadPoolExecutor(max_workers=8) as pool:
        for line in sys.stdin:
            try:
                request = json.loads(line)
            except json.JSONDecodeError:
                with lock: print(json.dumps({'jsonrpc': '2.0', 'id': None, 'error': {'code': -32700, 'message': 'Parse error'}}), flush=True)
                continue
            if isinstance(request, dict): pool.submit(reply, request)


def config_snippet(python=sys.executable, runs_root=ROOT / 'runs'):
    return '\n'.join(['[mcp_servers.%s]' % SERVER, 'command = %s' % json.dumps(str(Path(python).absolute())),
                      'args = %s' % json.dumps(['-m', 'robofrontier.engines.codex.desktop_robot_mcp', '--runs-root', str(Path(runs_root).resolve())]),
                      'env = { PYTHONPATH = %s }' % json.dumps(str(ROOT)),
                      'default_tools_approval_mode = "approve"', ''])


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--runs-root', type=Path, default=ROOT / 'runs')
    parser.add_argument('--print-config', action='store_true', help='Print the Desktop config.toml entry and exit')
    args = parser.parse_args()
    if args.print_config: print(config_snippet(runs_root=args.runs_root), end=''); return
    serve(DesktopRobotBridge(args.runs_root))


if __name__ == '__main__': main()
