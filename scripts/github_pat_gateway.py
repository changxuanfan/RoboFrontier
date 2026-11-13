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
import ssl
import sys
import threading
import time

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
        if self.command == 'GET' and path == '/healthz':
            return self.reply(200, {'ready': True, 'upstream': UPSTREAM,
                                    'scope': 'Local transport ready; not an upstream credential check'})
        if path not in ROUTES[self.command]:
            return self.error(404, 'Unsupported model endpoint')
        try:
            token = read_token(self.server.token_file)
        except ValueError:
            return self.error(503, 'PAT configuration is unavailable')
        if not hmac.compare_digest(self.headers.get('Authorization', '').encode(), ('Bearer ' + token).encode()):
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
        record = {'at': time.time(), 'path': path, 'model': payload.get('model')}
        connection, sent = None, False
        try:
            connection = self.server.upstream_connection()
            connection.request(self.command, path, body=body or None,
                               headers=headers(token, payload.get('stream', False)))
            response = connection.getresponse()
            record['http'] = response.status
            self.send_response(response.status)
            self.send_header('Content-Type', response.getheader('Content-Type', 'application/json'))
            self.send_header('Connection', 'close')
            for name in ('Retry-After', 'x-request-id'):
                if response.getheader(name):
                    self.send_header(name, response.getheader(name))
            self.end_headers()
            sent, self.close_connection = True, True
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
