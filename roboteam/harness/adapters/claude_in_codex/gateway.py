"""Experimental loopback adapter: Codex CLI Responses requests to Anthropic Messages.

Only the model transport is translated. The native Codex CLI owns tools, sessions,
compaction and forks. Every upstream request selects claude-opus-5-5 through the official
`anthropic` SDK. There is no model or credential fallback, no automatic replay, no
conversation store and no prompt logging; content that cannot be represented is rejected.

    python roboteam/harness/adapters/claude_in_codex/gateway.py --anthropic-key-file /private/claude/anthropic-key.txt \
        --key-file /private/claude/gateway-key.json --log /private/claude/transport-metadata.jsonl

See docs/harness/claude-in-codex.md.
"""
import argparse
import base64
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time
from urllib.parse import urlsplit

if not __package__:  # Run as a file, without installing the package: import from this checkout.
    sys.path[0] = str(Path(__file__).resolve().parents[4])
from roboteam.harness.adapters.claude_in_codex.monitor import summarize  # noqa: E402  (standard library only)

MODEL = 'claude-opus-5-5'
REVISION = 'messages-adapter-v1'
UPSTREAM = 'https://api.anthropic.com'
OPAQUE = 'rf_claude_thinking_v1:'
BINDING_BETA = 'thinking-binding-controls-2026-08-01'
DEFAULT_MAX_TOKENS = 64000
EFFORTS = ('low', 'medium', 'high', 'xhigh', 'max')
IMAGE_TYPES = ('image/jpeg', 'image/png', 'image/gif', 'image/webp')
MAX_BODY = 256 * 1024 * 1024
KEEPALIVE_S = 5.0
REMINDER = '<system-reminder>\n%s\n</system-reminder>'
FREEFORM_NOTE = ('\n\nThis is a freeform tool. Put the complete raw tool input, exactly as the tool expects it, '
                 'in the `input` string.')
# Request fields that carry no model-visible content: client bookkeeping only.
IGNORED_FIELDS = ('prompt_cache_key', 'client_metadata', 'metadata', 'user', 'safety_identifier')
REQUEST_FIELDS = ('model', 'input', 'instructions', 'tools', 'tool_choice', 'parallel_tool_calls', 'reasoning',
                  'store', 'stream', 'include', 'text', 'max_output_tokens', *IGNORED_FIELDS)
TOOL_NAME = re.compile(r'[A-Za-z0-9_-]{1,64}')
SAFE_ID = re.compile(r'[A-Za-z0-9_.:-]{1,128}')


class ProtocolError(ValueError):
    """The request or the upstream answer cannot be translated without losing something."""


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


# ---------------------------------------------------------------------------- request

def seal(block):
    """One Anthropic thinking block, unchanged, as a Responses reasoning item's opaque content."""
    return OPAQUE + base64.b64encode(canonical({'model': MODEL, 'block': block})).decode()


def unseal(value):
    if not isinstance(value, str) or not value.startswith(OPAQUE):
        raise ProtocolError('A reasoning item was not produced by this gateway; its reasoning cannot be replayed '
                            'to Claude and is not silently dropped')
    try:
        document = json.loads(base64.b64decode(value[len(OPAQUE):], validate=True))
        block = document['block']
        kind = block['type']
    except (ValueError, KeyError, TypeError):
        raise ProtocolError('A reasoning item carries damaged opaque content') from None
    if kind == 'thinking':
        if set(block) != {'type', 'thinking', 'signature'} or not isinstance(block['signature'], str):
            raise ProtocolError('A reasoning item carries a malformed thinking block')
    elif kind == 'redacted_thinking':
        if set(block) != {'type', 'data'} or not isinstance(block['data'], str):
            raise ProtocolError('A reasoning item carries a malformed redacted thinking block')
    else:
        raise ProtocolError('A reasoning item carries an unknown block type')
    return block


def image_block(part):
    url = part.get('image_url')
    if isinstance(url, dict):
        url = url.get('url')
    if part.get('file_id') or not isinstance(url, str):
        raise ProtocolError('Only inline or HTTPS image_url images are supported')
    if part.get('detail') not in (None, 'auto', 'low', 'high', 'original'):
        raise ProtocolError('Unsupported image detail')
    if url.startswith('data:'):
        header, _, data = url[5:].partition(',')
        media, _, encoding = header.partition(';')
        if media not in IMAGE_TYPES or encoding != 'base64' or not data:
            raise ProtocolError('Unsupported inline image type: ' + media[:40])
        return {'type': 'image', 'source': {'type': 'base64', 'media_type': media, 'data': data}}
    if urlsplit(url).scheme == 'https':
        return {'type': 'image', 'source': {'type': 'url', 'url': url}}
    raise ProtocolError('Unsupported image source')


def user_blocks(content, where):
    """Responses input parts as Messages text and image blocks; nothing is dropped."""
    if isinstance(content, str):
        return [{'type': 'text', 'text': content}] if content else []
    if not isinstance(content, list):
        raise ProtocolError('Expected text or a content array in ' + where)
    blocks = []
    for part in content:
        kind = part.get('type') if isinstance(part, dict) else None
        if kind in ('input_text', 'output_text', 'text'):
            if not isinstance(part.get('text'), str):
                raise ProtocolError('Malformed text part in ' + where)
            if part['text']:
                blocks.append({'type': 'text', 'text': part['text']})
        elif kind == 'input_image':
            blocks.append(image_block(part))
        else:
            raise ProtocolError('Unsupported content part in %s: %s' % (where, str(kind)[:40]))
    return blocks


def text_of(content, where):
    blocks = user_blocks(content, where)
    if any(block['type'] != 'text' for block in blocks):
        raise ProtocolError('Only text is supported in ' + where)
    return [block['text'] for block in blocks]


