"""Host-owned Gemini HTTP relay. Real credentials never enter a CLI or policy shell.

The CLI uses a random per-process placeholder key. Only this loopback listener
accepts it; the policy sandbox must deny loopback (checked by check_policy_env).
No redirect, request log, exception text or provider response body is recorded.
"""
import http.server
import secrets
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class Gateway:
    def __init__(self, base_url, key):
        self.placeholder = secrets.token_urlsafe(32)
        self.base_url = base_url.rstrip('/')
        self.key = key
        owner = self
        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = 'HTTP/1.0'
            def log_message(self, *args):
                pass

            def do_POST(self):
                parts = urlsplit(self.path)
                query = dict(parse_qsl(parts.query))
                supplied = self.headers.get('x-goog-api-key') or query.pop('key', None)
                if supplied != owner.placeholder or not parts.path.startswith('/v1beta/models/'):
                    self.send_error(403)
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 64 * 1024 * 1024:
                        raise ValueError('Invalid request size')
                    body = self.rfile.read(length)
                    path = urlunsplit(('', '', parts.path, urlencode(query), ''))
                    request = urllib.request.Request(owner.base_url + path, data=body,
                        headers={'Content-Type': 'application/json', 'x-goog-api-key': owner.key})
                    opener = urllib.request.build_opener(_NoRedirect())
                    try:
                        response = opener.open(request, timeout=300)
                    except urllib.error.HTTPError as error:
                        # Preserve status for native error classification; do not relay a
                        # provider body which could echo credentials or internal addresses.
                        self.send_error(error.code if 400 <= error.code <= 599 else 502)
                        return
                    with response:
                        self.send_response(response.status)
                        self.send_header('Content-Type', response.headers.get('Content-Type', 'application/json'))
                        self.end_headers()
                        while block := response.read1(65536):
                            self.wfile.write(block)
                            self.wfile.flush()
                except (OSError, ValueError, urllib.error.URLError):
                    self.close_connection = True
        self.server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.daemon_threads = True
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def start(self):
        self.thread.start()
        return self

    @property
    def url(self):
        return 'http://127.0.0.1:' + str(self.server.server_port)

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)
        self.key = None
