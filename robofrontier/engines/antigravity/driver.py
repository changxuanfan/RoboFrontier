"""Persistent Antigravity transport with no model input before native ID binding."""
import json
import math
import os
from pathlib import Path
import queue
import re
import secrets
import signal
import shutil
import sqlite3
import subprocess
import threading
import time
import uuid
import urllib.request

from .gateway import Gateway
from .profile import validate
from .auth import environment_home, home_directory
from .settings import cli_workspace, configure
from robofrontier.runtime.setup import write_json
from robofrontier.engines.common.native import PreLaunchCancelled

CAPACITY_CODES = frozenset(('RESOURCE_EXHAUSTED', 'UNAVAILABLE', 'rate_limit', 'server_overloaded'))
USAGE_KEYS = ('input_tokens', 'output_tokens', 'thinking_tokens', 'cache_read_tokens')
USER_INPUT_STEP = 14  # Native step type of one user input (native_turn.completed requires it).


class ForkUnacknowledged(ValueError):
    """The fork RPC named a child session but did not acknowledge the bound step."""
    def __init__(self, child):
        super().__init__('Native fork did not acknowledge the bound step')
        self.child = child


def usage_baseline(rows):
    """Counters a session starts from: what its (possibly inherited) transcript already holds.

    A fork child's counters continue its parent's. Transcript rows carry no thinking
    count, so an inherited thinking total is unknown, not zero."""
    return {key: sum(r.get(key, 0) for r in rows) if not rows or any(key in r for r in rows) else None
            for key in USAGE_KEYS}


def usage_delta(raw, previous):
    """(this turn's share, new running totals) from the CLI's cumulative counters.

    A counter the result leaves out keeps its previous total, so a later result is
    not charged the whole session again."""
    raw = raw if isinstance(raw, dict) else {}
    delta, totals = {}, dict(previous)
    for key in USAGE_KEYS:
        value, before = raw.get(key), previous.get(key)
        if type(value) not in (int, float):
            delta[key] = None
            continue
        totals[key] = value
        delta[key] = value-before if type(before) in (int, float) and value >= before else None
    return delta, totals


def native_id(value):
    if not isinstance(value, str) or str(uuid.UUID(value)) != value:
        raise ValueError('Expected native session UUID')
    return value


def summarize(events, session):
    """Only CLI result/error fields classify failures; model text is never evidence."""
    results = [e['result'] for e in events if e.get('event') == 'result' and isinstance(e.get('result'), dict)]
    if len(results) != 1:
        return {'session_id': session, 'turn_status': 'unknown', 'malformed_lines': 0}
    result = results[0]
    same = result.get('conversation_id') == session
    success = result.get('status') == 'SUCCESS' and not result.get('denied_actions')
    error = result.get('error')
    code = error.get('code') if isinstance(error, dict) else None
    # RESOURCE_EXHAUSTED may mean a plan limit, a daily API quota or temporary
    # capacity. It is deliberately not retried without a precise native subtype.
    capacity = code if code in ('rate_limit', 'server_overloaded') else None
    return {'session_id': result.get('conversation_id'),
            'turn_status': ('ended' if success else 'failed') if same else 'unknown',
            'result_subtype': 'success' if success else 'error_during_execution',
            'capacity_error_code': capacity, 'usage': result.get('usage'),
            'total_cost_usd': None, 'malformed_lines': 0,
            'response': result.get('response'), 'duration_seconds': result.get('duration_seconds'),
            'denied_actions': result.get('denied_actions')}