def translate_tools(tools):
    """Responses tool definitions as Anthropic tools, name-sorted, with the way back.

    Returns (definitions, names): `names` maps each Anthropic tool name to
    ('function' | 'custom', namespace or None, original name).
    """
    definitions, names = {}, {}

    def add(flat, kind, namespace, name, description, schema, strict=False):
        if not isinstance(name, str) or not TOOL_NAME.fullmatch(flat):
            raise ProtocolError('Tool name cannot be represented: ' + str(flat)[:80])
        if flat in definitions:
            raise ProtocolError('Duplicate tool name: ' + flat)
        if not isinstance(schema, dict):
            raise ProtocolError('Tool %s has no JSON schema' % flat)
        definition = {'name': flat, 'description': description if isinstance(description, str) else '',
                      'input_schema': schema}
        if strict is True:
            definition['strict'] = True
        definitions[flat] = definition
        names[flat] = (kind, namespace, name)

    def function(tool, namespace=None, context=''):
        flat = tool.get('name') if namespace is None else '%s__%s' % (namespace, tool.get('name'))
        description = tool.get('description') or ''
        add(flat, 'function', namespace, tool.get('name'), context + description,
            tool.get('parameters') if tool.get('parameters') is not None else {'type': 'object', 'properties': {}},
            tool.get('strict'))

    for tool in tools or []:
        kind = tool.get('type') if isinstance(tool, dict) else None
        if kind == 'function':
            function(tool)
        elif kind == 'custom':
            form = tool.get('format') or {'type': 'text'}
            description = (tool.get('description') or '') + FREEFORM_NOTE
            if form.get('type') == 'grammar':
                description += '\nThe input must match this %s grammar:\n%s' % (form.get('syntax'), form.get('definition'))
            elif form.get('type') != 'text':
                raise ProtocolError('Unsupported freeform tool format')
            add(tool.get('name'), 'custom', None, tool.get('name'), description,
                {'type': 'object', 'properties': {'input': {'type': 'string', 'description': 'Raw tool input'}},
                 'required': ['input'], 'additionalProperties': False})
        elif kind == 'namespace':
            if not isinstance(tool.get('name'), str) or not isinstance(tool.get('tools'), list):
                raise ProtocolError('Malformed tool namespace')
            context = 'Tool namespace `%s`: %s\n\n' % (tool['name'], tool.get('description') or '')
            for member in tool['tools']:
                if not isinstance(member, dict) or member.get('type') != 'function':
                    raise ProtocolError('Only function tools are supported inside a namespace')
                function(member, tool['name'], context)
        else:
            raise ProtocolError('Unsupported tool type: ' + str(kind)[:40])
    return [definitions[name] for name in sorted(definitions)], names


def flat_name(item, names):
    namespace, name = item.get('namespace'), item.get('name')
    flat = name if namespace is None else '%s__%s' % (namespace, name)
    if not isinstance(flat, str) or not TOOL_NAME.fullmatch(flat):
        raise ProtocolError('Replayed tool call has a name that cannot be represented')
    return flat


class Conversation:
    """Group Responses input items into alternating Messages turns."""

    def __init__(self):
        self.messages, self.assistant, self.open_calls = [], None, []
        self.results, self.extra = [], []
        self.counts = {'images': 0, 'tool_results': 0, 'thinking_blocks': 0, 'tool_calls': 0}

    def flush(self):
        if self.assistant is not None:
            if self.open_calls:
                raise ProtocolError('A replayed tool call has no output: ' + self.open_calls[0][:80])
            if not self.messages:
                raise ProtocolError('The conversation must begin with user content')
            self.messages.append({'role': 'assistant', 'content': self.assistant})
            self.assistant = None
        if self.results or self.extra:
            # Messages requires every result of one assistant turn first, in a single user turn.
            self.messages.append({'role': 'user', 'content': self.results + self.extra})
            self.results, self.extra = [], []

    def add_assistant(self, block, call_id=None):
        if self.results or self.extra:
            self.flush()  # user content or tool results closed the previous assistant turn
        if self.assistant is None:
            self.assistant = []
        self.assistant.append(block)
        if call_id is not None:
            self.open_calls.append(call_id)
            self.counts['tool_calls'] += 1

    def add_user(self, blocks):
        if self.open_calls:
            raise ProtocolError('User content arrived before the output of tool call ' + self.open_calls[0][:80])
        if self.assistant is not None and not self.results and not self.extra:
            self.flush()
        self.extra.extend(blocks)

    def add_result(self, call_id, content):
        if call_id not in self.open_calls:
            raise ProtocolError('A tool output has no matching tool call in the same turn')
        self.open_calls.remove(call_id)
        self.results.append({'type': 'tool_result', 'tool_use_id': call_id, 'content': content})
        self.counts['tool_results'] += 1


