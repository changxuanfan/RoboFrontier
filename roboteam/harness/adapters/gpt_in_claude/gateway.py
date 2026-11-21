"""Messages adapter with explicitly selected OpenAI authentication.

Only the model transport is translated. Claude Code owns sessions, tools and forks.
No credential fallback, external relay, prompt logging, or implicit model substitution.
"""

import argparse
import base64
import hashlib
import json
import os
import secrets
import sqlite3
import ssl
import sys
import threading
import time
import traceback
import uuid
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlsplit

if not __package__:  # Run as a file, without installing the package: import from this checkout.
    sys.path[0] = str(Path(__file__).resolve().parents[4])
from roboteam.harness.adapters.gpt_in_claude.auth import CredentialStore
from roboteam.harness.adapters.gpt_in_claude.websocket import (
    Admission,
    ProtocolError,
    UpstreamError,
    WebSocketTransport,
    canonical,
)

MODEL = 'gpt-6.1-sol'
OPAQUE = 'roboteam_responses_v1:'


class APIKeyStore:
    """Read the dedicated host-only key file; never fall back to OAuth or shell keys."""

    def __init__(self, path):
        self.path = Path(path)

    def access_token(self):
        value = self.path.read_text(encoding='utf-8-sig').strip()
        if not value or value == 'PASTE_OPENAI_API_KEY_HERE' or any(char.isspace() for char in value):
            raise ValueError('API key file must contain one key, without placeholder text')
        return value


class NativeControls:
    """Prove synthetic resume controls from host-owned, session-bound transcripts."""

    def __init__(self, index):
        index = Path(index)
        if index.is_symlink() or (os.name != 'nt' and index.stat().st_mode & 0o077):
            raise ProtocolError('Native session index must be private and not a symlink')
        self.paths = json.loads(index.read_text())
        self.cache = {}
        self.lock = threading.RLock()

    def _discover(self, session, lineage):
        if session in self.paths:
            return Path(self.paths[session])
        if len(lineage) < 2:
            return None
        parent = lineage[1]
        parent_path = self._discover(parent, lineage[1:])
        if parent_path is None:
            return None
        path = parent_path.with_name(session + '.jsonl')
        if not path.is_file() or path.is_symlink():
            return None
        config = parent_path.parents[2]
        if parent_path.parents[1].name != 'projects':
            raise ProtocolError('Native fork discovery requires the registered run layout')
        if (
            config.name != 'config'
            or config.parent.name != 'harness'
            or config.parent.parent.name != 'private'
        ):
            raise ProtocolError('Native fork discovery requires the registered run layout')
        run = config.parent.parent.parent
        claim_dir = run / 'private/claude-forks'
        matches = []
        for claim_path in claim_dir.glob('*.json'):
            if claim_path.is_symlink() or (os.name != 'nt' and claim_path.stat().st_mode & 0o077):
                raise ProtocolError('Native fork claim must be private and not a symlink')
            claim = json.loads(claim_path.read_text())
            if claim.get('child_session') == session:
                matches.append((claim_path, claim))
        if len(matches) != 1:
            return None
        claim_path, claim = matches[0]
        if (
            claim.get('status') not in ('claimed', 'history_verified_gated')
            or claim.get('source_session') != parent
            or claim.get('parent_session') != parent
            or claim_path.stem != claim.get('actor')
            or claim.get('tool_permissions') != 'gated'
        ):
            raise ProtocolError('Native fork claim does not authorize this session')
        from roboteam.harness.claude.systems.provenance import (
            copied_history_length,
            first_input,
            history,
            transcript_rows,
        )

        deadline = time.monotonic() + 3
        while True:
            try:
                current = history(transcript_rows(config, parent), parent)
                copied = history(transcript_rows(config, session), session)
                # A parent may have advanced after creating the claim. Locate precisely
                # the pinned prefix, using the original claim's JSON digest format.
                prefix = hashlib.sha256(b'[')
                source = None
                for index, row in enumerate(current):
                    if index:
                        prefix.update(b', ')
                    prefix.update(json.dumps(row, sort_keys=True).encode())
                    candidate = prefix.copy()
                    candidate.update(b']')
                    if candidate.hexdigest() == claim.get('parent_history_sha256'):
                        source = current[: index + 1]
                        break
                if source is None:
                    raise ValueError('Claimed source prefix is unavailable')
                copied_length = copied_history_length(source, copied)
                if {row['uuid'] for row in copied[copied_length:]} & {row['uuid'] for row in current}:
                    raise ValueError('Child copied parent history beyond the claimed fork point')
                prompt = first_input(copied[copied_length:])
                if prompt is None or hashlib.sha256(prompt.encode()).hexdigest() != claim.get(
                    'first_input_sha256'
                ):
                    raise ValueError('Native child input differs from its host claim')
                break
            except ValueError as error:
                # Native CLI transcript writes can lag its first HTTP request. Wait
                # for the complete witness; no request is released before it verifies.
                if time.monotonic() >= deadline:
                    raise ProtocolError(
                        'Native fork provenance could not be verified: ' + str(error)
                    ) from None
                time.sleep(0.05)
        self.paths[session] = str(path)
        return path

    def confirms(self, session, occurrence, lineage=None):
        if str(uuid.UUID(session)) != session:
            raise ProtocolError('Invalid native session identity')
        with self.lock:
            path = self._discover(session, lineage or [session])
            if path is None:
                return False
            if path.is_symlink() or path.name != session + '.jsonl':
                raise ProtocolError('Native session path identity mismatch')
            deadline = time.monotonic() + 3
            while True:
                # Resume may rewrite a transcript in place, retaining its inode
                # and growing beyond the previous offset. Re-scan the witness
                # rather than trusting stale offsets from before that rewrite.
                count = 0
                with path.open('rb') as stream:
                    while True:
                        line = stream.readline()
                        if not line or not line.endswith(b'\n'):
                            break
                        row = json.loads(line)
                        message = row.get('message') or {}
                        if (
                            row.get('type') == 'assistant'
                            and row.get('sessionId') == session
                            and message.get('model') == '<synthetic>'
                            and row.get('isApiErrorMessage') is False
                            and message.get('content') == [{'type': 'text', 'text': 'No response requested.'}]
                        ):
                            count += 1
                    self.cache[session] = (path.stat().st_ino, stream.tell(), count)
                if occurrence < count:
                    return True
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.05)


