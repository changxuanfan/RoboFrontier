"""Read-only, pinned-format native fork evidence. Never edits native databases."""
import hashlib
import json
from pathlib import Path
import sqlite3

from .driver import native_id


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
    value = [[r[0], r[1], r[2], bytes(r[3]).hex()] for r in rows]
    return hashlib.sha256(json.dumps(value, separators=(',', ':')).encode()).hexdigest()


def verify(home, parent, child, at, *, snapshot=None):
    source, copied = steps(home, parent), steps(home, child)
    if len(source) != at + 1 or len(copied) != at + 2:
        raise ValueError('Parent advanced or child ran before activation')
    if source[:at] != copied[:at]:
        raise ValueError('Native fork changed the inherited history')
    if (copied[at][2] != 6 or copied[at+1][1] != 101
            or tool_call(source[at]) != tool_call(copied[at])):
        raise ValueError('Native fork did not preserve and cancel the pending tool call')
    proof = {'source_thread_id': parent, 'source_ordinal': at,
            'source_sha256': digest(source[:at]), 'pending_tool_sha256':
            hashlib.sha256(json.dumps(tool_call(source[at]), sort_keys=True).encode()).hexdigest()}
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
        if verify(snapshot, parent, child, at) != proof:
            raise ValueError('Native fork changed while preserving its snapshot')
    return proof
