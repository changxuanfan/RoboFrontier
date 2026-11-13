"""Read-only, pinned-format native fork evidence. Never edits native databases."""
import hashlib
import json
from pathlib import Path
import sqlite3

from .driver import native_id
from robofrontier.engines.common.identity import fingerprint

# Native step statuses and types of the pinned CLI's conversation database.
PENDING, CANCELED, FORK_NOTICE = 2, 6, 101
ROBOT_TOOL = 'mcp_robofrontier_robot'


def fields(data):
    """Decode protobuf wire fields without interpreting or rewriting unknown fields."""
    result, position = {}, 0
    def varint():
        nonlocal position
        value, shift = 0, 0
        while position < len(data) and shift < 70:
            byte = data[position]
            position += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value
            shift += 7
        raise ValueError('Malformed native protobuf')
    while position < len(data):
        tag = varint()
        number, wire = tag >> 3, tag & 7
        if wire == 0:
            value = varint()
        elif wire in (1, 2, 5):
            length = varint() if wire == 2 else 8 if wire == 1 else 4
            value = data[position:position+length]
            if len(value) != length:
                raise ValueError('Truncated native protobuf')
            position += length
        else:
            raise ValueError('Unsupported native wire format')
        if number in result:
            raise ValueError('Ambiguous repeated native field')
        result[number] = value
    return result


def steps(home, session):
    path = Path(home)/'conversations'/(native_id(session) + '.db')
    db = sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)
    try:
        rows = db.execute('SELECT idx,step_type,status,step_payload,metadata FROM steps ORDER BY idx').fetchall()
        if [r[0] for r in rows] != list(range(len(rows))):
            raise ValueError('Native history is not contiguous')
        return rows
    finally:
        db.close()


def tool_call(row):
    call = fields(fields(row[4])[4])
    return {'id': call[1].decode(), 'name': call[2].decode(), 'args': json.loads(call[3])}


def digest(rows):
    """Every compared column, so the saved digest proves what the live comparison checked."""
    value = [[r[0], r[1], r[2], bytes(r[3]).hex(), None if r[4] is None else bytes(r[4]).hex()] for r in rows]
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def pending(home, parent, binding):
    """The parent's last native step is still the delegate call the robot tool bound.

    The binding (robot_mcp.Router.bind) recorded the native tool ID and the hash of the
    arguments when the call arrived. A fork is taken from, and proven against, that
    same row: same step, same tool call, same arguments, still waiting."""
    rows, at = steps(home, parent), binding['step']
    if binding['session_id'] != parent or len(rows) != at + 1 or rows[at][2] != PENDING:
        raise ValueError('Bound delegate call is no longer the pending end of the parent history')
    call = tool_call(rows[at])
    arguments = dict(call['args'])
    arguments.pop('toolSummary', None)
    if (call['id'] != binding['tool_id'] or call['name'] != ROBOT_TOOL
            or fingerprint(arguments) != binding['input_sha256']):
        raise ValueError('Pending native call differs from the bound delegate call')
    return rows


def verify(home, parent, child, at, *, binding=None, snapshot=None):
    """Prove `child` is `parent` forked at its pending step `at`, before either moved on.

    With `binding` (every delegation), the pending step is also the delegate call the
    robot tool bound. The provider preflight forks a plain probe call and has none."""
    if binding is not None:
        if binding['step'] != at:
            raise ValueError('Fork step differs from the bound delegate call')
        source = pending(home, parent, binding)
    else:
        source = steps(home, parent)
        if len(source) != at + 1 or source[at][2] != PENDING:
            raise ValueError('Parent advanced or its forked call is not pending')
    copied = steps(home, child)
    if len(copied) != at + 2:
        raise ValueError('Child ran before activation')
    if source[:at] != copied[:at]:
        raise ValueError('Native fork changed the inherited history')
    if (copied[at][2] != CANCELED or copied[at+1][1] != FORK_NOTICE
            or tool_call(source[at]) != tool_call(copied[at])):
        raise ValueError('Native fork did not preserve and cancel the pending tool call')
    proof = {'source_thread_id': parent, 'source_ordinal': at,
            'source_sha256': digest(source[:at]), 'pending_tool_sha256':
            hashlib.sha256(json.dumps(tool_call(source[at]), sort_keys=True).encode()).hexdigest()}
    if binding is not None:
        proof.update(pending_tool_id=binding['tool_id'], pending_input_sha256=binding['input_sha256'],
                     pending_trajectory=binding['trajectory'])
    if snapshot is not None:
        destination = Path(snapshot)/'conversations'
        destination.mkdir(parents=True, exist_ok=False)
        for session in (parent, child):
            original = Path(home)/'conversations'/(native_id(session)+'.db')
            copied = destination/(session+'.db')
            with sqlite3.connect(original.as_uri()+'?mode=ro', uri=True) as before, sqlite3.connect(copied) as after:
                before.backup(after)
        # Make the sealed source boundary independently reviewable after the
        # live parent advances. A changed boundary never qualifies a fork.
        if verify(snapshot, parent, child, at, binding=binding) != proof:
            raise ValueError('Native fork changed while preserving its snapshot')
    return proof
