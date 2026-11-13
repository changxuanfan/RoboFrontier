"""Standalone, loopback-only HTTP transport to GitHub Copilot model endpoints.

Python standard library only; no Copilot CLI, agent loop, or stored conversations.
Run this file directly on Windows, macOS, or Linux. Credentials stay in a private
file or the process environment, never command-line arguments or request logs.
"""
import argparse
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import sys
import threading
import time
from urllib.parse import unquote, urlsplit

UPSTREAM = 'api.githubcopilot.com'
MAX_BODY = 64 * 1024 * 1024
ROUTES = {'GET': {'/models'}, 'POST': {'/chat/completions', '/responses', '/responses/compact'}}
HEADERS = {
    'Content-Type': 'application/json', 'Accept-Encoding': 'identity',
    'Copilot-Integration-Id': 'vscode-chat', 'X-GitHub-Api-Version': '2025-04-01',
    'Editor-Version': 'vscode/1.93.0', 'Editor-Plugin-Version': 'copilot-chat/0.26.7',
    'User-Agent': 'GitHubCopilotChat/0.26.7', 'OpenAI-Intent': 'conversation-panel',
    'X-Initiator': 'agent', 'Copilot-Vision-Request': 'true',
}


def json_schema(value):
    """Translate GenAI's schema spelling without changing tool semantics."""
    if isinstance(value, list):
        return [json_schema(item) for item in value]
    if not isinstance(value, dict):
        return value
    result = {}
    for key, child in value.items():
        if key == 'propertyOrdering':
            continue
        if key == 'type' and isinstance(child, str):
            child = child.lower()
        elif key in ('minLength', 'maxLength', 'minItems', 'maxItems', 'minProperties', 'maxProperties') and isinstance(child, str):
            child = int(child)
        if key in ('properties', '$defs', 'definitions', 'patternProperties') and isinstance(child, dict):
            result[key] = {name: json_schema(schema) for name, schema in child.items()}
        elif key in ('enum', 'default', 'const', 'examples'):
            result[key] = child
        else:
            result[key] = json_schema(child)
    if result.pop('nullable', False):
        if isinstance(result.get('type'), str):
            result['type'] = [result['type'], 'null']
        else:
            result = {'anyOf': [result, {'type': 'null'}]}
    return result


def image_part(part):
    inline = part.get('inlineData', part.get('inline_data'))
    if not isinstance(inline, dict):
        raise ValueError('Only inline GenAI images are supported; file/audio/video inputs are not fetched')
    mime, data = inline.get('mimeType', inline.get('mime_type', '')), inline.get('data')
    if not mime.startswith('image/') or not isinstance(data, str) or not data:
        raise ValueError('Expected a nonempty inline image with an image MIME type')
    return {'type': 'image_url', 'image_url': {'url': 'data:' + mime + ';base64,' + data}}