class InputHistory(list):
    """Incremental identity of the replayed input, including original argument strings."""

    def __init__(self, session_id=None, fork_source=None):
        super().__init__()
        self.prefix = hashlib.sha256()
        self.replayed_ids = []
        self.replay_prefix_changes = []
        self.session_id = session_id
        self.fork_source = fork_source
        self.native_controls = []
        self.native_defaults = []

    def append(self, item):
        super().append(item)
        self.prefix.update(canonical(item))
        self.prefix.update(b'\n')

    def extend(self, items):
        for item in items:
            self.append(item)


def normalized_blocks(blocks):
    """Ignore client bookkeeping, but never normalize text, tool values or opaque data."""
    result = []
    for block in blocks:
        kind = block.get('type')
        fields = {
            'text': ('type', 'text'),
            'tool_use': ('type', 'id', 'name', 'input'),
            'redacted_thinking': ('type', 'data'),
            'thinking': ('type', 'thinking', 'signature'),
        }.get(kind)
        if fields is None:
            raise ProtocolError('Unsupported assistant replay block: ' + str(kind))
        item = {key: block[key] for key in fields if key in block}
        if kind == 'text' and result and result[-1]['type'] == 'text':
            result[-1]['text'] += item['text']
        else:
            result.append(item)
    return result


def same_projection(left, right):
    # Native JavaScript may spell 1.0 as 1; booleans and changed numeric values
    # must remain distinct. The original argument spelling is restored separately.
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return left == right
    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return left.keys() == right.keys() and all(same_projection(left[key], right[key]) for key in left)
    if isinstance(left, list):
        return len(left) == len(right) and all(same_projection(a, b) for a, b in zip(left, right))
    return left == right


def projection_anchor(block):
    identity = {key: block[key] for key in ('type', 'id', 'name')} if block['type'] == 'tool_use' else block
    return hashlib.sha256(canonical(identity)).hexdigest()


def schema_defaults(schema):
    """Keep only default declarations from the original, advertised tool schema."""
    if not isinstance(schema, dict):
        return {}
    tree = {key: schema[key] for key in ('default',) if key in schema}
    properties = {
        key: sub for key, value in schema.get('properties', {}).items() if (sub := schema_defaults(value))
    }
    if properties:
        tree['properties'] = properties
    items = schema_defaults(schema.get('items'))
    if items:
        tree['items'] = items
    return tree


def same_arguments(original, native, defaults):
    if isinstance(original, dict) and isinstance(native, dict):
        if not original.keys() <= native.keys():
            return False
        properties = defaults.get('properties', {})
        return all(
            same_arguments(original[key], value, properties.get(key, {}))
            if key in original
            else 'default' in properties.get(key, {}) and same_projection(value, properties[key]['default'])
            for key, value in native.items()
        )
    if isinstance(original, list) and isinstance(native, list):
        return len(original) == len(native) and all(
            same_arguments(a, b, defaults.get('items', {})) for a, b in zip(original, native)
        )
    return same_projection(original, native)


