"""Notice when a local run's model API is unreachable, so its world can pause (egress_pause).

Runs that count active time (run_protocol clock active_time_v1) and have no Slurm egress pause
(a Mac, a RunPod host, or a Slurm job with direct egress) probe the model API host the run's
profile names (its `base_url`), or their engine's default hosts, from the world process with a verified HTTPS request (a bare TCP connect succeeds through a
local VPN tunnel whose route is gone). After `FAILURES` consecutive failed probes the world pauses as for a
Slurm egress outage; the first successful probe resumes it. Slurm runs keep their egress
pause. See docs/running/continuation.md#time.

The probe runs on its own thread and only sets flags; the world's owner thread reads them and
writes every record. A probe that never succeeds (no direct route, as on a Slurm node or in a
sandbox) never pauses a world: it gives up after `UNARMED_GIVE_UP` failures.
"""
import os
import socket
import ssl
import threading
import time

ENGINE_HOSTS = {'claude': ('api.anthropic.com',), 'codex': ('chatgpt.com', 'auth.openai.com')}
INTERVAL_S = 5.
TIMEOUT_S = 5.
FAILURES = 3
UNARMED_GIVE_UP = 12
SWITCH = 'ROBOFRONTIER_OUTAGE_PROBE'


def tcp_probe(hosts, timeout=TIMEOUT_S):
    """True when every host accepts a TCP connection on port 443.

    Not used by default: a local VPN tunnel accepts every TCP connection itself, so this
    stays true while the route to the API is gone (observed 2026-11-10)."""
    for host in hosts:
        try:
            socket.create_connection((host, 443), timeout=timeout).close()
        except OSError:
            return False
    return True


def https_probe(hosts, timeout=TIMEOUT_S, context=None, port=443):
    """True when every host completes a verified TLS handshake and answers an HTTP request.

    Any HTTP status counts: the answer proves the server itself was reached end to end."""
    context = context or ssl.create_default_context()
    for host in hosts:
        try:
            with socket.create_connection((host, port), timeout=timeout) as raw:
                with context.wrap_socket(raw, server_hostname=host) as tls:
                    tls.settimeout(timeout)
                    tls.sendall(b'HEAD / HTTP/1.1\r\nHost: ' + host.encode('idna') + b'\r\nConnection: close\r\n\r\n')
                    if not tls.recv(16).startswith(b'HTTP/'): return False
        except (OSError, ValueError):
            return False
    return True


def bounded(probe, hosts, timeout):
    """Run one probe, counting it as failed if it has not answered within `timeout`.

    Name resolution has no timeout of its own, so the probe runs on a helper thread."""
    answer = []
    def run():
        try: answer.append(probe(hosts))
        except Exception: answer.append(False)
    worker = threading.Thread(target=run, daemon=True)
    worker.start(); worker.join(timeout)
    return bool(answer and answer[0])


class OutageMonitor:
    def __init__(self, hosts, probe=https_probe, *, interval_s=INTERVAL_S, timeout_s=TIMEOUT_S,
                 failures=FAILURES, unarmed_give_up=UNARMED_GIVE_UP, clock=time.monotonic):
        self.hosts = tuple(hosts); self.probe = probe; self.interval_s = interval_s
        self.timeout_s = timeout_s; self.required = failures; self.unarmed_give_up = unarmed_give_up
        self.clock = clock
        self.armed = False      # a probe succeeded once: this host reaches the API directly
        self.failures = 0       # consecutive failed probes
        self.streak_started = None  # when the first failed probe of the current streak began
        self.down = False
        self.unavailable = False
        self.notes = []
        self.lock = threading.Lock(); self.stopping = threading.Event(); self.thread = None

    def step(self):
        """One probe; returns whether the API is now considered down."""
        began = self.clock()
        try:
            ok = bounded(self.probe, self.hosts, self.timeout_s * len(self.hosts) + 1.)
        except Exception:
            ok = False
        with self.lock:
            if ok:
                self.armed = True; self.failures = 0; self.streak_started = None; self.down = False
            else:
                self.failures += 1
                if self.streak_started is None: self.streak_started = began
                if self.armed and self.failures >= self.required: self.down = True
                elif not self.armed and self.failures >= self.unarmed_give_up:
                    self.unavailable = True
                    self.notes.append(('OUTAGE_PROBE_UNAVAILABLE', {'hosts': list(self.hosts), 'failures': self.failures,
                        'note': 'The model API was never reachable from the world process; no outage pause'}))
            return self.down

    def take_notes(self):
        with self.lock:
            notes, self.notes = self.notes, []
        return notes

    def state(self):
        with self.lock:
            return {'down': self.down, 'failures': self.failures, 'streak_started': self.streak_started}

    def _loop(self):
        while not self.stopping.is_set() and not self.unavailable:
            self.step()
            self.stopping.wait(self.interval_s)

    def start(self):
        self.thread = threading.Thread(target=self._loop, name='outage-probe', daemon=True)
        self.thread.start()
        return self

    def stop(self):
        self.stopping.set()


def model_hosts(run, engine):
    """The model API hosts a run uses: its frozen profile's base_url host, else the engine's own."""
    import json
    from pathlib import Path
    from urllib.parse import urlsplit
    if run is not None:
        try: profile = json.loads((Path(run)/'private/inputs'/(engine+'.json')).read_text()).get('profile') or {}
        except (OSError, ValueError, AttributeError): profile = {}
        host = urlsplit(profile.get('base_url') or '').hostname
        if host: return (host,)
    return ENGINE_HOSTS.get(engine)


def monitor_for(task, config, probe=None, run=None):
    """The outage monitor a world should run, or None.

    Only active-time runs without a Slurm egress pause (which pauses the world itself), with
    known model hosts, and not switched off with ROBOFRONTIER_OUTAGE_PROBE=off (the test suite
    does that). A Slurm node without a direct route never reaches the hosts, so its probe never
    pauses (UNARMED_GIVE_UP)."""
    from .clock import WALL_CLOCK, run_clock
    if run_clock(task.get('run_protocol') or {}) == WALL_CLOCK: return None
    if task.get('execution_readiness') != 'prepared_policy_trial': return None
    if os.environ.get('ROBOFRONTIER_EGRESS_PAUSE_FILE'): return None
    if os.environ.get(SWITCH, '').strip().lower() in ('off', '0', 'false', 'no'): return None
    hosts = model_hosts(run, (config or {}).get('engine', 'codex'))
    if not hosts: return None
    return OutageMonitor(hosts, probe or https_probe)
