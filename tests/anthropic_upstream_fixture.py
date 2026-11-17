"""A local stand-in for the Anthropic Messages API: scripted SSE answers, recorded requests.

Offline only. It never contacts a model provider and accepts fake keys.
"""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading

MODEL = 'claude-opus-5-5'


def thinking(signature, text=''):
    return {'type': 'thinking', 'thinking': text, 'signature': signature}


def text(value):
    return {'type': 'text', 'text': value}


def tool_use(identity, name, arguments, raw=None):
    """`raw` is the exact JSON text streamed for the input (default: compact JSON)."""
    return {'type': 'tool_use', 'id': identity, 'name': name, 'input': arguments,
            '_raw': json.dumps(arguments) if raw is None else raw}


def usage(uncached=100, read=900, created=50, output=20, thinking_tokens=7):
    return {'input_tokens': uncached, 'cache_read_input_tokens': read, 'cache_creation_input_tokens': created,
            'cache_creation': {'ephemeral_5m_input_tokens': created, 'ephemeral_1h_input_tokens': 0},
            'output_tokens': output, 'output_tokens_details': {'thinking_tokens': thinking_tokens}}


def message_events(blocks, stop_reason='end_turn', counts=None, model=MODEL, identity='msg_stub', stop_details=None,
                   truncate=False):
    """Anthropic stream events for one assistant message."""
    counts = counts or usage()
    yield 'message_start', {'type': 'message_start', 'message': {
        'id': identity, 'type': 'message', 'role': 'assistant', 'model': model, 'content': [], 'stop_reason': None,
        'stop_sequence': None, 'usage': {**counts, 'output_tokens': 1}}}
    yield 'ping', {'type': 'ping'}
    for index, block in enumerate(blocks):
        if block['type'] == 'thinking':
            yield 'content_block_start', {'type': 'content_block_start', 'index': index,
                                          'content_block': {'type': 'thinking', 'thinking': '', 'signature': ''}}
            if block['thinking']:
                yield 'content_block_delta', {'type': 'content_block_delta', 'index': index,
                                              'delta': {'type': 'thinking_delta', 'thinking': block['thinking']}}
            yield 'content_block_delta', {'type': 'content_block_delta', 'index': index,
                                          'delta': {'type': 'signature_delta', 'signature': block['signature']}}
        elif block['type'] == 'text':
            yield 'content_block_start', {'type': 'content_block_start', 'index': index,
                                          'content_block': {'type': 'text', 'text': ''}}
            half = len(block['text']) // 2
            for piece in (block['text'][:half], block['text'][half:]):
                yield 'content_block_delta', {'type': 'content_block_delta', 'index': index,
                                              'delta': {'type': 'text_delta', 'text': piece}}
        elif block['type'] == 'tool_use':
            yield 'content_block_start', {'type': 'content_block_start', 'index': index, 'content_block': {
                'type': 'tool_use', 'id': block['id'], 'name': block['name'], 'input': {}}}
            raw = block['_raw']
            half = len(raw) // 2
            for piece in (raw[:half], raw[half:]):
                yield 'content_block_delta', {'type': 'content_block_delta', 'index': index,
                                              'delta': {'type': 'input_json_delta', 'partial_json': piece}}
        else:
            yield 'content_block_start', {'type': 'content_block_start', 'index': index, 'content_block': block}
        yield 'content_block_stop', {'type': 'content_block_stop', 'index': index}
    if truncate:
        return
    delta = {'stop_reason': stop_reason, 'stop_sequence': None}
    if stop_details is not None:
        delta['stop_details'] = stop_details
    yield 'message_delta', {'type': 'message_delta', 'delta': delta, 'usage': {'output_tokens': counts['output_tokens']}}
    yield 'message_stop', {'type': 'message_stop'}


class AnthropicStub(ThreadingHTTPServer):
    """`script(body, headers)` returns {'blocks': [...], ...} for a stream, or
    {'status': 429, 'error': {...}, 'headers': {...}} for an HTTP error."""
    daemon_threads = True

    def __init__(self, script):
        self.script, self.requests, self.lock = script, [], threading.Lock()
        super().__init__(('127.0.0.1', 0), _Handler)
        self.thread = threading.Thread(target=self.serve_forever, kwargs={'poll_interval': .02}, daemon=True)
        self.thread.start()

    @property
    def url(self):
        return 'http://127.0.0.1:%d' % self.server_port

    def close(self):
        self.shutdown()
        self.server_close()
        self.thread.join()


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers.get('Content-Length', 0))))
        headers = {name.lower(): value for name, value in self.headers.items()}
        with self.server.lock:
            self.server.requests.append({'path': self.path, 'headers': headers, 'body': body})
        answer = self.server.script(body, headers)
        if 'status' in answer:
            payload = json.dumps({'type': 'error', 'error': answer['error']}).encode()
            self.send_response(answer['status'])
            self.send_header('Content-Type', 'application/json')
            self.send_header('request-id', 'req_stub_error')
            for name, value in answer.get('headers', {}).items():
                self.send_header(name, value)
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('request-id', 'req_stub')
        self.end_headers()
        events = list(message_events(answer['blocks'], answer.get('stop_reason', 'end_turn'), answer.get('usage'),
                                     answer.get('model', MODEL), answer.get('id', 'msg_stub'),
                                     answer.get('stop_details'), answer.get('truncate', False)))
        if answer.get('stream_error'):
            events = events[:3] + [('error', {'type': 'error', 'error': answer['stream_error']})]
        for event, data in events:
            self.wfile.write(('event: %s\ndata: %s\n\n' % (event, json.dumps(data))).encode())
            self.wfile.flush()