def same_client_projection(original, native, defaults):
    if len(original) != len(native):
        return False
    for index, (a, b) in enumerate(zip(original, native)):
        if a.get('type') == 'tool_use' and b.get('type') == 'tool_use':
            if not same_projection(
                {k: v for k, v in a.items() if k != 'input'}, {k: v for k, v in b.items() if k != 'input'}
            ):
                return False
            if not same_arguments(
                a.get('input'), b.get('input'), defaults[index] if index < len(defaults) else {}
            ):
                return False
        elif not same_projection(a, b):
            return False
    return True


class ReplayStore:
    """Private durable response state, not a prompt log or a model-visible side channel."""

    def __init__(self, path, native_session_index=None):
        self.path = Path(path)
        self.native_controls = NativeControls(native_session_index) if native_session_index else None
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.is_symlink():
            raise ProtocolError('Replay database must not be a symlink')
        self.path.touch(mode=0o600, exist_ok=True)
        if os.name != 'nt' and self.path.stat().st_mode & 0o077:
            raise ProtocolError('Replay database must be owner-only')
        with self.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
            db.execute(
                'CREATE TABLE IF NOT EXISTS responses ('
                'response_id TEXT PRIMARY KEY, input_digest TEXT NOT NULL, '
                'projection TEXT NOT NULL, output TEXT NOT NULL, anchor TEXT NOT NULL, '
                "origin_session TEXT, defaults TEXT NOT NULL DEFAULT '[]')"
            )
            db.execute('CREATE INDEX IF NOT EXISTS responses_input ON responses(input_digest)')
            db.execute('CREATE INDEX IF NOT EXISTS responses_anchor ON responses(anchor)')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (session_id TEXT PRIMARY KEY,parent_id TEXT)')

    def lineage(self, session, parent=None):
        if session is None:
            if parent is not None:
                raise ProtocolError('Fork source requires a native session identity')
            return [None]
        with self.connect() as db:
            row = db.execute('SELECT parent_id FROM sessions WHERE session_id=?', (session,)).fetchone()
            if row is None:
                db.execute('INSERT INTO sessions VALUES (?,?)', (session, parent))
            elif parent is not None and row[0] != parent:
                raise ProtocolError('Native fork ancestry cannot be rebound')
            result = []
            current = session
            while current is not None:
                if current in result or len(result) >= 128:
                    raise ProtocolError('Invalid native fork ancestry')
                result.append(current)
                row = db.execute('SELECT parent_id FROM sessions WHERE session_id=?', (current,)).fetchone()
                current = row[0] if row else None
        return result

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=30)
        try:
            with db:
                yield db
        finally:
            db.close()

    def remember(self, request, response, message):
        history = request['input']
        if not isinstance(history, InputHistory):
            original = history
            history = InputHistory()
            history.extend(original)
        projection = normalized_blocks(message['content'])
        schemas = {
            tool['name']: schema_defaults(tool.get('parameters', {}))
            for group in request.get('tools', [])
            for tool in group.get('tools', [])
        }
        defaults = [
            schemas.get(block.get('name'), {}) if block['type'] == 'tool_use' else {} for block in projection
        ]
        value = (
            response['id'],
            history.prefix.hexdigest(),
            canonical(projection).decode(),
            canonical(response['output']).decode(),
            projection_anchor(projection[0]),
            history.session_id,
            canonical(defaults).decode(),
        )
        self.lineage(history.session_id, history.fork_source)
        with self.connect() as db:
            old = db.execute(
                'SELECT response_id,input_digest,projection,output,anchor,origin_session,defaults FROM responses WHERE response_id=?',
                (response['id'],),
            ).fetchone()
            if old is not None and old != value:
                raise ProtocolError('A response identity was reused for different replay state')
            db.execute(
                'INSERT OR IGNORE INTO responses (response_id,input_digest,projection,output,anchor,origin_session,defaults) VALUES (?,?,?,?,?,?,?)',
                value,
            )

    def restore(self, history, blocks, offset):
        matches = []
        anchor = projection_anchor(blocks[offset])
        lineage = self.lineage(history.session_id, history.fork_source)
        for column, key in (('input_digest', history.prefix.hexdigest()), ('anchor', anchor)):
            for session in lineage:
                with self.connect() as db:
                    candidates = db.execute(
                        'SELECT response_id,projection,output,input_digest,defaults FROM responses WHERE '
                        + column
                        + '=? AND origin_session IS ?',
                        (key, session),
                    ).fetchall()
                for identity, projection, output, digest, defaults in candidates:
                    expected = json.loads(projection)
                    if expected and same_client_projection(
                        expected, blocks[offset : offset + len(expected)], json.loads(defaults)
                    ):
                        matches.append((identity, expected, output, digest))
                if matches:
                    break
            if matches:
                break
        if not matches:
            if (
                self.native_controls is None
                and len(lineage) > 1
                and history.replayed_ids
                and blocks[offset:] == [{'type': 'text', 'text': 'No response requested.'}]
            ):
                history.append({'role': 'assistant', 'content': 'No response requested.'})
                history.native_controls.append('fork_no_response')
                return offset + 1
            if (
                self.native_controls is not None
                and history.session_id is not None
                and blocks[offset:] == [{'type': 'text', 'text': 'No response requested.'}]
            ):
                with self.connect() as db:
                    known = db.execute(
                        'SELECT 1 FROM responses WHERE origin_session IN (%s) LIMIT 1'
                        % ','.join('?' for _ in lineage),
                        lineage,
                    ).fetchone()
                # A registered root may have a native control from a cancelled
                # first turn, before any provider output ever existed. Its
                # synthetic transcript witness is still mandatory. Forks also
                # require an existing provider lineage and the host claim.
                if (known or len(lineage) == 1) and self.native_controls.confirms(
                    history.session_id, history.native_controls.count('resume_no_response'), lineage
                ):
                    history.append({'role': 'assistant', 'content': 'No response requested.'})
                    history.native_controls.append('resume_no_response')
                    return offset + 1
            error = ProtocolError(
                'Original Responses output is unavailable or assistant history changed; '
                'the history cannot be reconstructed losslessly'
            )
            error.replay_context = {
                'native_session': history.session_id,
                'fork_source': history.fork_source,
                'offset': offset,
                'block_types': [b.get('type') for b in blocks],
                'block_hashes': [hashlib.sha256(canonical(b)).hexdigest() for b in blocks],
                'native_controls_restored': len(history.native_controls),
                'native_witness_count': self.native_controls.cache.get(
                    history.session_id, (None, None, None)
                )[2]
                if self.native_controls
                else None,
                'candidate_count': len(candidates),
                'candidate_types': [[b.get('type') for b in json.loads(row[1])] for row in candidates[:8]],
            }
            raise error
        if len({row[2] for row in matches}) != 1:
            raise ProtocolError('Ambiguous original response for this assistant history')
        identity, expected, output, digest = matches[0]
        if not same_projection(expected, blocks[offset : offset + len(expected)]):
            history.native_defaults.append(identity)
        if digest != history.prefix.hexdigest():
            history.replay_prefix_changes.append(identity)
        history.extend(json.loads(output))
        history.replayed_ids.append(identity)
        return offset + len(expected)