class Driver:
    def __init__(self, run, actor, profile, base_env, *, binary='agy', session=None, python=None, gateway_factory=Gateway):
        self.run = Path(run).resolve()
        self.actor = actor
        self.profile = validate(profile)
        self.binary = binary
        self.session = native_id(session) if session else None
        self.base_env = dict(base_env)
        self.python = python
        self.gateway_factory = gateway_factory
        self.process = None
        self.gateway = None
        self.events = queue.Queue()
        self.csrf = secrets.token_urlsafe(32)
        self.lock = threading.RLock()
        self.reported_usage = None
        # events_name -> native step count before that turn's input was written.
        self.inputs = {}
        self.log = self.run/'private/engine'/('antigravity-' + actor + '.log')

    def environment(self):
        env = {k: v for k, v in self.base_env.items() if k in ('PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL',
                'LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'SSL_CERT_FILE', 'SSL_CERT_DIR')}
        env['AGY_CLI_DISABLE_AUTO_UPDATE'] = 'true'
        # Hook and MCP imports use this checkout, not an editable install elsewhere.
        env['PYTHONPATH'] = str(Path(__file__).resolve().parents[3])
        original = env.get('HOME', str(Path.home()))
        env['HOME'] = str(environment_home(self.run, self.profile, original))
        if self.profile['auth_mode'] == 'api_key':
            key = self.base_env.get(self.profile['env_key'])
            if not key:
                raise ValueError('Missing credential variable: ' + self.profile['env_key'])
            if self.gateway is None:
                self.gateway = self.gateway_factory(self.profile['base_url'], key).start()
            env['GEMINI_API_KEY'] = self.gateway.placeholder
            env['GOOGLE_GEMINI_BASE_URL'] = self.gateway.url
        return env

    @property
    def home(self):
        return home_directory(self.run, self.profile, self.base_env.get('HOME'))/'.gemini/antigravity-cli'

    def open(self, timeout=60):
        with self.lock:
            if self.process is not None and self.process.poll() is None:
                return self.session
            creating = self.session is None
            self.events = queue.Queue()
            settings = configure(self.run, **({'python': self.python} if self.python else {}))
            values = json.loads(settings.read_text())
            if self.profile['auth_mode'] == 'api_key':
                values['modelProvider'] = 'gemini'
            cmd = [self.binary, '--input-format', 'stream-json', '--output-format', 'stream-json',
                   '--disable-slash-commands', '--agent', 'robofrontier', '--model', self.profile['model'],
                   '--effort', self.profile['effort'], '--mode', 'accept-edits', '--sandbox',
                   '--settings', json.dumps(values), '--log-file', str(self.log), '--csrf_token', self.csrf]
            if self.session:
                cmd += ['--conversation', self.session]
            env = self.environment()
            try:
                self.process = subprocess.Popen(cmd, cwd=cli_workspace(self.run), env=env, stdin=subprocess.PIPE,
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, bufsize=1, start_new_session=True)
                process, messages = self.process, self.events
                def read():
                    try:
                        for line in process.stdout:
                            try:
                                messages.put(json.loads(line))
                            except (ValueError, TypeError):
                                messages.put({'event': 'invalid'})
                    finally:
                        messages.put(None)
                def drain():
                    # stderr can contain provider error bodies. Drain without persisting.
                    for _ in process.stderr:
                        pass
                threading.Thread(target=read, daemon=True).start()
                threading.Thread(target=drain, daemon=True).start()
                first = messages.get(timeout=timeout)
                if not first or first.get('event') != 'init':
                    raise ValueError('Antigravity did not establish a native session before input')
                if first.get('init', {}).get('model') != self.profile['model']:
                    raise ValueError('Antigravity selected a different model')
                sid = native_id(first.get('conversation_id'))
                if self.session and sid != self.session:
                    raise ValueError('Antigravity resumed a different session')
                self.session = sid
                from .context import limits, policy_spec, system_text, verify_static
                if creating:
                    # Bootstrap establishes authenticated local control without sending
                    # model input. Create the actual policy conversation with immutable
                    # checkpoint settings and only the frozen system prompt, then attach
                    # the CLI to that native ID.
                    metadata = self.rpc('GetConversationMetadata', {'conversationId': sid})
                    _, threshold = limits(self.run)
                    spec = policy_spec(metadata['metadata']['staticConfig'], threshold, system_text(self.run))
                    reply = self.rpc('StartCascade', {'customAgentSpec': spec,
                        'workspaceUris': [cli_workspace(self.run).as_uri()],
                        'source': 'CORTEX_TRAJECTORY_SOURCE_CLI'})
                    configured = native_id(reply.get('cascadeId'))
                    if configured == sid:
                        raise ValueError('Native conversation creation reused the bootstrap session')
                    write_json(self.run/'private/engine/context'/(configured+'-creation.json'),
                        {'bootstrap_session_id': sid, 'session_id': configured,
                         'model_input_sent': False, 'auto_compact_token_limit': threshold})
                    self.close()
                    self.session = configured
                    self.reported_usage = None
                    return self.open(timeout)
                verify_static(self)
                accounting = self.run/'private/state/antigravity-accounting'/(sid+'.json')
                if self.reported_usage is None:
                    if accounting.is_file():
                        self.reported_usage = json.loads(accounting.read_text())
                    else:
                        transcript = self.home/'brain'/sid/'.system_generated/logs/transcript.jsonl'
                        rows = [json.loads(line) for line in transcript.read_text().splitlines()] if transcript.is_file() else []
                        self.reported_usage = usage_baseline(rows)
                write_json(self.run/'private/state/antigravity-sessions'/ (self.actor + '.json'),
                           {'session_id': sid, 'actor': self.actor})
                return sid
            except BaseException:
                self.close()
                raise

    def close(self):
        with self.lock:
            collection_error = None
            if self.process is not None:
                process = self.process
                def send(sig):
                    try:
                        os.killpg(process.pid, sig)
                    except PermissionError:
                        # macOS can reject a group signal across sandboxed
                        # descendants. Still reap the CLI we own explicitly.
                        process.send_signal(sig)
                if process.poll() is None:
                    try:
                        send(signal.SIGTERM)
                        process.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        send(signal.SIGKILL)
                        process.wait(timeout=5)
                    except ProcessLookupError:
                        pass
                for stream in (process.stdin, process.stdout, process.stderr):
                    if stream:
                        stream.close()
                self.process = None
                if self.session:
                    try:
                        self.collect_session()
                    except Exception as error:
                        collection_error = error
            if self.gateway:
                self.gateway.close()
                self.gateway = None
            if collection_error:
                raise collection_error

    def collect_session(self):
        """Copy only this stopped session, never its authentication/configuration home."""
        source = self.home/'brain'/self.session/'.system_generated/logs/transcript.jsonl'
        target = self.run/'private/engine/transcripts'/(self.session+'.jsonl')
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.is_file():
            shutil.copyfile(source, target)
        native = self.home/'conversations'/(self.session+'.db')
        if native.is_file():
            destination = self.run/'private/engine/native'/(self.session+'.db')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(native.as_uri()+'?mode=ro', uri=True) as original, sqlite3.connect(destination) as copied:
                original.backup(copied)

    def __call__(self, profile, model, effort, mcp, prompt, run_dir, base_env, *, cancel_event=None,
                 timeout=None, events_name='turn.jsonl', max_budget_usd=None, **options):
        if max_budget_usd is not None:
            raise ValueError('Antigravity does not report costs or enforce a dollar allowance')
        if cancel_event is not None and cancel_event.is_set():
            raise PreLaunchCancelled('Antigravity turn stopped before input')
        self.open()
        from .native_turn import boundary, completed
        native_start = boundary(self)
        began = time.monotonic()
        evidence = self.run/'private/engine/turns'/events_name
        evidence.parent.mkdir(parents=True, exist_ok=True)
        events = []
        from robofrontier.batch.metrics import host_event
        host_event(self.run, 'cli_turn_started', actor=self.actor, session_id=self.session,
                   events_name=events_name, native_step_start=native_start)
        try:
            with evidence.open('x') as out:
                if cancel_event is not None and cancel_event.is_set():
                    raise PreLaunchCancelled('Antigravity turn stopped before input')
                self.process.stdin.write(json.dumps({'event': 'user', 'message': {'content': prompt}}) + '\n')
                self.process.stdin.flush()
                with self.lock:
                    self.inputs[events_name] = native_start
                while True:
                    if cancel_event and cancel_event.is_set() or timeout and time.monotonic() - began >= timeout:
                        self.close()
                        return {'process': 'interrupted', 'summary': summarize(events, self.session)}
                    try:
                        event = self.events.get(timeout=.1)
                    except queue.Empty:
                        continue
                    if event is None:
                        return {'process': 'process_exited', 'exit_code': self.process.poll(),
                                'summary': summarize(events, self.session)}
                    out.write(json.dumps(event, ensure_ascii=False) + '\n')
                    out.flush()
                    events.append(event)
                    if event.get('event') == 'invalid':
                        raise ValueError('Malformed native event')
                    if event.get('event') == 'result':
                        summary = summarize(events, self.session)
                        if summary.get('session_id') == self.session and not summary.get('denied_actions'):
                            proof = completed(self, native_start, summary.get('response'))
                            if proof:
                                summary.update(proof)
                                summary['native_result_turn_status'] = summary['turn_status']
                                summary.update(turn_status='ended', result_subtype='success', capacity_error_code=None)
                        if summary.get('turn_status') == 'ended':
                            from .context import verify_effective
                            verify_effective(self)
                        delta, self.reported_usage = usage_delta(summary.get('usage'), self.reported_usage)
                        write_json(self.run/'private/state/antigravity-accounting'/(self.session+'.json'),
                                   self.reported_usage)
                        host_event(self.run, 'cli_turn_completed', actor=self.actor, session_id=self.session,
                            events_name=events_name, phase='policy', usage_delta=delta,
                            reported_cost_usd=None, duration_s=time.monotonic()-began)
                        return {'process': 'exited', 'exit_code': 0, 'summary': summary,
                                'duration_s': time.monotonic() - began}
        except BaseException:
            self.close()
            raise

    def rpc(self, method, body):
        if not self.process or self.process.poll() is not None:
            raise ValueError('Native process is not live')
        matches = re.findall(r'Language server listening on random port at (\d+) for HTTP', self.log.read_text())
        if not matches:
            raise ValueError('Native control endpoint missing')
        request = urllib.request.Request('http://127.0.0.1:' + matches[-1] +
            '/exa.language_server_pb.LanguageServerService/' + method, data=json.dumps(body).encode(),
            headers={'Content-Type': 'application/json', 'x-codeium-csrf-token': self.csrf})
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def input_delivered(self, events_name, timeout, alive=lambda: True):
        """True once the native history holds the user input of turn `events_name`.

        Writing to the CLI's stdin only hands the text to a pipe. The session's own
        database recording a new user-input step is the evidence that it arrived."""
        from .provenance import steps
        deadline = time.monotonic() + timeout
        while True:
            with self.lock:
                start = self.inputs.get(events_name)
            if start is not None:
                try:
                    if any(row[1] == USER_INPUT_STEP for row in steps(self.home, self.session)[start:]):
                        return True
                except (sqlite3.Error, ValueError):
                    pass  # Being written; read again.
            elif not alive():
                return False
            if time.monotonic() >= deadline:
                return False
            time.sleep(.05)

    def fork(self, step):
        reply = self.rpc('ForkConversation', {'sourceCascadeId': self.session, 'forkAtStepIndex': step})
        child = native_id(reply.get('newCascadeId'))
        if child == self.session:
            raise ValueError('Native fork returned its own source session')
        if reply.get('forkedAtStepIndex') != step:
            # The child exists. Its ID must reach the run's records before anything fails.
            raise ForkUnacknowledged(child)
        return child
