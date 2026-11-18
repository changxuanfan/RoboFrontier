"""Official Sign in with ChatGPT for a private, self-hosted experiment gateway."""

import argparse
import base64
import hashlib
import json
import os
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import Request, urlopen

ISSUER = 'https://auth.openai.com'
RESOURCE = 'https://api.openai.com/v1'
AUTHORIZE = ISSUER + '/api/accounts/authorize'
TOKEN = ISSUER + '/api/accounts/oauth/token'
SCOPES = 'openid model email offline_access resource.invoke chatgpt.tokens.use.direct'


def atomic_json(path, document):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + '.' + secrets.token_hex(8) + '.tmp')
    descriptor = os.open(temporary, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            json.dump(document, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        temporary.replace(path)
        if os.name != 'nt':
            path.chmod(0o600)
    finally:
        temporary.unlink(missing_ok=True)


def exchange(fields):
    request = Request(
        TOKEN, data=urlencode(fields).encode(), headers={'Content-Type': 'application/x-www-form-urlencoded'}
    )
    with urlopen(request, timeout=45) as response:
        return json.load(response)


def validate_identity(encoded, client_id, nonce=None):
    import jwt
    from jwt import PyJWKClient

    key = PyJWKClient(ISSUER + '/.well-known/jwks.json').get_signing_key_from_jwt(encoded)
    identity = jwt.decode(
        encoded,
        key.key,
        algorithms=['RS256'],
        issuer=ISSUER,
        audience=client_id,
        options={'require': ['exp', 'iat', 'iss', 'aud', 'sub']},
    )
    if nonce is not None and not secrets.compare_digest(identity.get('nonce', ''), nonce):
        raise ValueError('ID-token nonce mismatch')
    return identity


def credentials(tokens, client_id, host_id, identity, previous=None):
    scopes = tokens['scope'].split() if 'scope' in tokens else list((previous or {}).get('scopes', []))
    if 'chatgpt.tokens.use.direct' not in scopes or 'resource.invoke' not in scopes:
        raise ValueError('ChatGPT plan use was not granted; no inference is authorized')
    if not tokens.get('access_token') or not (
        tokens.get('refresh_token') or (previous or {}).get('refresh_token')
    ):
        raise ValueError('Token response is missing required credentials')
    return {
        **(previous or {}),
        **tokens,
        'client_id': client_id,
        'ext_agent_host_id': host_id,
        'issuer': ISSUER,
        'subject': identity['sub'],
        'scopes': scopes,
        'expires_at': time.time() + int(tokens['expires_in']),
        'saved_at': time.time(),
    }


class CredentialStore:
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def access_token(self, *, force_refresh=False):
        with self.lock:
            saved = json.loads(self.path.read_text(encoding='utf-8'))
            if 'chatgpt.tokens.use.direct' not in saved.get('scopes', []):
                raise ValueError('Credential is not authorized for ChatGPT plan use')
            if force_refresh or saved['expires_at'] < time.time() + 90:
                tokens = exchange(
                    {
                        'grant_type': 'refresh_token',
                        'client_id': saved['client_id'],
                        'refresh_token': saved['refresh_token'],
                        'resource': RESOURCE,
                    }
                )
                identity = {'sub': saved['subject']}
                if tokens.get('id_token'):
                    identity = validate_identity(tokens['id_token'], saved['client_id'])
                    if identity['sub'] != saved['subject']:
                        raise ValueError('Refreshed account identity changed')
                updated = credentials(tokens, saved['client_id'], saved['ext_agent_host_id'], identity, saved)
                atomic_json(self.path, updated)
                saved = updated
            return saved['access_token']


def login(path, port):
    import uuid

    path = Path(path)
    host_file = path.parent / 'host-id.json'
    if not host_file.exists():
        atomic_json(host_file, {'ext_agent_host_id': 'urn:uuid:' + str(uuid.uuid4())})
    host_id = json.loads(host_file.read_text())['ext_agent_host_id']
    previous = json.loads(path.read_text()) if path.exists() else None
    state, nonce, verifier = (secrets.token_urlsafe(48) for _ in range(3))
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    result = {}

    class Callback(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Callback URLs contain a one-use authorization code.

        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path != '/auth/callback':
                self.send_error(404)
                return
            query = parse_qs(parsed.query)
            if not secrets.compare_digest(query.get('state', [''])[0], state):
                self.send_error(400, 'Invalid authorization state')
                return
            try:
                if query.get('error'):
                    raise ValueError('Authorization declined: ' + query['error'][0])
                client = query.get('client_id', [previous['client_id'] if previous else ''])[0]
                if not client or client == 'dynamic_agent_client':
                    raise ValueError('Registration did not return an issued client ID')
                if previous and client != previous['client_id']:
                    raise ValueError('Returning registration identity changed')
                code = query.get('code', [''])[0]
                if not code:
                    raise ValueError('Authorization code missing')
                tokens = exchange(
                    {
                        'grant_type': 'authorization_code',
                        'client_id': client,
                        'code': code,
                        'code_verifier': verifier,
                        'redirect_uri': callback,
                        'resource': RESOURCE,
                    }
                )
                identity = validate_identity(tokens['id_token'], client, nonce)
                if previous and previous['subject'] != identity['sub']:
                    raise ValueError('Signed-in account differs from the selected account')
                atomic_json(path, credentials(tokens, client, host_id, identity))
                result['authenticated'] = True
                message = b'ChatGPT plan authorization completed. You can close this page and return to the experiment.'
                self.send_response(200)
            except Exception as error:
                # Never echo token exchange bodies, callback codes, or tokens.
                result['error_type'] = type(error).__name__
                self.send_response(400)
                message = (
                    b'Authorization could not be completed. Return to the experiment for a fresh sign-in.'
                )
            self.send_header('Content-Type', 'text/plain; charset=utf-8')
            self.send_header('Content-Length', str(len(message)))
            self.end_headers()
            self.wfile.write(message)

    server = HTTPServer(('127.0.0.1', port), Callback)
    server.timeout = 1
    callback = f'http://127.0.0.1:{server.server_port}/auth/callback'
    query = {
        'client_id': previous['client_id'] if previous else 'dynamic_agent_client',
        'ext_agent_host_id': host_id,
        'response_type': 'code',
        'redirect_uri': callback,
        'scope': SCOPES,
        'resource': RESOURCE,
        'state': state,
        'nonce': nonce,
        'code_challenge_method': 'S256',
        'code_challenge': challenge,
    }
    if previous:
        if previous.get('id_token'):
            query['id_token_hint'] = previous['id_token']
    else:
        query['agent_name_hint'] = 'RoboTeam Claude GPT Ablation'
    # Never print an id_token_hint while reauthorizing a saved account.
    if previous:
        raise ValueError('Use a new protected account file for interactive account selection')
    print(
        json.dumps(
            {
                'event': 'login_required',
                'url': AUTHORIZE + '?' + urlencode(query),
                'callback_ready': callback,
                'expires_in_seconds': 1800,
            }
        ),
        flush=True,
    )
    deadline = time.monotonic() + 1800
    try:
        while not result and time.monotonic() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not result:
        raise TimeoutError('Interactive sign-in expired; start a fresh attempt')
    print(json.dumps(result), flush=True)
    if not result.get('authenticated'):
        raise RuntimeError('Interactive sign-in failed: ' + result['error_type'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['login', 'status'])
    parser.add_argument('--credential-file', type=Path, required=True)
    parser.add_argument('--port', type=int, default=18767)
    args = parser.parse_args()
    if args.action == 'login':
        login(args.credential_file, args.port)
    else:
        saved = json.loads(args.credential_file.read_text())
        print(
            json.dumps(
                {
                    'authenticated': 'chatgpt.tokens.use.direct' in saved.get('scopes', []),
                    'expires_at': saved.get('expires_at'),
                    'scopes': saved.get('scopes'),
                }
            )
        )


if __name__ == '__main__':
    main()
