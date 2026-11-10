"""Bind host-generated delegation IDs to unique, unfinished native tool uses."""
from robofrontier.engines.claude.native_home import history_directory
import hashlib
import json
from pathlib import Path
import time

from robofrontier.engines.claude.provenance import history, transcript_rows
from robofrontier.runtime.setup import write_json
from robofrontier.runtime.store import RuntimeStore


def fingerprint(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def receipt_path(run, call_id):
    return Path(run)/'private/state/claude-tool-bindings'/(hashlib.sha256(call_id.encode()).hexdigest()+'.json')


def bind_delegate(run, actor, args, call_id, timeout=10):
    """Fail before submission if a generated ID cannot be tied to native history.

    MCP JSON-RPC IDs are intentionally not treated as native tool_use IDs.
    Matching requires exact original arguments and one unfinished native call.
    """
    run = Path(run)
    store = RuntimeStore(run/'private/state/runtime.sqlite')
    try:
        session = store.agent(actor)['thread_id']
        if actor != 'Controller' or not session or store.get('lifecycle') != 'running':
            raise ValueError('Automatic delegation requires the active Controller session')
    finally:
        store.close()
    path = receipt_path(run, call_id)
    expected = fingerprint(args)
    if path.exists():
        saved = json.loads(path.read_text())
        if (saved.get('session_id'), saved.get('actor'), saved.get('input_sha256')) != (session, actor, expected):
            raise ValueError('Delegation binding differs from the original request')
        return
    deadline = time.monotonic() + timeout
    while True:
        try:
            source = history(transcript_rows(history_directory(run), session), session)
        except ValueError:
            source = []  # Native transcript creation/flush can lag tool dispatch.
        finished = {item.get('tool_use_id') for row in source
                    for item in (row.get('message') or {}).get('content', [])
                    if isinstance(item, dict) and item.get('type') == 'tool_result'}
        matches = [(row['uuid'], item['id']) for row in source
                   for item in (row.get('message') or {}).get('content', [])
                   if isinstance(item, dict) and item.get('type') == 'tool_use'
                   and item.get('name') == 'mcp__robot__robot' and isinstance(item.get('id'), str)
                   and item['id'] not in finished and fingerprint(item.get('input')) == expected]
        if len(matches) > 1:
            raise ValueError('Ambiguous native delegation tool uses; no request submitted')
        if matches:
            row_uuid, native_id = matches[0]
            # One native use may never be rebound to another generated request.
            folder = path.parent
            folder.mkdir(parents=True, exist_ok=True)
            import fcntl
            with (folder/'bindings.lock').open('a+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                for other in folder.glob('*.json'):
                    bound = json.loads(other.read_text())
                    if (bound.get('session_id') == session and bound.get('tool_use_id') == native_id
                            and bound.get('call_id') != call_id):
                        raise ValueError('Native delegation tool use is already bound')
                write_json(path, {'schema': 'robofrontier.claude-tool-binding.v1', 'actor': actor,
                                  'session_id': session, 'call_id': call_id, 'row_uuid': row_uuid,
                                  'tool_use_id': native_id, 'input_sha256': expected})
                path.chmod(0o600)
            return
        if time.monotonic() >= deadline:
            raise ValueError('Native delegation tool use not recorded; no request submitted')
        time.sleep(.05)


def matches_binding(run, call_id, session, row, item):
    path = receipt_path(run, call_id)
    if not path.is_file(): return False
    saved = json.loads(path.read_text())
    return (saved.get('schema') == 'robofrontier.claude-tool-binding.v1'
            and saved.get('actor') == 'Controller' and saved.get('session_id') == session
            and saved.get('call_id') == call_id and saved.get('row_uuid') == row.get('uuid')
            and saved.get('tool_use_id') == item.get('id')
            and saved.get('input_sha256') == fingerprint(item.get('input')))