def request_fingerprints(request):
    """Local prefix comparisons without persisting prompts, images or tool bodies."""

    def encoded(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':')).encode()

    prefix = hashlib.sha256()
    checkpoints = {}
    items = request.get('input', [])
    for count, item in enumerate(items, 1):
        prefix.update(encoded(item))
        prefix.update(b'\n')
        if count in (1, 2, 4, 8) or count % 16 == 0 or count == len(items):
            checkpoints[str(count)] = prefix.hexdigest()
    return {
        'instructions_sha256': hashlib.sha256(encoded(request.get('instructions'))).hexdigest(),
        'tools_sha256': hashlib.sha256(encoded(request.get('tools', []))).hexdigest(),
        'input_prefix_sha256': checkpoints,
        'cache_mode': 'implicit_provider_default',
        'reasoning_effort': request['reasoning']['effort'],
    }


def response_metadata(result):
    """Allow only documented diagnostic fields; never copy provider payload bodies to logs."""
    diagnostics = result.get('prompt_cache_diagnostics')
    transformations = result.get('input_transformations')
    usage = result.get('usage') or {}
    return {
        'response_model': result['model'],
        'response_id': result['id'],
        'effective_reasoning': result.get('reasoning'),
        'effective_cache_options': result.get('prompt_cache_options'),
        'cache_diagnostics': {
            key: diagnostics[key]
            for key in ('type', 'reason', 'comparison_reusable_tokens', 'cache_missed_tokens')
            if key in diagnostics
        }
        if isinstance(diagnostics, dict)
        else None,
        'input_transformations': [
            {key: item[key] for key in ('id', 'type', 'action', 'reason') if key in item}
            for item in transformations
        ]
        if isinstance(transformations, list)
        else None,
        'service_tier': result.get('service_tier'),
        'usage': {
            key: usage[key]
            for key in (
                'input_tokens',
                'output_tokens',
                'total_tokens',
                'input_tokens_details',
                'output_tokens_details',
            )
            if key in usage
        },
    }