def genai_to_chat(payload, model, stream):
    """Stateless protocol conversion, including images attached to tool results."""
    if any(payload.get(key) for key in ('cachedContent', 'safetySettings')):
        raise ValueError('cachedContent and safetySettings overrides are not supported by this transport')
    messages, pending = [], []
    system = payload.get('systemInstruction', payload.get('system_instruction', {}))
    if system:
        parts = system.get('parts', [])
        if any('text' not in part for part in parts):
            raise ValueError('GenAI system instructions must contain text')
        text = '\n'.join(part['text'] for part in parts)
        if text:
            messages.append({'role': 'system', 'content': text})
    for turn, content in enumerate(payload.get('contents', [])):
        role, parts = content.get('role', 'user'), content.get('parts', [])
        if role == 'model':
            texts, thoughts, calls = [], [], []
            for index, part in enumerate(parts):
                if 'functionCall' in part:
                    call = part['functionCall']
                    call_id = call.get('id') or 'call_' + str(turn) + '_' + str(index)
                    pending.append((call_id, call['name']))
                    calls.append({'id': call_id, 'type': 'function', 'function': {
                        'name': call['name'], 'arguments': json.dumps(call.get('args', {}), ensure_ascii=False)}})
                elif 'text' in part:
                    (thoughts if part.get('thought') else texts).append(part['text'])
                else:
                    raise ValueError('Unsupported GenAI model content part')
            message = {'role': 'assistant', 'content': ''.join(texts) or None}
            if thoughts:
                message['reasoning_content'] = ''.join(thoughts)
            if calls:
                message['tool_calls'] = calls
            messages.append(message)
        elif role == 'user':
            user_parts = []
            for part in parts:
                if 'functionResponse' in part:
                    result = part['functionResponse']
                    match = next((item for item in pending if
                                  (item[0] == result['id'] if result.get('id') else item[1] == result['name'])), None)
                    if match is None:
                        raise ValueError('GenAI tool result does not match a preceding function call')
                    pending.remove(match)
                    messages.append({'role': 'tool', 'tool_call_id': match[0],
                                     'content': json.dumps(result.get('response', {}), ensure_ascii=False)})
                    attachments = result.get('parts', [])
                    if attachments:
                        user_parts.append({'type': 'text', 'text': 'Images returned by tool ' + result['name'] + ' (call ' + match[0] + '):'})
                        user_parts.extend(image_part(item) for item in attachments)
                elif 'text' in part:
                    user_parts.append({'type': 'text', 'text': part['text']})
                else:
                    user_parts.append(image_part(part))
            # OpenAI tool messages are text-only. Put their image attachments in
            # a user image message after all results of this parallel tool group.
            if user_parts:
                if pending:
                    raise ValueError('GenAI tool images arrived before all parallel tool results')
                messages.append({'role': 'user', 'content': user_parts})
        else:
            raise ValueError('Unsupported GenAI conversation role')
    if pending:
        raise ValueError('GenAI history has unanswered function calls')
    request = {'model': model, 'messages': messages, 'stream': stream}
    if stream:
        request['stream_options'] = {'include_usage': True}
    declarations = [item for tool in payload.get('tools', []) for item in tool.get('functionDeclarations', [])]
    if any(set(tool) - {'functionDeclarations'} for tool in payload.get('tools', [])):
        raise ValueError('Only GenAI function declarations are supported')
    if declarations:
        request['tools'] = [{'type': 'function', 'function': {
            'name': item['name'], 'description': item.get('description', ''),
            'parameters': json_schema(item.get('parametersJsonSchema', item.get('parameters', {'type': 'object'})))}}
            for item in declarations]
        calling = payload.get('toolConfig', {}).get('functionCallingConfig', {})
        mode = calling.get('mode', 'AUTO')
        if mode not in ('AUTO', 'NONE', 'ANY'):
            raise ValueError('Unsupported GenAI function calling mode')
        allowed = calling.get('allowedFunctionNames')
        if allowed:
            request['tools'] = [tool for tool in request['tools'] if tool['function']['name'] in allowed]
            if len(request['tools']) != len(set(allowed)):
                raise ValueError('Unknown allowed GenAI function name')
        request['tool_choice'] = {'AUTO': 'auto', 'NONE': 'none', 'ANY': 'required'}[mode]
    config = payload.get('generationConfig', {})
    fields = {'maxOutputTokens': 'max_completion_tokens', 'temperature': 'temperature', 'topP': 'top_p', 'stopSequences': 'stop'}
    supported = set(fields) | {'thinkingConfig', 'responseMimeType', 'responseSchema', 'responseJsonSchema', 'candidateCount'}
    if set(config) - supported or config.get('candidateCount', 1) != 1:
        raise ValueError('Unsupported GenAI generation configuration')
    request.update({target: config[source] for source, target in fields.items() if source in config})
    thinking = config.get('thinkingConfig', {})
    if 'thinkingBudget' in thinking:
        raise ValueError('Use thinkingLevel; an exact thinkingBudget cannot be preserved on Chat Completions')
    if thinking.get('thinkingLevel'):
        request['reasoning_effort'] = thinking['thinkingLevel'].lower()
    schema = config.get('responseJsonSchema', config.get('responseSchema'))
    if schema:
        request['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'response', 'schema': json_schema(schema)}}
    elif config.get('responseMimeType') == 'application/json':
        request['response_format'] = {'type': 'json_object'}
    elif config.get('responseMimeType', 'text/plain') != 'text/plain':
        raise ValueError('Unsupported GenAI response MIME type')
    return request


def usage_metadata(usage):
    result = {target: usage[source] for source, target in (
        ('prompt_tokens', 'promptTokenCount'), ('completion_tokens', 'candidatesTokenCount'), ('total_tokens', 'totalTokenCount')) if source in usage}
    details = usage.get('completion_tokens_details') or {}
    if 'reasoning_tokens' in details:
        result['thoughtsTokenCount'] = details['reasoning_tokens']
    return result


def genai_candidate(parts, finish=None):
    candidate = {'index': 0, 'content': {'role': 'model', 'parts': parts}}
    if finish:
        try:
            candidate['finishReason'] = {'stop': 'STOP', 'tool_calls': 'STOP', 'length': 'MAX_TOKENS', 'content_filter': 'SAFETY'}[finish]
        except KeyError:
            raise ValueError('Unsupported upstream finish reason') from None
    return {'candidates': [candidate]}


def message_parts(message):
    parts = []
    if message.get('reasoning_content'):
        parts.append({'text': message['reasoning_content'], 'thought': True})
    if message.get('content'):
        parts.append({'text': message['content']})
    for call in message.get('tool_calls', []):
        function = call['function']
        args = json.loads(function['arguments'])
        if not isinstance(args, dict):
            raise ValueError('Upstream function arguments must be a JSON object')
        parts.append({'functionCall': {'id': call['id'], 'name': function['name'], 'args': args}})
    return parts


def genai_response(document):
    choice = document['choices'][0]
    result = genai_candidate(message_parts(choice['message']), choice['finish_reason'])
    if document.get('usage'):
        result['usageMetadata'] = usage_metadata(document['usage'])
    return result


def sse_documents(response):
    data = []
    for raw in response:
        line = raw.decode('utf-8').rstrip('\r\n')
        if not line:
            if data:
                value = '\n'.join(data)
                if value == '[DONE]':
                    return
                yield json.loads(value)
                data = []
        elif line.startswith('data:'):
            data.append(line[5:].lstrip(' '))
    if data:
        raise ValueError('Truncated upstream SSE event')


def genai_stream(response):
    calls, finish, usage = {}, None, None
    for document in sse_documents(response):
        if 'error' in document:
            raise ValueError('Upstream returned an in-stream error')
        if document.get('usage'):
            usage = usage_metadata(document['usage'])
        choices = document.get('choices', [])
        if not choices:
            continue
        choice = choices[0]
        delta = choice.get('delta', {})
        for source, thought in (('reasoning_content', True), ('content', False)):
            if delta.get(source):
                part = {'text': delta[source]}
                if thought:
                    part['thought'] = True
                yield genai_candidate([part])
        for item in delta.get('tool_calls', []):
            entry = calls.setdefault(item['index'], {'id': '', 'function': {'name': '', 'arguments': ''}})
            entry['id'] += item.get('id', '')
            for key in ('name', 'arguments'):
                entry['function'][key] += item.get('function', {}).get(key, '')
        if choice.get('finish_reason'):
            finish = choice['finish_reason']
    if finish is None:
        raise ValueError('Upstream stream ended without a finish reason')
    result = genai_candidate(message_parts({'tool_calls': [calls[index] for index in sorted(calls)]}), finish)
    if usage:
        result['usageMetadata'] = usage
    yield result


def read_token(token_file=None):
    try:
        value = (Path(token_file).read_text(encoding='utf-8-sig') if token_file
                 else os.environ.get('ROBOFRONTIER_GITHUB_PAT', '')).strip()
    except OSError:
        raise ValueError('Cannot read the PAT file') from None
    if not value or any(c.isspace() for c in value):
        raise ValueError('Set ROBOFRONTIER_GITHUB_PAT or provide a file containing one PAT')
    return value


def headers(token, stream=False):
    return {**HEADERS, 'Authorization': 'Bearer ' + token,
            'Accept': 'text/event-stream' if stream else 'application/json'}


def connect():
    return http.client.HTTPSConnection(UPSTREAM, timeout=1800, context=ssl.create_default_context())


class Gateway(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, token_file=None, flash_helper=False, log_file=None):
        self.token_file, self.flash_helper, self.log_file = token_file, flash_helper, log_file
        self.log_lock = threading.Lock()
        self.upstream_connection = connect
        read_token(token_file)
        super().__init__(address, Handler)

    def record(self, value):
        if self.log_file:
            with self.log_lock, open(self.log_file, 'a', encoding='utf-8') as output:
                output.write(json.dumps(value) + '\n')


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'
    server_version = 'GitHubPATGateway'
    sys_version = ''

    def log_message(self, *args):
        pass

    def reply(self, status, value):
        body = json.dumps(value).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        self.wfile.write(body)

    def error(self, status, message):
        self.reply(status, {'error': {'message': message}})

    def handle_api(self):
        path = self.path[3:] if self.path.startswith('/v1/') else self.path
        genai = re.fullmatch(r'/v1beta/models/([^/:]+):(streamGenerateContent|generateContent)', unquote(urlsplit(path).path)) if self.command == 'POST' else None
        if self.command == 'GET' and path == '/healthz':
            return self.reply(200, {'ready': True, 'upstream': UPSTREAM,
                                    'scope': 'Local transport ready; not an upstream credential check'})
        if path not in ROUTES[self.command] and not genai:
            return self.error(404, 'Unsupported model endpoint')
        try:
            token = read_token(self.server.token_file)
        except ValueError:
            return self.error(503, 'PAT configuration is unavailable')
        supplied = self.headers.get('Authorization', '')
        if genai and not supplied and self.headers.get('x-goog-api-key'):
            supplied = 'Bearer ' + self.headers['x-goog-api-key']
        if not hmac.compare_digest(supplied.encode(), ('Bearer ' + token).encode()):
            return self.error(401, 'Gateway authentication required')
        body, payload = b'', {}
        if self.command == 'POST':
            if self.headers.get('Transfer-Encoding'):
                return self.error(400, 'Chunked request bodies are unsupported')
            try:
                length = int(self.headers['Content-Length'])
            except (KeyError, TypeError, ValueError):
                return self.error(411, 'A valid Content-Length is required')
            if not 0 < length <= MAX_BODY:
                return self.error(413, 'Request body is empty or too large')
            body = self.rfile.read(length)
            try:
                payload = json.loads(body)
            except (ValueError, UnicodeError):
                return self.error(400, 'Invalid JSON')
            if not isinstance(payload, dict):
                return self.error(400, 'Expected a JSON object')
            if genai:
                try:
                    payload = genai_to_chat(payload, genai[1], genai[2] == 'streamGenerateContent')
                except (KeyError, TypeError, ValueError, AttributeError):
                    return self.error(400, 'Invalid or unsupported GenAI request configuration or content')
                path = '/chat/completions'
                body = json.dumps(payload).encode()
            if self.server.flash_helper and path == '/chat/completions':
                changed = False
                if payload.get('model') == 'gemini-3.1-flash-lite-preview':
                    payload.update(model='gemini-3.8-flash', reasoning_effort='low')
                    changed = True
                elif payload.get('model') == 'gemini-3.8-flash' and payload.get('reasoning_effort') == 'minimal':
                    payload['reasoning_effort'] = 'low'
                    changed = True
                if changed:
                    body = json.dumps(payload).encode()
        record = {'at': time.time(), 'path': path, 'model': payload.get('model'),
                  'wire_protocol': 'genai' if genai else 'openai',
                  'reasoning_effort': payload.get('reasoning_effort'),
                  'max_completion_tokens': payload.get('max_completion_tokens'),
                  'response_format': (payload.get('response_format') or {}).get('type'),
                  'message_shapes': [{'role': message.get('role'), 'parts': len(message['content']) if isinstance(message.get('content'), list) else None,
                                      'empty': not message.get('content')} for message in payload.get('messages', [])],
                  'image_parts': sum(part.get('type') == 'image_url' for message in payload.get('messages', [])
                                     if isinstance(message.get('content'), list) for part in message['content'])}
        connection, sent = None, False
        try:
            connection = self.server.upstream_connection()
            connection.request(self.command, path, body=body or None,
                               headers=headers(token, payload.get('stream', False)))
            response = connection.getresponse()
            record['http'] = response.status
            if genai and response.status == 200 and not payload['stream']:
                try:
                    result = genai_response(json.load(response))
                except (KeyError, TypeError, ValueError, IndexError):
                    return self.error(502, 'Invalid upstream model response')
                return self.reply(200, result)
            self.send_response(response.status)
            self.send_header('Content-Type', 'text/event-stream' if genai and response.status == 200 else response.getheader('Content-Type', 'application/json'))
            self.send_header('Connection', 'close')
            for name in ('Retry-After', 'x-request-id'):
                if response.getheader(name):
                    self.send_header(name, response.getheader(name))
            self.end_headers()
            sent, self.close_connection = True, True
            if genai and response.status == 200:
                try:
                    for item in genai_stream(response):
                        self.wfile.write(('data: ' + json.dumps(item) + '\n\n').encode())
                        self.wfile.flush()
                except (KeyError, TypeError, ValueError, IndexError):
                    record['error_type'] = 'InvalidUpstreamStream'
                    self.wfile.write(b'data: {"error":{"code":502,"status":"INTERNAL","message":"Invalid or incomplete upstream model stream"}}\n\n')
                    self.wfile.flush()
            else:
                while chunk := response.read1(16384):
                    self.wfile.write(chunk)
                    self.wfile.flush()
        except (OSError, http.client.HTTPException) as exc:
            record['error_type'] = type(exc).__name__
            if not sent:
                self.error(502, 'Upstream model transport failed')
        finally:
            if connection:
                connection.close()
            record['finished_at'] = time.time()
            self.server.record(record)

    do_GET = handle_api
    do_POST = handle_api


def list_models(token_file):
    connection = connect()
    try:
        connection.request('GET', '/models', headers=headers(read_token(token_file)))
        response = connection.getresponse()
        if response.status != 200:
            raise ValueError('GitHub model catalog returned HTTP ' + str(response.status))
        document = json.load(response)
        return [{'id': row['id'], 'supported_endpoints': row.get('supported_endpoints', [])}
                for row in document['data']]
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file', type=Path, help='Private PAT file; reread for every request')
    parser.add_argument('--port', type=int, default=18450)
    parser.add_argument('--flash-helper', action='store_true', help='Map Antigravity Flash Lite to Flash/LOW and Flash minimal to low')
    parser.add_argument('--log-file', type=Path, help='Optional metadata-only JSONL; no prompts or credentials')
    parser.add_argument('--list-models', action='store_true', help='Call GitHub and print the current account model IDs/endpoints')
    args = parser.parse_args()
    os.umask(0o077)
    try:
        if args.list_models:
            print(json.dumps(list_models(args.token_file), indent=2))
            return
        if not 1 <= args.port <= 65535:
            parser.error('--port must be 1..65535')
        with Gateway(('127.0.0.1', args.port), args.token_file, args.flash_helper, args.log_file) as server:
            print('GitHub PAT gateway listening on http://127.0.0.1:' + str(args.port), flush=True)
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                pass
    except (OSError, ValueError) as exc:
        # These messages contain configuration/transport failures, never credentials.
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
