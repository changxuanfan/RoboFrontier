"""Connection-local Responses state; native Claude sessions remain independent."""

import hashlib
import json
import secrets
import ssl
import threading
import time
from collections import deque
from contextlib import contextmanager, nullcontext

MODEL = 'gpt-6.1-sol'


class ProtocolError(ValueError):
    pass


class UpstreamError(ProtocolError):
    def __init__(self, code, param=None, status=None):
        self.code, self.param, self.status = code, param, status
        super().__init__('Upstream request did not complete: ' + str(code))


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


class Channel:
    def __init__(self):
        self.lock = threading.Lock()
        self.socket = None
        self.born = 0
        self.token_digest = None
        self.generation = None
        self.prefix = ()
        self.settings = None
        self.response_id = None
        self.last_request = None
        self.last_result = None

    def disconnect(self):
        socket, self.socket = self.socket, None
        self.prefix, self.settings, self.response_id = (), None, None
        if socket is not None:
            socket.close()


class Admission:
    """A shared FIFO token reservation window; waiting never holds a model connection."""

    def __init__(self, tokens_per_minute, reservation=428000, concurrency=4, window=60):
        if tokens_per_minute < reservation or reservation <= 0 or concurrency < 1 or window <= 0:
            raise ValueError('Invalid API token admission settings')
        self.limit, self.reservation, self.concurrency, self.window = (
            tokens_per_minute,
            reservation,
            concurrency,
            window,
        )
        self.condition = threading.Condition()
        self.queue = deque()
        self.sent = deque()
        self.active = 0

    @contextmanager
    def reserve(self, cancelled, record):
        ticket = object()
        began = time.monotonic()
        admitted = False
        with self.condition:
            self.queue.append(ticket)
            try:
                while True:
                    if cancelled.is_set():
                        raise ConnectionResetError('Client disconnected while waiting for API admission')
                    now = time.monotonic()
                    while self.sent and self.sent[0][0] <= now - self.window:
                        self.sent.popleft()
                    if (
                        self.queue[0] is ticket
                        and self.active < self.concurrency
                        and sum(v for _, v in self.sent) + self.reservation <= self.limit
                    ):
                        self.queue.popleft()
                        self.sent.append((now, self.reservation))
                        self.active += 1
                        admitted = True
                        record.update(
                            api_admission_wait_s=now - began,
                            api_reserved_tokens=self.reservation,
                            api_token_budget_per_minute=self.limit,
                        )
                        self.condition.notify_all()
                        break
                    self.condition.wait(0.25)
            finally:
                if not admitted:
                    self.queue.remove(ticket)
                    self.condition.notify_all()
        try:
            yield
        finally:
            with self.condition:
                self.active -= 1
                self.condition.notify_all()