def parts(value):
    if isinstance(value, str):
        return [{'type': 'input_text', 'text': value}]
    if not isinstance(value, list):
        raise ProtocolError('Expected a text or image content array')
    output = []
    for block in value:
        if block['type'] == 'text':
            output.append({'type': 'input_text', 'text': block['text']})
        elif block['type'] == 'image':
            source = block['source']
            if source.get('type') == 'base64' and source.get('media_type', '').startswith('image/'):
                url = 'data:' + source['media_type'] + ';base64,' + source['data']
            elif source.get('type') == 'url' and urlsplit(source.get('url', '')).scheme == 'https':
                url = source['url']
            else:
                raise ProtocolError('Unsupported image source')
            output.append({'type': 'input_image', 'image_url': url})
        else:
            raise ProtocolError('Unsupported content block: ' + str(block.get('type')))
    return output


def to_responses(payload, effort='high', replay=None, session_id=None, fork_source=None):
    inputs = InputHistory(session_id, fork_source)
    for message in payload.get('messages', []):
        role = message.get('role')
        if role not in ('user', 'assistant', 'system', 'developer'):
            raise ProtocolError('Unsupported message role')
        if role == 'system':
            role = 'developer'
        content = message['content']
        blocks = [{'type': 'text', 'text': content}] if isinstance(content, str) else content
        if role == 'assistant':
            if replay is None:
                raise ProtocolError('Assistant history requires original output replay state')
            blocks = normalized_blocks(blocks)
            offset = 0
            while offset < len(blocks):
                offset = replay.restore(inputs, blocks, offset)
            continue
        pending = []

        def flush():
            if pending:
                if role == 'developer':
                    if any(p['type'] != 'text' for p in pending):
                        raise ProtocolError(
                            'Assistant or developer message contains unsupported non-text content'
                        )
                    inputs.append({'role': role, 'content': ''.join(p['text'] for p in pending)})
                else:
                    inputs.append({'role': role, 'content': parts(pending)})
                pending.clear()

        for block in blocks:
            kind = block.get('type')
            if kind in ('text', 'image'):
                pending.append(block)
                continue
            flush()
            if kind == 'tool_result' and role == 'user':
                output = parts(block.get('content', ''))
                if block.get('is_error'):
                    output.insert(
                        0,
                        {
                            'type': 'input_text',
                            'text': 'Tool execution failed. The following is its error result.',
                        },
                    )
                inputs.append(
                    {'type': 'function_call_output', 'call_id': block['tool_use_id'], 'output': output}
                )
            else:
                raise ProtocolError('Unsupported message content: ' + str(kind))
        flush()
    request = {
        'model': MODEL,
        'input': inputs,
        'stream': True,
        'store': False,
        'include': ['reasoning.encrypted_content'],
        'reasoning': {'effort': effort},
    }
    if inputs.replayed_ids:
        request['prompt_cache_options'] = {'comparison_response_id': inputs.replayed_ids[-1]}
    system = payload.get('system')
    if system:
        if isinstance(system, str):
            request['instructions'] = system
        elif isinstance(system, list) and all(b.get('type') == 'text' for b in system):
            request['instructions'] = '\n'.join(b['text'] for b in system)
        else:
            raise ProtocolError('Unsupported system prompt format')
    definitions = []
    for tool in payload.get('tools', []):
        if tool.get('type') not in (None, 'custom'):
            raise ProtocolError('Hosted Anthropic tools are not supported')
        definitions.append(
            {
                'type': 'function',
                'name': tool['name'],
                'description': tool.get('description', ''),
                'parameters': tool['input_schema'],
                'strict': False,
            }
        )
    if definitions:
        request['tools'] = [
            {
                'type': 'namespace',
                'name': 'robot_team',
                'description': 'Tools executed by the native Claude Code harness.',
                'tools': definitions,
            }
        ]
    choice = payload.get('tool_choice', {'type': 'auto'})
    if choice['type'] in ('auto', 'none'):
        request['tool_choice'] = choice['type']
    elif choice['type'] == 'any':
        request['tool_choice'] = 'required'
    elif choice['type'] == 'tool':
        selected = [tool for tool in definitions if tool['name'] == choice['name']]
        if len(selected) != 1:
            raise ProtocolError('Forced tool was not defined')
        request['tools'][0]['tools'] = selected
        request['tool_choice'] = 'required'
    else:
        raise ProtocolError('Unsupported tool choice')
    if choice.get('disable_parallel_tool_use'):
        request['parallel_tool_calls'] = False
    # The official plan-use route rejects max_output_tokens and sampling controls.
    # Keep that policy explicit; no silent endpoint or billing fallback is permitted.
    for field in ('temperature', 'top_p', 'top_k', 'stop_sequences'):
        if payload.get(field) not in (None, []):
            raise ProtocolError('Sampling or stop overrides are not supported by ChatGPT plan use: ' + field)
    return request