def call_identity(item):
    call_id = item.get('call_id')
    if not isinstance(call_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', call_id):
        raise ProtocolError('Tool call identifier cannot be represented')
    return call_id


def translate_input(body, names):
    """(system text blocks, messages, counts) for a Responses `input` array."""
    system = []
    if body.get('instructions') is not None:
        if not isinstance(body['instructions'], str):
            raise ProtocolError('instructions must be text')
        if body['instructions']:
            system.append(body['instructions'])
    items = body.get('input')
    if isinstance(items, str):
        items = [{'type': 'message', 'role': 'user', 'content': items}]
    if not isinstance(items, list) or not items:
        raise ProtocolError('input must be a non-empty array')
    conversation, leading = Conversation(), True
    for item in items:
        if not isinstance(item, dict):
            raise ProtocolError('Malformed input item')
        kind = item.get('type', 'message' if 'role' in item else None)
        role = item.get('role') if kind == 'message' else None
        if leading and role in ('developer', 'system'):
            # The static prefix: instructions and the developer messages before any other item.
            system.extend(text_of(item.get('content'), 'a developer message'))
            continue
        leading = False
        if role in ('developer', 'system'):
            # Later developer messages stay where they are, as marked text in the user turn:
            # moving them into `system` would rewrite the prefix of every earlier turn.
            conversation.add_user([{'type': 'text', 'text': REMINDER % text}
                                   for text in text_of(item.get('content'), 'a developer message')])
        elif role == 'user':
            blocks = user_blocks(item.get('content'), 'a user message')
            conversation.counts['images'] += sum(block['type'] == 'image' for block in blocks)
            conversation.add_user(blocks)
        elif role == 'assistant':
            for text in text_of(item.get('content'), 'an assistant message'):
                conversation.add_assistant({'type': 'text', 'text': text})
        elif kind == 'reasoning':
            conversation.add_assistant(unseal(item.get('encrypted_content')))
            conversation.counts['thinking_blocks'] += 1
        elif kind == 'function_call':
            try:
                arguments = json.loads(item.get('arguments') or '{}')
            except (ValueError, TypeError):
                raise ProtocolError('Replayed tool arguments are not valid JSON') from None
            if not isinstance(arguments, dict):
                raise ProtocolError('Replayed tool arguments must be a JSON object')
            call_id = call_identity(item)
            conversation.add_assistant({'type': 'tool_use', 'id': call_id, 'name': flat_name(item, names),
                                        'input': arguments}, call_id)
        elif kind == 'custom_tool_call':
            if not isinstance(item.get('input'), str):
                raise ProtocolError('Replayed freeform tool input must be text')
            call_id = call_identity(item)
            conversation.add_assistant({'type': 'tool_use', 'id': call_id, 'name': flat_name(item, names),
                                        'input': {'input': item['input']}}, call_id)
        elif kind in ('function_call_output', 'custom_tool_call_output'):
            output = item.get('output')
            if isinstance(output, str):
                content = output
            else:
                content = user_blocks(output, 'a tool output')
                conversation.counts['images'] += sum(block['type'] == 'image' for block in content)
                if all(block['type'] == 'text' for block in content):
                    content = content if content else ''
            conversation.add_result(call_identity(item), content)
        else:
            raise ProtocolError('Unsupported input item: ' + str(kind if role is None else role)[:60])
    conversation.flush()
    if not conversation.messages or conversation.messages[-1]['role'] != 'user':
        raise ProtocolError('The conversation must end with user content or tool results')
    return system, conversation.messages, conversation.counts


def translate_request(body, *, cache_ttl='5m', mismatch='error', session_tools=None, compaction_tool_choice='none'):
    """A Codex Responses request as Anthropic Messages parameters, plus what the reply needs.

    `session_tools` is the (definitions, names) pair this Codex session last declared. Codex
    sends its compaction request without tools; reusing the session's exact tools keeps the
    conversation prefix, and therefore replayed thinking blocks and the prompt cache, valid.
    """
    if not isinstance(body, dict):
        raise ProtocolError('The request body must be a JSON object')
    unknown = sorted(set(body) - set(REQUEST_FIELDS))
    if unknown:
        raise ProtocolError('Unsupported request field: ' + ', '.join(unknown)[:200])
    if body.get('model') != MODEL:
        raise ProtocolError('This gateway serves %s only; requested %s' % (MODEL, str(body.get('model'))[:80]))
    if body.get('stream') is not True:
        raise ProtocolError('Only streaming requests are supported')
    if body.get('store') not in (None, False):
        raise ProtocolError('store=true needs a server-side conversation store, which this gateway does not have')
    if any(value != 'reasoning.encrypted_content' for value in body.get('include') or []):
        raise ProtocolError('Unsupported include value')
    if body.get('text') not in (None, {}):
        raise ProtocolError('Text format and verbosity controls have no Messages equivalent')
    reasoning = body.get('reasoning') or {}
    if set(reasoning) - {'effort', 'summary'} or reasoning.get('summary') not in (None, 'none'):
        raise ProtocolError('Unsupported reasoning option')
    if reasoning.get('effort') not in EFFORTS:
        # Thinking cannot be switched off and the API default is medium: never guess.
        raise ProtocolError('reasoning.effort must be one of ' + ', '.join(EFFORTS))
    choice = body.get('tool_choice', 'auto')
    if choice not in ('auto', 'none'):
        raise ProtocolError('Only tool_choice auto or none is supported; forced tool use is rejected by ' + MODEL)
    limit = body.get('max_output_tokens')
    if limit is None:
        limit = DEFAULT_MAX_TOKENS
    elif type(limit) is not int or limit <= 0:
        raise ProtocolError('max_output_tokens must be a positive integer')

    tools, names = translate_tools(body.get('tools'))
    declared = bool(tools)
    restored = False
    if not tools and session_tools is not None:
        tools, names, restored = session_tools[0], session_tools[1], True
    system, messages, counts = translate_input(body, names)
    if not tools and counts['tool_calls']:
        raise ProtocolError('The request replays tool calls but declares no tools, and this gateway has no '
                            'record of the session\'s tools (it was restarted, or the session is unknown)')

    marker = {'type': 'ephemeral', 'ttl': '1h'} if cache_ttl == '1h' else {'type': 'ephemeral'}
    params = {'model': MODEL, 'max_tokens': limit, 'messages': messages,
              'thinking': {'type': 'adaptive'}, 'output_config': {'effort': reasoning['effort']}}
    if mismatch != 'api_default':
        params['thinking']['block_binding'] = {'prefix_mismatch_behavior': mismatch}
        params['betas'] = [BINDING_BETA]
    tool_choice = {'type': choice}
    if restored and choice == 'auto':
        tool_choice = {'type': compaction_tool_choice}
    if tools:
        params['tools'] = [dict(tool) for tool in tools]
        if body.get('parallel_tool_calls') is False and tool_choice['type'] == 'auto':
            tool_choice['disable_parallel_tool_use'] = True
        params['tool_choice'] = tool_choice
    if system:
        params['system'] = [{'type': 'text', 'text': text} for text in system]
        # One explicit breakpoint after the static prefix: tools render before system.
        params['system'][-1]['cache_control'] = dict(marker)
    elif tools:
        params['tools'][-1]['cache_control'] = dict(marker)
    # Automatic caching moves a second breakpoint along the growing conversation. A request
    # whose tool_choice differs from the session's cannot reuse that entry, and nothing reads
    # a compaction request's prefix again, so no write is paid for there.
    automatic = not (restored and tool_choice['type'] != 'auto')
    if automatic:
        params['cache_control'] = dict(marker)
    info = {'names': names, 'tools_declared': declared, 'tools_restored': restored,
            'tools': [dict(tool) for tool in tools], 'counts': {**counts, 'messages': len(messages), 'tools': len(tools)},
            'effort': reasoning['effort'], 'max_tokens': limit, 'cache_ttl': cache_ttl, 'automatic_cache': automatic,
            'tool_choice': tool_choice['type'] if tools else None,
            'tools_sha256': digest(tools)[:16], 'system_sha256': digest(system)[:16],
            'prefix_sha256': digest({'tools': tools, 'system': system})[:16]}
    return params, info


# --------------------------------------------------------------------------- response

class Failure(Exception):
    """A terminal state that must not reach Codex as response.completed."""
    def __init__(self, code, message, kind='failed', reason=None):
        super().__init__(message)
        self.code, self.kind, self.reason = code, kind, reason


class Reply:
    """Accumulate one Messages stream; nothing is released until it has ended well."""

    def __init__(self, info):
        self.info = info
        self.blocks, self.buffers = {}, {}
        self.message_id = self.model = self.stop_reason = self.stop_details = None
        self.usage, self.transformations, self.stopped = {}, [], False

    def feed(self, event):
        kind = event.get('type')
        if kind == 'message_start':
            message = event.get('message') or {}
            self.message_id, self.model = message.get('id'), message.get('model')
            self._usage(message.get('usage'))
            self.transformations = message.get('input_transformations') or self.transformations
        elif kind == 'content_block_start':
            block = dict(event.get('content_block') or {})
            index = event.get('index')
            if block.get('type') == 'thinking':
                block = {'type': 'thinking', 'thinking': block.get('thinking') or '', 'signature': block.get('signature') or ''}
            elif block.get('type') == 'redacted_thinking':
                block = {'type': 'redacted_thinking', 'data': block.get('data')}
            elif block.get('type') == 'text':
                if block.get('citations'):
                    raise Failure('invalid_prompt', 'Upstream returned citations, which cannot be represented')
                block = {'type': 'text', 'text': block.get('text') or ''}
            elif block.get('type') == 'tool_use':
                block = {'type': 'tool_use', 'id': block.get('id'), 'name': block.get('name')}
                self.buffers[index] = ''
            else:
                raise Failure('invalid_prompt', 'Unsupported upstream content block: ' + str(block.get('type'))[:60])
            self.blocks[index] = block
        elif kind == 'content_block_delta':
            block, delta = self.blocks.get(event.get('index')), event.get('delta') or {}
            if block is None:
                raise Failure('server_error', 'Upstream sent a delta for an unknown content block')
            sort = delta.get('type')
            if sort == 'text_delta' and block['type'] == 'text':
                block['text'] += delta.get('text') or ''
            elif sort == 'thinking_delta' and block['type'] == 'thinking':
                block['thinking'] += delta.get('thinking') or ''
            elif sort == 'signature_delta' and block['type'] == 'thinking':
                block['signature'] = delta.get('signature') or ''
            elif sort == 'input_json_delta' and block['type'] == 'tool_use':
                self.buffers[event['index']] += delta.get('partial_json') or ''
            else:
                raise Failure('invalid_prompt', 'Unsupported upstream delta: ' + str(sort)[:60])
        elif kind == 'message_delta':
            delta = event.get('delta') or {}
            self.stop_reason = delta.get('stop_reason') or self.stop_reason
            self.stop_details = delta.get('stop_details') or self.stop_details
            self._usage(event.get('usage'))
            self.transformations = event.get('input_transformations') or self.transformations
        elif kind == 'message_stop':
            self.stopped = True
        elif kind == 'error':
            error = event.get('error') or {}
            raise Failure(stream_code(error.get('type')), 'Anthropic stream error (%s): %s'
                          % (str(error.get('type'))[:60], str(error.get('message'))[:300]))

    def _usage(self, usage):
        for key, value in (usage or {}).items():
            if value is not None:
                self.usage[key] = value

    def usage_record(self):
        """Anthropic's own counts, for the metadata log."""
        number = lambda value: value if type(value) is int else 0
        creation = self.usage.get('cache_creation') or {}
        details = self.usage.get('output_tokens_details') or {}
        return {'input_tokens': number(self.usage.get('input_tokens')),
                'cache_read_input_tokens': number(self.usage.get('cache_read_input_tokens')),
                'cache_creation_input_tokens': number(self.usage.get('cache_creation_input_tokens')),
                'cache_creation_5m_input_tokens': number(creation.get('ephemeral_5m_input_tokens')),
                'cache_creation_1h_input_tokens': number(creation.get('ephemeral_1h_input_tokens')),
                'output_tokens': number(self.usage.get('output_tokens')),
                'thinking_tokens': number(details.get('thinking_tokens'))}

    def responses_usage(self):
        """Responses usage as Codex and the benchmark read it: input includes cached input."""
        own = self.usage_record()
        total_input = own['input_tokens'] + own['cache_read_input_tokens'] + own['cache_creation_input_tokens']
        return {'input_tokens': total_input,
                'input_tokens_details': {'cached_tokens': own['cache_read_input_tokens'],
                                         'cache_write_tokens': own['cache_creation_input_tokens']},
                'output_tokens': own['output_tokens'],
                'output_tokens_details': {'reasoning_tokens': own['thinking_tokens']},
                'total_tokens': total_input + own['output_tokens']}

    def dropped_thinking(self):
        return sum(1 for entry in self.transformations if isinstance(entry, dict) and entry.get('type') == 'thinking_dropped')

    def items(self):
        """The complete output as Responses items, or a Failure. Called once, after the stream."""
        if self.message_id is None or not self.stopped:
            raise Failure('server_error', 'The Anthropic stream ended before message_stop')
        if self.model != MODEL:
            raise Failure('invalid_prompt', 'Upstream answered with model %s; only %s is allowed and there is no '
                          'fallback' % (str(self.model)[:80], MODEL))
        if self.stop_reason == 'refusal':
            details = self.stop_details if isinstance(self.stop_details, dict) else {}
            raise Failure('invalid_prompt', 'Claude declined this request (stop_reason refusal, category %s). No '
                          'output was released and no other model was tried.' % str(details.get('category'))[:40])
        if self.stop_reason == 'max_tokens':
            raise Failure('max_output_tokens', 'Claude reached max_tokens before finishing', 'incomplete',
                          'max_output_tokens')
        if self.stop_reason == 'model_context_window_exceeded':
            raise Failure('context_length_exceeded', 'Claude reached its context window')
        if self.stop_reason not in ('end_turn', 'tool_use'):
            raise Failure('invalid_prompt', 'Unsupported stop reason: ' + str(self.stop_reason)[:60])
        output, calls = [], 0
        for index in sorted(self.blocks):
            block = self.blocks[index]
            if block['type'] in ('thinking', 'redacted_thinking'):
                output.append({'id': 'rs_%s_%d' % (self.message_id, index), 'type': 'reasoning', 'summary': [],
                               'encrypted_content': seal(block)})
            elif block['type'] == 'text':
                if not block['text'].strip():
                    continue  # the API accepts no empty text block back; its prefix check ignores them
                output.append({'id': 'msg_%s_%d' % (self.message_id, index), 'type': 'message', 'role': 'assistant',
                               'status': 'completed',
                               'content': [{'type': 'output_text', 'text': block['text'], 'annotations': []}]})
            else:
                calls += 1
                output.append(self._call(block, self.buffers[index]))
        if (self.stop_reason == 'tool_use') != bool(calls):
            raise Failure('server_error', 'Stop reason %s does not match the tool calls returned' % self.stop_reason)
        if calls and not self.info['tools_declared']:
            raise Failure('invalid_prompt', 'Claude called a tool in a request that declared none')
        return output

    def _call(self, block, raw):
        raw = raw if raw.strip() else '{}'
        try:
            arguments = json.loads(raw)
        except ValueError:
            raise Failure('server_error', 'Claude returned tool input that is not valid JSON') from None
        if not isinstance(arguments, dict) or not isinstance(block.get('id'), str) or not isinstance(block.get('name'), str):
            raise Failure('server_error', 'Claude returned a malformed tool call')
        kind, namespace, name = self.info['names'].get(block['name'], ('function', None, block['name']))
        if kind == 'custom':
            if set(arguments) != {'input'} or not isinstance(arguments['input'], str):
                raise Failure('server_error', 'Claude returned a malformed freeform tool call')
            return {'id': 'ctc_' + block['id'], 'type': 'custom_tool_call', 'status': 'completed',
                    'call_id': block['id'], 'name': name, 'input': arguments['input']}
        item = {'id': 'fc_' + block['id'], 'type': 'function_call', 'status': 'completed', 'call_id': block['id'],
                'name': name, 'arguments': raw}
        if namespace is not None:
            item['namespace'] = namespace
        return item


def stream_code(error_type):
    """A response.failed code. Codex retries unknown codes and stops on invalid_prompt."""
    return {'overloaded_error': 'server_overloaded', 'rate_limit_error': 'rate_limit_exceeded',
            'invalid_request_error': 'invalid_prompt', 'authentication_error': 'invalid_prompt',
            'permission_error': 'invalid_prompt', 'billing_error': 'invalid_prompt',
            'not_found_error': 'invalid_prompt', 'request_too_large': 'invalid_prompt'}.get(error_type, 'server_error')


def envelope(response_id, status, output=(), usage=None, **extra):
    return {'id': response_id, 'object': 'response', 'created_at': int(time.time()), 'status': status, 'model': MODEL,
            'output': list(output), 'usage': usage, **extra}


def completed_events(response_id, output, usage):
    """The Responses SSE sequence for a finished answer, each item released whole."""
    for index, item in enumerate(output):
        opening = dict(item)
        if item['type'] == 'message':
            opening.update(status='in_progress', content=[])
        elif item['type'] == 'function_call':
            opening.update(status='in_progress', arguments='')
        elif item['type'] == 'custom_tool_call':
            opening.update(status='in_progress', input='')
        yield 'response.output_item.added', {'output_index': index, 'item': opening}
        common = {'output_index': index, 'item_id': item['id']}
        if item['type'] == 'message':
            part = item['content'][0]
            yield 'response.content_part.added', {**common, 'content_index': 0, 'part': {**part, 'text': ''}}
            yield 'response.output_text.delta', {**common, 'content_index': 0, 'delta': part['text']}
            yield 'response.output_text.done', {**common, 'content_index': 0, 'text': part['text']}
            yield 'response.content_part.done', {**common, 'content_index': 0, 'part': part}
        elif item['type'] == 'function_call':
            yield 'response.function_call_arguments.delta', {**common, 'delta': item['arguments']}
            yield 'response.function_call_arguments.done', {**common, 'arguments': item['arguments']}
        elif item['type'] == 'custom_tool_call':
            yield 'response.custom_tool_call_input.delta', {**common, 'delta': item['input']}
            yield 'response.custom_tool_call_input.done', {**common, 'input': item['input']}
        yield 'response.output_item.done', {'output_index': index, 'item': item}
    yield 'response.completed', {'response': envelope(response_id, 'completed', output, usage)}


def failure_event(response_id, failure, usage=None):
    if failure.kind == 'incomplete':
        return 'response.incomplete', {'response': envelope(response_id, 'incomplete', usage=usage,
                                                            incomplete_details={'reason': failure.reason})}
    return 'response.failed', {'response': envelope(response_id, 'failed', usage=usage,
                                                    error={'code': failure.code, 'message': str(failure)})}


# ----------------------------------------------------------------------------- server

def private_file(path, what):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError(what + ' must be a regular file, not a symlink')
    if os.name != 'nt' and path.stat().st_mode & 0o077:
        raise ValueError(what + ' must be readable by its owner only (chmod 600)')
    return path


def read_secret(path, what):
    value = private_file(path, what).read_text(encoding='utf-8-sig').strip()
    if not value or any(char.isspace() for char in value) or value.startswith('PASTE_'):
        raise ValueError(what + ' must contain exactly one credential and nothing else')
    return value


def load_keys(path):
    """Local gateway keys by label: {"key": "..."} or {"keys": {"label": "..."}}."""
    document = json.loads(private_file(path, 'Gateway key file').read_text())
    keys = document.get('keys') if isinstance(document.get('keys'), dict) else {'default': document.get('key')}
    if not keys or len(set(keys.values())) != len(keys):
        raise ValueError('Gateway key file needs distinct keys')
    for label, key in keys.items():
        if not re.fullmatch(r'[A-Za-z0-9_.-]{1,64}', label) or not isinstance(key, str) or len(key) < 32:
            raise ValueError('Gateway keys need a simple label and at least 32 characters')
    return keys


def create_key_file(path):
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(handle, 'w') as stream:
        json.dump({'key': secrets.token_urlsafe(48)}, stream)


def upstream_url(value):
    url = urlsplit(value)
    if value == UPSTREAM:
        return value
    # Offline tests only: a local stand-in for the API. Nothing else may receive the key.
    if (url.scheme == 'http' and url.hostname == '127.0.0.1' and url.port and not url.username
            and not url.password and not url.query and not url.fragment and url.path in ('', '/')):
        return value
    raise ValueError('The upstream is %s; only a literal 127.0.0.1 test server may replace it' % UPSTREAM)


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, anthropic_key, keys, *, log=None, cache_ttl='5m', mismatch='error',
                 compaction_tool_choice='none', upstream=UPSTREAM, state_dir=None, timeout_s=600):
        if address[0] != '127.0.0.1':
            raise ValueError('The gateway listens on 127.0.0.1 only')
        if cache_ttl not in ('5m', '1h') or mismatch not in ('error', 'drop_block', 'api_default') \
                or compaction_tool_choice not in ('none', 'auto'):
            raise ValueError('Unknown gateway option')
        import anthropic
        self.sdk = anthropic
        self.read_key = anthropic_key if callable(anthropic_key) else (lambda: anthropic_key)
        self.read_key()
        self.upstream, self.timeout_s = upstream_url(upstream), timeout_s
        self.keys, self.log = dict(keys), Path(log) if log else None
        self.cache_ttl, self.mismatch, self.compaction_tool_choice = cache_ttl, mismatch, compaction_tool_choice
        self.state_dir = Path(state_dir) if state_dir else None
        if self.state_dir:
            self.state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.lock, self.sessions, self.records, self.started = threading.Lock(), {}, [], time.time()
        super().__init__(address, Handler)

    def client(self):
        # An explicit key and base URL: the SDK then consults no environment variable or
        # model, and it never retries by itself (Codex owns retries).
        return self.sdk.Anthropic(api_key=self.read_key(), base_url=self.upstream, max_retries=0,
                                  timeout=self.timeout_s)

    def label(self, presented):
        for label, key in self.keys.items():
            if secrets.compare_digest(presented.encode(), key.encode()):
                return label
        return None

    def _state_file(self, session):
        return self.state_dir/(hashlib.sha256(session.encode()).hexdigest()+'.json') if self.state_dir else None

    def remember_tools(self, session, tools, names):
        if session is None or not tools:
            return
        fingerprint = digest(tools)
        with self.lock:
            if self.sessions.get(session, (None,))[0] == fingerprint:
                return
            self.sessions[session] = (fingerprint, tools, names)
            target = self._state_file(session)
            if target is not None:
                temporary = target.with_suffix('.tmp-%s' % secrets.token_hex(4))
                handle = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(handle, 'w') as stream:
                    json.dump({'tools': tools, 'names': names}, stream)
                os.replace(temporary, target)

    def recall_tools(self, session):
        if session is None:
            return None
        with self.lock:
            known = self.sessions.get(session)
            if known is None and self.state_dir and self._state_file(session).is_file():
                saved = json.loads(self._state_file(session).read_text())
                names = {name: tuple(value) for name, value in saved['names'].items()}
                known = self.sessions[session] = (digest(saved['tools']), saved['tools'], names)
        return (known[1], known[2]) if known else None

    def audit(self, record):
        with self.lock:
            self.records.append({key: record.get(key) for key in ('at', 'status', 'run', 'key_label', 'codex_session',
                                                                  'usage', 'cache_ttl', 'model', 'prefix_sha256',
                                                                  'thinking_blocks_dropped')})
            del self.records[:-50000]
            if self.log:
                # Owner-only: metadata, but it names sessions and runs.
                handle = os.open(self.log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
                with os.fdopen(handle, 'a', encoding='utf-8') as stream:
                    stream.write(json.dumps(record, sort_keys=True) + '\n')

    def stats(self, window_s=600):
        with self.lock:
            records = list(self.records)
        return {'model': MODEL, 'transport_revision': REVISION, 'started_at': self.started,
                **summarize(records, window_s=window_s)}


def codex_identity(headers):
    """Non-secret identifiers the Codex CLI sends, validated before they reach a log."""
    safe = lambda value: value if isinstance(value, str) and SAFE_ID.fullmatch(value) else None
    try:
        metadata = json.loads(headers.get('x-codex-turn-metadata') or '{}')
    except ValueError:
        metadata = {}
    metadata = metadata if isinstance(metadata, dict) else {}
    return {'codex_session': safe(headers.get('session-id')) or safe(metadata.get('session_id')),
            'codex_thread': safe(headers.get('thread-id')) or safe(metadata.get('thread_id')),
            'codex_installation': safe(metadata.get('installation_id')),
            'codex_forked_from': safe(metadata.get('forked_from_thread_id')),
            'request_kind': safe(metadata.get('request_kind'))}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, *args):
        pass

    def reply(self, status, document, headers=None):
        body = json.dumps(document).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        # A rejected request may leave an unread body; it must never become the next request.
        self.send_header('Connection', 'close')
        self.close_connection = True
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def error(self, status, kind, message, headers=None):
        self.reply(status, {'error': {'type': kind, 'code': kind, 'message': message}}, headers)

    def authorized(self):
        value = self.headers.get('Authorization', '')
        return self.server.label(value[7:]) if value.startswith('Bearer ') else None

    def do_GET(self):
        path = urlsplit(self.path).path
        if path == '/healthz':
            # The local listener only; it proves nothing about Anthropic access.
            return self.reply(200, {'ready': True, 'model': MODEL, 'transport_revision': REVISION,
                                    'inference_verified': False})
        label = self.authorized()
        if label is None:
            return self.error(401, 'authentication_error', 'Invalid local gateway key')
        if path == '/stats':
            return self.reply(200, self.server.stats())
        if path in ('/v1/models', '/models'):
            return self.reply(200, {'object': 'list', 'data': [{'id': MODEL, 'object': 'model', 'owned_by': 'anthropic'}]})
        self.error(404, 'not_found_error', 'Endpoint not implemented')

    def send_event(self, event, data):
        self.sequence += 1
        self.wfile.write(('event: %s\ndata: %s\n\n' % (event, json.dumps({'type': event, 'sequence_number': self.sequence,
                                                                          **data}))).encode())
        self.wfile.flush()

    def do_POST(self):
        server = self.server
        label = self.authorized()
        if label is None:
            return self.error(401, 'authentication_error', 'Invalid local gateway key')
        identity = codex_identity(self.headers)
        run = label if label != 'default' else ('codex-' + identity['codex_installation'][:8]
                                                if identity['codex_installation'] else 'unknown')
        record = {'event': 'request', 'at': time.time(), 'request_id': secrets.token_hex(8), 'model': MODEL,
                  'key_label': label, 'run': run, **identity, 'status': 'rejected', 'http': None,
                  'cache_ttl': server.cache_ttl, 'thinking_prefix_mismatch': server.mismatch}
        streaming, reply, stream = False, None, None
        self.sequence = 0
        try:
            try:
                length = int(self.headers.get('Content-Length', ''))
            except ValueError:
                raise ProtocolError('A Content-Length is required') from None
            if not 0 < length <= MAX_BODY:
                raise ProtocolError('Invalid request size')
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise ConnectionResetError('Client disconnected during upload')
            if urlsplit(self.path).path not in ('/v1/responses', '/responses'):
                record.update(http=404, failure='unsupported_endpoint')
                return self.error(404, 'not_found_error', 'Endpoint not implemented')
            try:
                body = json.loads(raw)
            except ValueError:
                raise ProtocolError('The request body is not valid JSON') from None
            session = identity['codex_session']
            params, info = translate_request(body, cache_ttl=server.cache_ttl, mismatch=server.mismatch,
                                             session_tools=server.recall_tools(session),
                                             compaction_tool_choice=server.compaction_tool_choice)
            if info['tools_declared']:
                server.remember_tools(session, info['tools'], info['names'])
            record.update({key: info[key] for key in ('counts', 'effort', 'max_tokens', 'tools_restored', 'tool_choice',
                                                      'automatic_cache', 'tools_sha256', 'system_sha256',
                                                      'prefix_sha256')})
            reply = Reply(info)
            betas = params.pop('betas', None)
            client = server.client()
            api = client.beta.messages if betas else client.messages
            stream = api.create(**params, stream=True, **({'betas': betas} if betas else {}))
            record['upstream_request_id'] = getattr(getattr(stream, 'response', None), 'headers', {}).get('request-id')
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            streaming = True
            record['http'] = 200
            response_id = 'resp_' + record['request_id']
            self.send_event('response.created', {'response': envelope(response_id, 'in_progress')})
            written = time.monotonic()
            try:
                for event in stream:
                    reply.feed(event if isinstance(event, dict) else event.to_dict())
                    if time.monotonic() - written >= KEEPALIVE_S:
                        # Keeps Codex's idle timer alive and notices a client that went away.
                        self.send_event('response.in_progress', {'response': envelope(response_id, 'in_progress')})
                        written = time.monotonic()
                output = reply.items()
            except Failure as failure:
                record.update(status='incomplete' if failure.kind == 'incomplete' else 'failed', failure=failure.code)
                self.send_event(*failure_event(response_id, failure, reply.responses_usage()))
                return
            except (BrokenPipeError, ConnectionResetError):
                raise
            except Exception as error:
                # Nothing was released, so Codex may retry; the gateway itself never replays.
                status = getattr(error, 'status_code', None)
                kind = ((getattr(error, 'body', None) or {}).get('error') or {}).get('type') \
                    if isinstance(getattr(error, 'body', None), dict) else None
                record.update(status='failed', failure='upstream_stream', exception=type(error).__name__,
                              upstream_status=status, upstream_error=kind)
                failure = Failure(stream_code(kind), 'The Anthropic stream failed (%s)' % (kind or type(error).__name__))
                self.send_event(*failure_event(response_id, failure, reply.responses_usage()))
                return
            for event, data in completed_events(response_id, output, reply.responses_usage()):
                self.send_event(event, data)
            record.update(status='completed', http=200, output_items=len(output))
        except ProtocolError as error:
            record.update(http=400, failure='protocol', failure_detail=str(error)[:200])
            if not streaming:
                self.error(400, 'invalid_request_error', 'Codex/Claude gateway: ' + str(error))
        except (BrokenPipeError, ConnectionResetError):
            record.update(status='client_disconnect')
        except Exception as error:
            status = getattr(error, 'status_code', None)
            record.update(status='upstream_error', exception=type(error).__name__)
            if streaming:
                return
            try:
                if isinstance(status, int) and 400 <= status <= 599:
                    payload = getattr(error, 'body', None)
                    detail = (payload.get('error') if isinstance(payload, dict) else None) or {}
                    kind = detail.get('type') if isinstance(detail.get('type'), str) else 'api_error'
                    record.update(http=status, upstream_error=kind,
                                  thinking_binding_mismatch='different conversation' in str(detail.get('message')))
                    headers = getattr(getattr(error, 'response', None), 'headers', {}) or {}
                    retry = headers.get('retry-after')
                    record['upstream_request_id'] = headers.get('request-id')
                    self.error(status, kind, 'Anthropic API error (%s): %s' % (kind, str(detail.get('message'))[:1000]),
                               {'Retry-After': retry} if retry else None)
                else:
                    # No HTTP answer at all (connection, TLS or timeout): a retryable gateway error.
                    record.update(http=502, upstream_error='connection')
                    self.error(502, 'api_connection_error', 'The Anthropic API could not be reached ('
                               + type(error).__name__ + ')')
            except (BrokenPipeError, ConnectionResetError):
                record['status'] = 'client_disconnect'
        finally:
            if stream is not None:
                try:
                    stream.close()
                except Exception:
                    pass
            if reply is not None:
                if reply.usage:
                    record['usage'] = reply.usage_record()
                record.update(stop_reason=reply.stop_reason, upstream_model=reply.model,
                              thinking_blocks_dropped=reply.dropped_thinking(),
                              input_transformations=len(reply.transformations))
                if reply.stop_reason == 'refusal' and isinstance(reply.stop_details, dict):
                    record['refusal_category'] = reply.stop_details.get('category')
            record.update(finished_at=time.time(), duration_s=round(time.time() - record['at'], 3))
            server.audit(record)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter,
                                     allow_abbrev=False)
    parser.add_argument('--anthropic-key-file', type=Path,
                        help='Owner-only file holding the Anthropic API key (otherwise ANTHROPIC_API_KEY of this process)')
    parser.add_argument('--key-file', type=Path, required=True,
                        help='Local gateway key file; created with one random key when missing')
    parser.add_argument('--port', type=int, default=18470)
    parser.add_argument('--log', type=Path, help='Metadata-only JSONL log; never bodies, headers or keys')
    parser.add_argument('--cache-ttl', choices=('5m', '1h'), default='5m', help='Prompt-cache lifetime (default 5m)')
    parser.add_argument('--thinking-prefix-mismatch', choices=('error', 'drop_block', 'api_default'), default='error',
                        help='What the API does with a replayed thinking block whose history changed (default error)')
    parser.add_argument('--compaction-tool-choice', choices=('none', 'auto'), default='none',
                        help='tool_choice for a Codex request that declares no tools, such as compaction (default none)')
    parser.add_argument('--state-dir', type=Path,
                        help='Private folder remembering each session\'s tool definitions across a gateway restart')
    parser.add_argument('--upstream-base-url', default=UPSTREAM, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if os.environ.get('ANTHROPIC_AUTH_TOKEN'):
        parser.error('Unset ANTHROPIC_AUTH_TOKEN: this gateway uses exactly one API key')
    if args.anthropic_key_file:
        path = args.anthropic_key_file
        read_key = lambda: read_secret(path, 'Anthropic key file')
    else:
        value = os.environ.pop('ANTHROPIC_API_KEY', '').strip()
        if not value:
            parser.error('Give --anthropic-key-file or set ANTHROPIC_API_KEY for this process')
        read_key = lambda: value
    if not args.key_file.exists():
        create_key_file(args.key_file)
    server = Gateway(('127.0.0.1', args.port), read_key, load_keys(args.key_file), log=args.log,
                     cache_ttl=args.cache_ttl, mismatch=args.thinking_prefix_mismatch,
                     compaction_tool_choice=args.compaction_tool_choice, upstream=args.upstream_base_url,
                     state_dir=args.state_dir)
    print(json.dumps({'listening': list(server.server_address), 'model': MODEL, 'transport_revision': REVISION,
                      'cache_ttl': args.cache_ttl, 'thinking_prefix_mismatch': args.thinking_prefix_mismatch,
                      'key_labels': sorted(server.keys)}), flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