class WebSocketTransport:
    """One socket per native session: forks never wait for a blocked parent turn."""

    def __init__(self, store, connector=None, timeout=600, max_age=55 * 60, max_sessions=256, admission=None):
        self.store = store
        self.connect = connector or self.open_socket
        self.timeout, self.max_age, self.max_sessions = timeout, max_age, max_sessions
        self.channels = {}
        self.lock = threading.Lock()
        self.closed = False
        self.admission = admission

    @staticmethod
    def open_socket(token):
        from websockets.exceptions import InvalidStatus
        from websockets.sync.client import connect

        try:
            return connect(
                'wss://api.openai.com/v1/responses',
                ssl=ssl.create_default_context(),
                additional_headers={'Authorization': 'Bearer ' + token},
                open_timeout=30,
                close_timeout=5,
                max_size=256 * 1024 * 1024,
                legacy=True,
            )
        except InvalidStatus as error:
            status = error.response.status_code
            code, param = 'websocket_handshake_rejected', None
            try:
                document = json.loads(error.response.body)
                detail = document.get('error') or {}
                code, param = detail.get('code') or code, detail.get('param')
            except (ValueError, TypeError, AttributeError):
                pass
            raise UpstreamError(code, param, status) from None

    def close(self):
        with self.lock:
            self.closed = True
            channels = list(self.channels.values())
        for channel in channels:
            channel.disconnect()

    def channel(self, session):
        with self.lock:
            if self.closed:
                raise ProtocolError('WebSocket transport has closed')
            if session is None:
                return Channel()
            if session not in self.channels:
                if len(self.channels) >= self.max_sessions:
                    raise ProtocolError(
                        'WebSocket session capacity reached; restart with saved native histories'
                    )
                self.channels[session] = Channel()
            return self.channels[session]

    def receive(self, socket, cancelled, record=None):
        deadline, identity, started = time.monotonic() + self.timeout, None, False
        while True:
            if cancelled.is_set():
                raise ConnectionResetError('Client disconnected before completion')
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError('Responses WebSocket completion timed out')
            try:
                event = json.loads(socket.recv(timeout=min(1, remaining)))
            except TimeoutError:
                continue
            kind = event.get('type')
            if record is not None:
                record['ws_last_event'] = kind
            if kind in ('error', 'response.failed', 'response.incomplete'):
                error = event.get('error') or (event.get('response') or {}).get('error') or {}
                failure = UpstreamError(error.get('code') or kind, error.get('param'))
                failure.response_started = started
                raise failure
            response = event.get('response') or {}
            event_id = event.get('response_id') or response.get('id')
            if identity is not None and event_id is not None and identity != event_id:
                raise ProtocolError('WebSocket event belongs to another response')
            if kind == 'response.created':
                if started:
                    raise ProtocolError('Duplicate WebSocket response.created')
                identity, started = event_id, True
                if record is not None:
                    record['ws_response_started'] = True
            elif kind and kind.startswith('response.output'):
                started = True
                if record is not None:
                    record['ws_response_started'] = True
            if kind == 'response.completed':
                if response.get('status') != 'completed' or response.get('model') != MODEL:
                    raise ProtocolError('WebSocket response incomplete or returned a different model')
                if not response.get('id'):
                    raise ProtocolError('WebSocket completion lacks a response identity')
                return response

    @contextmanager
    def exchange(self, request, cancelled, record):
        history = request['input']
        session = getattr(history, 'session_id', None)
        channel = self.channel(session)
        while not channel.lock.acquire(timeout=0.1):
            if cancelled.is_set():
                raise ConnectionResetError('Client disconnected while awaiting native session')
        try:
            if cancelled.is_set():
                raise ConnectionResetError('Client disconnected before inference')
            settings = {
                key: value
                for key, value in request.items()
                if key not in ('input', 'stream', 'prompt_cache_options')
            }
            settings_digest = digest(settings)
            hashes = tuple(digest(item) for item in history)
            signature = digest([settings_digest, hashes])
            record.update(transport='responses_websocket', context_input_items=len(history))
            if signature == channel.last_request and channel.last_result is not None:
                record.update(
                    ws_mode='completed_retry',
                    wire_input_items=0,
                    upstream_sent=False,
                    ws_generation=channel.generation,
                )
                yield channel.last_result
                return
            token = self.store.access_token()
            token_digest = hashlib.sha256(token.encode()).hexdigest()
            reset = None
            if channel.socket is not None:
                if channel.token_digest != token_digest:
                    reset = 'credential_refreshed'
                elif time.monotonic() - channel.born >= self.max_age:
                    reset = 'connection_lifetime'
                elif channel.settings != settings_digest:
                    reset = 'settings_changed'
                elif len(hashes) < len(channel.prefix) or hashes[: len(channel.prefix)] != channel.prefix:
                    reset = 'history_replaced'
                if reset:
                    channel.disconnect()
            for attempt in range(2):
                reservation = (
                    self.admission.reserve(cancelled, record) if self.admission is not None else nullcontext()
                )
                try:
                    with reservation:
                        result = self._exchange_once(
                            channel, token, settings, history, cancelled, record, reset
                        )
                except UpstreamError as error:
                    if (
                        attempt == 0
                        and record.get('ws_mode') == 'incremental'
                        and error.code == 'previous_response_not_found'
                        and not error.response_started
                    ):
                        record['ws_recovery'] = 'previous_response_not_found'
                        channel.disconnect()
                        reset = 'previous_response_not_found'
                        continue
                    raise
                break
            yield result
            # Commit connection state only after translation and durable replay storage succeed.
            channel.prefix = hashes + tuple(digest(item) for item in result['output'])
            channel.settings, channel.response_id = settings_digest, result['id']
            channel.last_request, channel.last_result = signature, result
        except BaseException as error:
            # Close reasons are arbitrary peer text; retain codes and hashes, never their bodies.
            record['ws_connection_age_s'] = max(0, time.monotonic() - channel.born) if channel.born else None
            for name in ('rcvd', 'sent'):
                close = getattr(error, name, None)
                if close is not None:
                    record['ws_' + name + '_close_code'] = close.code
                    record['ws_' + name + '_reason_sha256'] = hashlib.sha256(
                        close.reason.encode()
                    ).hexdigest()
            if hasattr(error, 'rcvd_then_sent'):
                record['ws_received_close_first'] = error.rcvd_then_sent
            channel.disconnect()
            raise
        finally:
            if session is None:
                channel.disconnect()
            channel.lock.release()

    def _exchange_once(self, channel, token, settings, history, cancelled, record, reset):
        if channel.socket is not None and time.monotonic() - channel.born >= self.max_age:
            channel.disconnect()
            reset = 'connection_lifetime'
        continuing = channel.socket is not None and channel.response_id is not None
        if channel.socket is None:
            channel.socket = self.connect(token)
            channel.born, channel.token_digest = time.monotonic(), hashlib.sha256(token.encode()).hexdigest()
            channel.generation = secrets.token_hex(12)
        wire = {
            **settings,
            'type': 'response.create',
            'input': list(history[len(channel.prefix) :] if continuing else history),
        }
        if continuing:
            wire['previous_response_id'] = channel.response_id
            if not wire['input']:
                raise ProtocolError('Continuation has no new input items')
        record.update(
            ws_mode='incremental' if continuing else 'full_replay',
            ws_reset_reason=reset,
            ws_generation=channel.generation,
            previous_response_id=wire.get('previous_response_id'),
            wire_input_items=len(wire['input']),
            upstream_sent=True,
        )
        record.update(ws_request_sent=False, ws_response_started=False)
        channel.socket.send(json.dumps(wire, ensure_ascii=False))
        record['ws_request_sent'] = True
        return self.receive(channel.socket, cancelled, record)