def to_message(response):
    content = []
    for item in response.get('output', []):
        kind = item['type']
        if kind == 'message':
            for block in item.get('content', []):
                if block['type'] == 'output_text':
                    content.append({'type': 'text', 'text': block['text']})
                elif block['type'] == 'refusal':
                    content.append({'type': 'text', 'text': block['refusal']})
                else:
                    raise ProtocolError('Unsupported output content: ' + block['type'])
        elif kind == 'function_call':
            arguments = json.loads(item['arguments'])
            if not isinstance(arguments, dict):
                raise ProtocolError('Tool arguments must be a JSON object')
            content.append(
                {'type': 'tool_use', 'id': item['call_id'], 'name': item['name'], 'input': arguments}
            )
        elif kind == 'reasoning':
            if not item.get('encrypted_content'):
                raise ProtocolError('Upstream omitted requested encrypted reasoning')
            encoded = base64.b64encode(json.dumps(item, separators=(',', ':')).encode()).decode()
            content.append({'type': 'redacted_thinking', 'data': OPAQUE + encoded})
        else:
            raise ProtocolError('Unsupported Responses output item: ' + kind)
    if not content:
        raise ProtocolError('Completed response contained no output')
    content = normalized_blocks(content)
    usage = response.get('usage') or {}
    cached = (usage.get('input_tokens_details') or {}).get('cached_tokens', 0)
    written = (usage.get('input_tokens_details') or {}).get('cache_write_tokens', 0)
    return {
        'id': response['id'],
        'type': 'message',
        'role': 'assistant',
        'model': MODEL,
        'content': content,
        'stop_reason': 'tool_use' if any(b['type'] == 'tool_use' for b in content) else 'end_turn',
        'stop_sequence': None,
        'usage': {
            'input_tokens': usage.get('input_tokens', 0) - cached - written,
            'cache_read_input_tokens': cached,
            'cache_creation_input_tokens': written,
            'output_tokens': usage.get('output_tokens', 0),
        },
    }


def message_events(message, original_output=None):
    arguments = {
        item['call_id']: item['arguments']
        for item in (original_output or [])
        if item.get('type') == 'function_call'
    }
    yield (
        'message_start',
        {
            'type': 'message_start',
            'message': {
                **message,
                'content': [],
                'stop_reason': None,
                'usage': {**message['usage'], 'output_tokens': 0},
            },
        },
    )
    for index, block in enumerate(message['content']):
        if block['type'] == 'tool_use':
            if block['id'] not in arguments:
                raise ProtocolError('Original tool argument string is required for SSE delivery')
            empty, delta = (
                {**block, 'input': {}},
                {'type': 'input_json_delta', 'partial_json': arguments[block['id']]},
            )
        elif block['type'] == 'text':
            empty, delta = {'type': 'text', 'text': ''}, {'type': 'text_delta', 'text': block['text']}
        else:
            empty, delta = block, None
        yield 'content_block_start', {'type': 'content_block_start', 'index': index, 'content_block': empty}
        if delta:
            yield 'content_block_delta', {'type': 'content_block_delta', 'index': index, 'delta': delta}
        yield 'content_block_stop', {'type': 'content_block_stop', 'index': index}
    yield (
        'message_delta',
        {
            'type': 'message_delta',
            'delta': {'stop_reason': message['stop_reason'], 'stop_sequence': None},
            'usage': {'output_tokens': message['usage']['output_tokens']},
        },
    )
    yield 'message_stop', {'type': 'message_stop'}


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(
        self,
        address,
        credential_file,
        key,
        log=None,
        auth_mode='chatgpt_plan',
        replay_file=None,
        native_session_index=None,
        tokens_per_minute=None,
    ):
        if auth_mode not in ('chatgpt_plan', 'openai_api_key'):
            raise ValueError('Choose chatgpt_plan or openai_api_key explicitly')
        self.auth_mode = auth_mode
        self.store = (
            APIKeyStore(credential_file)
            if auth_mode == 'openai_api_key'
            else CredentialStore(credential_file)
        )
        if auth_mode == 'openai_api_key':
            self.store.access_token()
        super().__init__(address, Handler)
        self.replay = ReplayStore(
            replay_file or Path(credential_file).with_name('response-replay.sqlite'), native_session_index
        )
        self.key = key
        self.log = log
        self.lock = threading.Lock()
        self.quota_file = Path(log).with_name(auth_mode.replace('_', '-') + '-quota.json') if log else None
        self.transport = WebSocketTransport(
            self.store, admission=Admission(tokens_per_minute) if tokens_per_minute else None
        )

    def server_close(self):
        self.transport.close()
        super().server_close()

    def current_quota(self):
        if self.quota_file and self.quota_file.exists():
            return json.loads(self.quota_file.read_text())
        return None

    def hold_quota(self, code, param=None):
        if self.quota_file:
            from roboteam.harness.adapters.gpt_in_claude.auth import atomic_json

            with self.lock:
                if not self.quota_file.exists():
                    atomic_json(
                        self.quota_file,
                        {
                            'code': code,
                            'param': param,
                            'detected_at': time.time(),
                            'reset_at': None,
                            'auth': self.auth_mode,
                            'action': 'Review provider usage and billing before releasing this hold.',
                        },
                    )

    def audit(self, record):
        if self.log:
            with self.lock, Path(self.log).open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record) + '\n')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def reply(self, status, document, headers=None):
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        # Rejected paths/authentication may leave an unread request body. It must
        # never become the next HTTP request on a reused native-client socket.
        self.send_header('Connection', 'close')
        self.close_connection = True
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def authorized(self):
        key = self.headers.get('x-api-key') or self.headers.get('Authorization', '').removeprefix('Bearer ')
        return secrets.compare_digest(key, self.server.key)

    def do_HEAD(self):
        self.send_response(200 if urlsplit(self.path).path == '/api/hello' else 404)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def do_GET(self):
        if urlsplit(self.path).path == '/health':
            quota = self.server.current_quota()
            return self.reply(
                200,
                {
                    'ready': True,
                    'model': MODEL,
                    'auth': self.server.auth_mode,
                    'inference_verified': False,
                    'replay_policy': 'exact-output-v2',
                    'transport_revision': 'websocket-incremental-v4',
                    'inference_blocked': (quota or {}).get('code'),
                },
            )
        self.reply(404, {'error': {'type': 'not_found_error', 'message': 'Endpoint not implemented'}})

    def do_POST(self):
        if not self.authorized():
            return self.reply(
                401,
                {
                    'type': 'error',
                    'error': {'type': 'authentication_error', 'message': 'Invalid local gateway key'},
                },
            )
        streaming = False
        done = threading.Event()
        write_lock = threading.Lock()
        record = {
            'at': time.time(),
            'request_id': secrets.token_hex(16),
            'auth': getattr(self.server, 'auth_mode', 'chatgpt_plan'),
            'model': MODEL,
            'native_session': self.headers.get('X-RoboTeam-Session'),
            'fork_source': self.headers.get('X-RoboTeam-Fork-Source'),
        }

        def send(event, data):
            with write_lock:
                self.wfile.write(('event: ' + event + '\ndata: ' + json.dumps(data) + '\n\n').encode())
                self.wfile.flush()

        def ping():
            while not done.wait(10):
                try:
                    send('ping', {'type': 'ping'})
                except (BrokenPipeError, ConnectionResetError, OSError):
                    done.set()
                    # Only the reader thread closes HTTPResponse/HTTPSConnection;
                    # closing it here races with its chunk parser.

        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= 256 * 1024 * 1024:
                raise ProtocolError('Invalid request size')
            body = self.rfile.read(length)
            if len(body) != length:
                raise ConnectionResetError('Client disconnected during request upload')
            if urlsplit(self.path).path != '/v1/messages':
                record.update(
                    http=404,
                    completed=False,
                    failure='unsupported_endpoint',
                    token_count_request=urlsplit(self.path).path == '/v1/messages/count_tokens',
                )
                return self.reply(
                    404,
                    {
                        'type': 'error',
                        'error': {'type': 'not_found_error', 'message': 'Endpoint not implemented'},
                    },
                )
            quota = self.server.current_quota()
            if quota:
                record.update(
                    http=429,
                    completed=False,
                    failure='quota_hold',
                    error_code=quota['code'],
                    upstream_sent=False,
                )
                return self.reply(
                    429,
                    {
                        'type': 'error',
                        'error': {
                            'type': 'rate_limit_error',
                            'code': quota['code'],
                            'message': quota['code']
                            + ': usage is paused; review provider usage and billing. No reset time was provided.',
                        },
                    },
                    {'x-should-retry': 'false'},
                )
            payload = json.loads(body)
            request = to_responses(
                payload,
                replay=self.server.replay,
                session_id=self.headers.get('X-RoboTeam-Session'),
                fork_source=self.headers.get('X-RoboTeam-Fork-Source'),
            )
            record.update(
                requested_model=payload.get('model'),
                tools=len(payload.get('tools', [])),
                input_items=len(request['input']),
            )
            record.update(request_fingerprints(request))
            record.update(
                replay_policy='exact-output-v2',
                native_session=request['input'].session_id,
                fork_source=request['input'].fork_source,
                replayed_response_ids=request['input'].replayed_ids,
                native_controls=request['input'].native_controls,
                native_default_response_ids=request['input'].native_defaults,
                replay_prefix_changes=request['input'].replay_prefix_changes,
                comparison_response_id=(request.get('prompt_cache_options') or {}).get(
                    'comparison_response_id'
                ),
            )
            record['stage'] = 'upstream_websocket'
            if payload.get('stream'):
                self.send_response(200)
                self.send_header('Content-Type', 'text/event-stream')
                self.send_header('Cache-Control', 'no-cache')
                self.send_header('Connection', 'close')
                self.end_headers()
                streaming = True
                self.close_connection = True
                threading.Thread(target=ping, daemon=True).start()
            record['stage'] = 'upstream_stream'
            with self.server.transport.exchange(request, done, record) as result:
                # A completed retry returns a previously metered response, not new inference.
                if record['ws_mode'] != 'completed_retry':
                    record.update(response_metadata(result), upstream_completed=True)
                else:
                    record.update(response_id=result['id'], reused_completed_response=True)
                record['stage'] = 'translate_response'
                message = to_message(result)
                self.server.replay.remember(request, result, message)
            record.update(completed=True)
            if done.is_set():
                raise ConnectionResetError('Client disconnected before completion')
            if streaming:
                for event, data in message_events(message, result['output']):
                    send(event, data)
            else:
                self.reply(200, message)
        except (BrokenPipeError, ConnectionResetError):
            record.update(completed=False, failure='client_disconnect')
        except Exception as error:
            if done.is_set():
                record.update(
                    completed=False, failure='client_disconnect', interrupted_reader=type(error).__name__
                )
                return
            record.update(completed=False, failure=type(error).__name__)
            if hasattr(error, 'replay_context'):
                record['replay_failure_context'] = error.replay_context
            if isinstance(error, UpstreamError):
                record.update(error_code=error.code, error_param=error.param)
                if error.code in ('subscription_sharing_usage_limit_exceeded', 'insufficient_quota'):
                    self.server.hold_quota(error.code, error.param)
            # Request-boundary handling surfaces failure; incomplete streams never emit message_stop.
            detail = str(error) if isinstance(error, ProtocolError) else type(error).__name__
            record['failure_detail'] = detail[:200]
            record['failure_stack'] = [
                {'function': frame.name, 'line': frame.lineno}
                for frame in traceback.extract_tb(error.__traceback__)[-4:]
            ]
            cause = error.reason if isinstance(error, URLError) else error
            transient_tls = isinstance(cause, ssl.SSLCertVerificationError)
            if transient_tls:
                record['tls_verify_code'] = cause.verify_code
                record['tls_verify_message'] = cause.verify_message
            status = 400 if isinstance(error, (ProtocolError, json.JSONDecodeError)) else 502
            retry = transient_tls
            if isinstance(error, UpstreamError):
                status = error.status or (429 if 'limit' in str(error.code) else 502)
                record['http'] = status
                retry = status in (429, 502, 503, 504) and error.code not in (
                    'subscription_sharing_usage_limit_exceeded',
                    'insufficient_quota',
                )
            document = {
                'type': 'error',
                'error': {'type': 'api_error' if streaming else 'invalid_request_error', 'message': detail},
            }
            if isinstance(error, UpstreamError):
                document['error'].update(code=error.code, param=error.param)
                if error.code in ('subscription_sharing_usage_limit_exceeded', 'insufficient_quota'):
                    document['error']['type'] = 'rate_limit_error'
            try:
                if streaming:
                    send('error', document)
                else:
                    self.reply(
                        status, document, {'x-should-retry': 'true' if retry else 'false', 'Retry-After': '2'}
                    )
            except (BrokenPipeError, ConnectionResetError, OSError):
                record['client_disconnected'] = True
        finally:
            done.set()
            record.update(finished_at=time.time(), duration_s=time.time() - record['at'])
            self.server.audit(record)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--credential-file', type=Path, required=True)
    parser.add_argument('--auth-mode', choices=('chatgpt_plan', 'openai_api_key'), default='chatgpt_plan')
    parser.add_argument(
        '--replay-file',
        type=Path,
        help='Existing protected replay database for an explicit credential handoff',
    )
    parser.add_argument(
        '--native-session-index',
        type=Path,
        help='Private host-written mapping of native IDs to their transcripts',
    )
    parser.add_argument(
        '--tokens-per-minute',
        type=int,
        help='Shared conservative API reservation budget; 428k tokens per request at a 300k context',
    )
    parser.add_argument('--key-file', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18461)
    parser.add_argument('--log', type=Path)
    args = parser.parse_args()
    if not args.key_file.exists():
        from roboteam.harness.adapters.gpt_in_claude.auth import atomic_json

        atomic_json(args.key_file, {'key': secrets.token_urlsafe(48)})
    key = json.loads(args.key_file.read_text())['key']
    server = Gateway(
        ('127.0.0.1', args.port),
        args.credential_file,
        key,
        args.log,
        args.auth_mode,
        args.replay_file,
        args.native_session_index,
        args.tokens_per_minute,
    )
    print(
        json.dumps({'listening': server.server_address, 'model': MODEL, 'auth': args.auth_mode}), flush=True
    )
    try:
        server.serve_forever()
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
