"""Job-scoped HTTP CONNECT egress over an operator-owned Mac/SSH channel.

Only opaque end-to-end TLS bytes cross this relay. It never reads native login
caches, submits allocations, restarts model turns, or changes policy networking.
The compute half is standalone so the Mac can run it through an existing srun.
"""
import argparse
import asyncio
import base64
from contextlib import contextmanager
import fcntl
import hashlib
import hmac
import http.client
import json
import os
from pathlib import Path
import re
import secrets
import shlex
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from urllib.parse import urlsplit

SCHEMA = 'robofrontier.slurm-egress.v3'
HEARTBEAT_S = 2
STALE_S = 12
MAX_STREAMS = 256
MAX_FRAME = 100000
CHUNK = 8192
WINDOW = 131072
CHANNEL_WINDOW = 524288


class EgressError(RuntimeError):
    pass


def require_local_storage(root):
    if sys.platform=='linux':
        kind=subprocess.check_output(['stat','-f','-c','%T',str(root)],text=True).strip()
        if kind not in ('ext2/ext3','xfs','btrfs','tmpfs','overlayfs','zfs'):
            raise EgressError('Short-outage control state requires node-local storage')


def private_directory(path, *, create=False):
    path = Path(path).absolute()
    if path.resolve() != path:
        raise EgressError('Egress directories must be canonical, without symlinks')
    if create:
        path.mkdir(parents=True, mode=0o700, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise EgressError('Egress directories must be private and owned by the operator')
    return path


def atomic(path, value):
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(json.dumps(value)+'\n'); out.flush(); os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_record(path):
    for _ in range(4):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_size > 16384 or info.st_nlink > 1):
                raise EgressError('Unsafe egress readiness record')
            if info.st_nlink == 0:
                # Atomic heartbeat publication can unlink the inode after open
                # but before fstat. Reopen the path; never admit that old inode.
                continue
            return json.loads(stream.read(16385))
    raise EgressError('Egress readiness record kept changing during read')


def job_id(value):
    if not re.fullmatch(r'[0-9]{1,16}', value):
        raise EgressError('An existing numeric Slurm allocation is required')
    return value


# One table decides which destinations the relay forwards and which hosts the
# Mac probes for each engine's job, so the two lists cannot drift apart. A route
# is healthy only while every probe host of its engine completes a TLS handshake.
ENGINE_ROUTES = {
    'codex': {'domains': ('openai.com', 'chatgpt.com'), 'probe_hosts': ('chatgpt.com', 'auth.openai.com')},
    'claude': {'domains': ('anthropic.com',), 'probe_hosts': ('api.anthropic.com',)},
}
ALLOWED_DOMAINS = tuple(domain for route in ENGINE_ROUTES.values() for domain in route['domains'])


def target_allowed(host, port, domains=ALLOWED_DOMAINS):
    return (port == 443 and isinstance(host, str) and len(host) <= 253
            and bool(re.fullmatch(r'[a-z0-9.-]+', host))
            and any(host == domain or host.endswith('.'+domain) for domain in domains))


def probe_hosts(engine):
    """Hosts whose TLS reachability decides route health for this engine."""
    route = ENGINE_ROUTES.get(engine)
    if route is None:
        raise EgressError('Unknown relay engine')
    if not all(target_allowed(host, 443, route['domains']) for host in route['probe_hosts']):
        raise EgressError('Relay probe hosts must be destinations of the same engine route')
    return route['probe_hosts']


def validate_record(record, identity, node, *, allow_paused=False):
    try:
        url = urlsplit(record['proxy_url'])
        good = (record['schema'] == SCHEMA and record['job_id'] == identity and record['node'] == node
                and isinstance(record['instance'], str) and len(record['instance']) == 32
                and -2 <= time.time()-record['heartbeat'] < STALE_S
                and record.get('state','ready') in (('ready','paused') if allow_paused else ('ready',))
                and url.scheme == 'http' and url.hostname == '127.0.0.1'
                and url.port and url.username == 'rf' and url.password and len(url.password) == 64
                and not url.path and not url.query and not url.fragment)
    except (KeyError, TypeError, ValueError):
        good = False
    if not good:
        raise EgressError('Managed egress is absent, stale or bound to another allocation/node')
    return url


def health(record, url):
    token = base64.b64encode((url.username+':'+url.password).encode()).decode()
    connection = http.client.HTTPConnection(url.hostname, url.port, timeout=2)
    try:
        connection.request('GET', '/health', headers={'Proxy-Authorization': 'Basic '+token})
        response = connection.getresponse()
        if response.status != 200 or response.getheader('X-RF-Instance') != record['instance']:
            raise EgressError('Egress listener identity check failed')
        response.read(1024)
    except (OSError, http.client.HTTPException):
        raise EgressError('Egress listener is not reachable') from None
    finally:
        connection.close()


@contextmanager
def environment(config, *, on_failure):
    """Admit one allocation's route, latch any loss, and restore the caller env."""
    slurm = config['slurm']
    if slurm.get('egress_mode', 'direct') != 'mac-ssh':
        yield
        return
    identity = job_id(os.environ.get('SLURM_JOB_ID', ''))
    grace_s = slurm.get('egress_pause_s',0)
    root = private_directory(slurm['egress_root'], create=True)
    if grace_s:require_local_storage(root)
    directory = root/identity
    deadline = time.monotonic()+slurm['egress_wait_s']
    while True:
        try:
            private_directory(directory)
            record = read_record(directory/'ready.json')
            url = validate_record(record, identity, socket.gethostname())
            if record.get('grace_s',0) != grace_s:
                raise EgressError('Managed egress recovery settings do not match the job')
            health(record, url)
            break
        except (OSError, ValueError, EgressError):
            if time.monotonic() >= deadline:
                raise EgressError('Managed Mac egress did not become ready before admission') from None
            time.sleep(.2)
    pause_path = None
    if grace_s:
        private = private_directory(os.environ['ROBOFRONTIER_JOB_PRIVATE_ROOT'])
        pause_path = private/'EGRESS_PAUSED'
        if os.path.lexists(pause_path):raise EgressError('A previous pause requires explicit review')
    keys = ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy',
            'all_proxy', 'no_proxy', 'ROBOFRONTIER_EGRESS_ROOT', 'ROBOFRONTIER_EGRESS_INSTANCE',
            'ROBOFRONTIER_EGRESS_PAUSE_FILE','ROBOFRONTIER_EGRESS_PAUSE_S')
    saved = {k: os.environ.get(k) for k in keys}
    for key in keys:
        os.environ.pop(key, None)
    os.environ.update(HTTPS_PROXY=record['proxy_url'], HTTP_PROXY=record['proxy_url'],
                      ALL_PROXY=record['proxy_url'], NO_PROXY='127.0.0.1,localhost',
                      ROBOFRONTIER_EGRESS_ROOT=str(root), ROBOFRONTIER_EGRESS_INSTANCE=record['instance'])
    if pause_path:
        os.environ['ROBOFRONTIER_EGRESS_PAUSE_FILE']=str(pause_path)
        os.environ['ROBOFRONTIER_EGRESS_PAUSE_S']=str(grace_s)
    stopped = threading.Event()
    failed = threading.Event()
    def watch():
        paused_at = None
        claim = None
        while not stopped.wait(.5):
            try:
                current = read_record(directory/'ready.json')
                validate_record(current, identity, socket.gethostname(), allow_paused=bool(grace_s))
                if current['instance'] != record['instance'] or current['proxy_url'] != record['proxy_url']:
                    raise EgressError('Egress identity changed')
                if current.get('grace_s',0) != grace_s:raise EgressError('Egress recovery settings changed')
                if current.get('state','ready')=='paused':
                    if paused_at is None:
                        paused_at=time.monotonic()
                        claim=secrets.token_hex(16)
                        atomic(pause_path,{'schema':'robofrontier.egress-pause.v1','job_id':identity,
                                          'instance':record['instance'],'claim':claim,'at':time.time()})
                    if time.monotonic()-paused_at>grace_s:raise EgressError('Short outage grace expired')
                elif paused_at is not None:
                    marker=read_record(pause_path)
                    if marker.get('claim')!=claim or marker.get('instance')!=record['instance']:
                        raise EgressError('Pause ownership changed')
                    try:health(current,url)
                    except EgressError:
                        if time.monotonic()-paused_at>grace_s:raise
                        continue
                    pause_path.unlink();paused_at=None
            except Exception as error:
                reason = ('unsafe_record' if isinstance(error, EgressError) and str(error) == 'Unsafe egress readiness record'
                          else 'binding_or_freshness' if isinstance(error, EgressError) and str(error).startswith('Managed egress is absent')
                          else 'instance_changed' if isinstance(error, EgressError) and str(error) == 'Egress identity changed'
                          else type(error).__name__)
                # Only fixed metadata enters diagnostics, never the private URL.
                private = os.environ.get('ROBOFRONTIER_JOB_PRIVATE_ROOT')
                if private:
                    try:
                        atomic(private_directory(private)/'EGRESS_DIAGNOSTIC.json',
                               {'reason': reason, 'at': time.time(), 'job_id': identity})
                    except Exception:
                        pass  # Failure to save a diagnostic cannot suppress fencing.
                failed.set()
                on_failure()
                return
    watcher = threading.Thread(target=watch, name='slurm-egress-custody', daemon=True)
    watcher.start()
    try:
        yield
        if failed.is_set():
            raise EgressError('Managed egress was lost; execution must not be automatically replayed')
    finally:
        stopped.set(); watcher.join()
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class Frames:
    """Bounded private stdio messages; payloads are never logged or retained."""
    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer
        self.condition = asyncio.Condition()
        self.waiting = {}; self.sequence = 0; self.writing = False
        self.write_started = None
        self.tx_bytes = 0; self.rx_bytes = 0
        self.max_control_wait_s = 0; self.max_write_wait_s = 0
        self.outbound = SendWindow(CHANNEL_WINDOW)
        self.pending_credit = 0; self.credit_task = None; self.credit_error = None

    async def return_credit(self):
        """Coalesce acknowledgements without waiting in the receive loop.

        Both SSH directions can be at their write high-water mark together.
        Waiting for drain here would stop both readers: neither writer could
        ever drain, so even priority heartbeats would time out.
        """
        try:
            while self.pending_credit:
                size = self.pending_credit; self.pending_credit = 0
                await self.send({'type': 'channel_credit', 'bytes': size})
        except asyncio.CancelledError:
            raise
        except Exception as error:
            self.credit_error = error
            self.writer.close()
        finally:
            self.credit_task = None

    async def close(self):
        if self.credit_task:
            self.credit_task.cancel()
            await asyncio.gather(self.credit_task, return_exceptions=True)

    def stats(self):
        return {'tx_bytes': self.tx_bytes, 'rx_bytes': self.rx_bytes,
                'queued_frames': len(self.waiting),
                'max_control_wait_s': round(self.max_control_wait_s, 3),
                'max_write_wait_s': round(self.max_write_wait_s, 3),
                'active_write_wait_s': None if self.write_started is None else round(time.monotonic()-self.write_started, 3),
                'pending_credit_bytes': self.pending_credit,
                'unacked_wire_bytes': CHANNEL_WINDOW-self.outbound.available}

    async def send(self, value):
        data = json.dumps(value, separators=(',', ':')).encode()+b'\n'
        if len(data) > MAX_FRAME:
            raise EgressError('Relay frame limit exceeded')
        reserved = value.get('type') == 'data'
        if reserved and len(data) > CHANNEL_WINDOW:
            raise EgressError('Relay data frame exceeds the channel window')
        if reserved:
            await self.outbound.take(len(data))
        # asyncio.Lock is FIFO: dozens of bulk senders can put a heartbeat
        # behind seconds of uploads. Admit control before queued payloads.
        priority = 2 if value.get('type') == 'data' else 0 if value.get('type') in ('ping','pong') else 1
        self.sequence += 1; ticket = (priority, self.sequence)
        started = time.monotonic(); self.waiting[ticket] = started; admitted = False; written = False
        try:
            async with self.condition:
                await self.condition.wait_for(lambda: not self.writing and ticket == min(self.waiting))
                self.waiting.pop(ticket); self.writing = True; admitted = True
            if priority == 0:
                self.max_control_wait_s = max(self.max_control_wait_s, time.monotonic()-started)
            write_started = time.monotonic()
            self.write_started = write_started
            self.writer.write(data)
            written = True
            await self.writer.drain()
            self.tx_bytes += len(data)
            self.max_write_wait_s = max(self.max_write_wait_s, time.monotonic()-write_started)
        finally:
            async with self.condition:
                self.waiting.pop(ticket, None)
                if admitted:
                    self.writing = False
                    self.write_started = None
                self.condition.notify_all()
            if reserved and not written:
                self.outbound.credit(len(data))

    async def receive(self):
        while True:
            if self.credit_error:
                raise self.credit_error
            line = await self.reader.readline()
            if not line:
                raise EOFError()
            self.rx_bytes += len(line)
            if len(line) > MAX_FRAME:
                raise EgressError('Relay frame limit exceeded')
            value = json.loads(line)
            if not isinstance(value, dict):
                raise EgressError('Invalid relay frame')
            if value.get('type') == 'channel_credit':
                self.outbound.credit(value.get('bytes'))
                continue
            if value.get('type') == 'data':
                # Credit at decode, independently of destination draining. This
                # bounds bytes hidden in SSH/Slurm's own buffering without
                # letting a slow destination exhaust the whole route's credit.
                self.pending_credit += len(line)
                if self.pending_credit > CHANNEL_WINDOW:
                    raise EgressError('Relay acknowledgement window exceeded')
                if self.credit_task is None:
                    self.credit_task = asyncio.create_task(self.return_credit())
            return value


async def stdio_frames():
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader(limit=MAX_FRAME)
    await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin.buffer)
    protocol = asyncio.streams.FlowControlMixin(loop=loop)
    transport, _ = await loop.connect_write_pipe(lambda: protocol, sys.stdout.buffer)
    writer = asyncio.StreamWriter(transport, protocol, None, loop)
    return Frames(reader, writer)


def decode_data(value):
    if not isinstance(value, str) or len(value) > 65536:
        raise EgressError('Invalid relay data frame')
    return base64.b64decode(value, validate=True)


class SendWindow:
    """Per-stream byte credit; a slow socket cannot fill the shared channel."""
    def __init__(self, limit=WINDOW):
        self.limit = limit
        self.available = limit
        self.changed = asyncio.Event()

    async def take(self, size):
        while self.available < size:
            self.changed.clear()
            await self.changed.wait()
        self.available -= size

    def credit(self, size):
        if type(size) is not int or size <= 0 or self.available + size > self.limit:
            raise EgressError('Invalid relay stream credit')
        self.available += size
        self.changed.set()


class StreamSink:
    """Drain one socket independently, returning credit only after delivery."""
    def __init__(self, writer, frames, identity, owner):
        self.writer, self.frames, self.identity, self.owner = writer, frames, identity, owner
        self.queue = asyncio.Queue()
        self.pending = 0
        self.ending = False
        self.stopping = False
        self.task = asyncio.create_task(self.run())

    def feed(self, data):
        if self.ending:
            return
        if not data or len(data) > CHUNK or self.pending + len(data) > WINDOW:
            raise EgressError('Relay receive window exceeded')
        self.pending += len(data)
        self.queue.put_nowait(data)

    def finish(self):
        if not self.ending:
            self.ending = True
            self.queue.put_nowait(None)

    async def run(self):
        try:
            while (data := await self.queue.get()) is not None:
                self.writer.write(data)
                await self.writer.drain()
                self.pending -= len(data)
                await self.frames.send({'type': 'credit', 'id': self.identity, 'bytes': len(data)})
        except (OSError, EgressError):
            pass
        finally:
            self.writer.close()
            if not self.stopping:
                self.owner.cancel()

    async def close(self):
        self.stopping = True
        self.task.cancel()
        await asyncio.gather(self.task, return_exceptions=True)


async def copy_to_frames(reader, frames, identity, window):
    while data := await reader.read(CHUNK):
        await window.take(len(data))
        await frames.send({'type': 'data', 'id': identity, 'data': base64.b64encode(data).decode()})


async def discard_remaining(reader):
    while await reader.read(CHUNK):
        pass


async def close_stream(frames, identity):
    # A dead SSH pipe must not keep cleanup (and the compute ownership lock)
    # alive indefinitely. This never retries data or recreates a connection.
    try:
        async with asyncio.timeout(1):
            await frames.send({'type': 'close', 'id': identity})
    except (OSError, EgressError, asyncio.TimeoutError):
        pass


class ComputeRelay:
    def __init__(self, frames, directory, identity, *, grace_s=0):
        self.frames, self.directory, self.identity = frames, directory, identity
        self.instance = secrets.token_hex(16)
        self.password = secrets.token_hex(32)
        self.authorization = 'Basic '+base64.b64encode(('rf:'+self.password).encode()).decode()
        self.streams = {}; self.next_id = 0; self.last_ping = time.monotonic()
        self.clients = set()
        self.grace_s=grace_s;self.paused_since=None;self.upstream_ready=True
        self.available=asyncio.Event();self.available.set()

    def publish_lease(self):
        now=time.monotonic()
        paused=now-self.last_ping>STALE_S or not self.upstream_ready
        if paused:
            if self.paused_since is None:self.paused_since=now
            if not self.grace_s or now-self.paused_since>self.grace_s:
                raise EgressError('Short outage grace expired')
            self.available.clear()
        else:self.paused_since=None;self.available.set()
        self.record.update(state='paused' if paused else 'ready',heartbeat=time.time())
        atomic(self.directory/'ready.json',self.record)

    async def lease_monitor(self):
        while True:
            self.publish_lease()
            await asyncio.sleep(HEARTBEAT_S)

    async def client(self, reader, writer):
        identity = None
        owner = asyncio.current_task(); self.clients.add(owner)
        sink = None
        try:
            async with asyncio.timeout(10):
                header = await reader.readuntil(b'\r\n\r\n')
            if len(header) > 8192:
                return
            lines = header.decode('ascii').split('\r\n')
            method, target, version = lines[0].split(' ')
            headers = {}
            for line in lines[1:]:
                if line:
                    key, value = line.split(':', 1)
                    if key.lower() in headers:
                        return
                    headers[key.lower()] = value.strip()
            if not hmac.compare_digest(headers.get('proxy-authorization', ''), self.authorization):
                writer.write(b'HTTP/1.1 407 Proxy Authentication Required\r\nContent-Length: 0\r\n\r\n')
                await writer.drain(); return
            if method == 'GET' and target == '/health':
                status='200 OK' if self.available.is_set() else '503 Service Unavailable'
                writer.write(('HTTP/1.1 '+status+'\r\nContent-Length: 0\r\nX-RF-Instance: '+self.instance+'\r\n\r\n').encode())
                await writer.drain(); return
            host, port = target.rsplit(':', 1)
            if (method != 'CONNECT' or version != 'HTTP/1.1' or not target_allowed(host, int(port))
                    or len(self.streams) >= MAX_STREAMS):
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
                await writer.drain(); return
            if self.grace_s:
                if len(self.clients)>MAX_STREAMS:
                    writer.write(b'HTTP/1.1 503 Service Unavailable\r\n\r\n');await writer.drain();return
                await self.available.wait()
                if reader.at_eof():return
            self.next_id += 1; identity = self.next_id
            opened = asyncio.get_running_loop().create_future()
            window = SendWindow()
            self.streams[identity] = {'writer': writer, 'opened': opened, 'window': window}
            await self.frames.send({'type': 'open', 'id': identity, 'host': host, 'port': int(port)})
            async with asyncio.timeout(20):
                accepted = await opened
            if not accepted:
                return
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n'); await writer.drain()
            sink = StreamSink(writer, self.frames, identity, owner)
            stream = self.streams[identity]
            stream['sink'] = sink
            # Data may follow the opened frame before this client is scheduled.
            for data in stream.pop('pending', []):
                sink.feed(data)
            if stream.get('closed'):
                sink.finish()
            await copy_to_frames(reader, self.frames, identity, window)
        except (OSError, ValueError, EOFError, asyncio.TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError, EgressError):
            pass
        finally:
            self.clients.discard(owner)
            if identity is not None:
                self.streams.pop(identity, None)
                if sink:
                    await sink.close()
                await close_stream(self.frames, identity)
            writer.close()

    async def messages(self):
        while True:
            if not self.grace_s and time.monotonic()-self.last_ping > STALE_S:
                raise EgressError('Mac heartbeat was lost')
            async with asyncio.timeout(None if self.grace_s else STALE_S):
                message = await self.frames.receive()
            kind = message.get('type')
            if kind == 'ping':
                self.last_ping = time.monotonic()
                ready=message.get('network_available',True)
                if type(ready) is not bool:raise EgressError('Invalid route availability')
                self.upstream_ready=ready
                if self.grace_s:self.publish_lease()
                else:atomic(self.directory/'ready.json', {**self.record, 'heartbeat': time.time()})
                await self.frames.send({'type': 'pong'})
                continue
            stream = self.streams.get(message.get('id'))
            if stream is None:
                continue
            if kind == 'opened' and not stream['opened'].done():
                stream['opened'].set_result(message.get('ok') is True)
            elif kind == 'data':
                data = decode_data(message.get('data'))
                if 'sink' in stream:
                    stream['sink'].feed(data)
                else:
                    pending = stream.setdefault('pending', [])
                    if not data or len(data) > CHUNK or sum(map(len, pending)) + len(data) > WINDOW:
                        raise EgressError('Relay receive window exceeded')
                    pending.append(data)
            elif kind == 'credit':
                stream['window'].credit(message.get('bytes'))
            elif kind == 'close':
                stream['closed'] = True
                if not stream['opened'].done():
                    stream['opened'].set_result(False)
                if 'sink' in stream:
                    stream['sink'].finish()

    async def run(self):
        server = await asyncio.start_server(self.client, '127.0.0.1', 0, limit=8193)
        port = server.sockets[0].getsockname()[1]
        self.record = {'schema': SCHEMA, 'job_id': self.identity, 'node': socket.gethostname(),
                       'instance': self.instance, 'proxy_url': 'http://rf:'+self.password+'@127.0.0.1:'+str(port),
                       'heartbeat': time.time(),'state':'ready','grace_s':self.grace_s}
        atomic(self.directory/'ready.json', self.record)
        failure = None
        monitors=[]
        try:
            await self.frames.send({'type': 'ready', 'job_id': self.identity, 'node': self.record['node'],
                                    'instance':self.instance,'grace_s':self.grace_s})
            if self.grace_s:
                monitors=[asyncio.create_task(self.messages()),asyncio.create_task(self.lease_monitor())]
                done,_=await asyncio.wait(monitors,return_when=asyncio.FIRST_COMPLETED)
                for task in done:await task
            else:await self.messages()
        except BaseException as error:
            failure = {'type': type(error).__name__, 'transport': self.frames.stats()}
            raise
        finally:
            # Server.__aexit__/wait_closed waits for active clients on Python
            # 3.12. Close those clients before awaiting listener shutdown.
            server.close()
            for task in monitors:task.cancel()
            await asyncio.gather(*monitors,return_exceptions=True)
            await self.frames.close()
            current = self.directory/'ready.json'
            if current.exists() and read_record(current).get('instance') == self.instance:
                current.unlink()
            for stream in list(self.streams.values()):
                stream['writer'].close()
            clients = list(self.clients)
            for task in clients:
                task.cancel()
            await asyncio.gather(*clients, return_exceptions=True)
            await server.wait_closed()
            atomic(self.directory/'closed.json', {'schema': SCHEMA, 'instance': self.instance,
                   'closed_at': time.time(), 'last_ping_age_s': time.monotonic()-self.last_ping,
                   'failure': failure,
                   'transport': self.frames.stats()})


async def serve(root, identity, *, grace_s=0):
    if sys.platform != 'linux' or os.environ.get('SLURM_JOB_ID') != identity:
        raise EgressError('Compute egress must run inside the selected Slurm allocation')
    current = asyncio.current_task()
    for number in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(number, current.cancel)
    root = private_directory(root, create=True)
    if grace_s:require_local_storage(root)
    directory = private_directory(root/job_id(identity), create=True)
    fd = os.open(directory/'owner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise EgressError('Unsafe egress ownership lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            await ComputeRelay(await stdio_frames(), directory, identity,grace_s=grace_s).run()
        except EOFError:
            pass  # Channel closure is terminal; never restart or replay it.
    finally:
        os.close(fd)


class MacRelay:
    def __init__(self, frames, *, status=None, dial=None, grace_s=0, probe=None, probe_hosts=(), probe_dial=None):
        self.frames, self.status = frames, status
        self.dial = dial or asyncio.open_connection
        self.streams = {}; self.tasks = {}; self.last_pong = None; self.ready = None
        self.failure_code = None; self.peak_streams = 0
        self.failure_transport = None
        self.grace_s=grace_s;self.paused_since=None;self.upstream_failed=False
        # The job's engine decides these hosts (probe_hosts(engine)); they are
        # passed explicitly so a Claude route never depends on an OpenAI host.
        self.probe_hosts=tuple(probe_hosts)
        if any(not target_allowed(host,443) for host in self.probe_hosts):
            raise EgressError('Relay probe hosts must be relayed destinations')
        if grace_s and probe is None and not self.probe_hosts:
            raise EgressError('Short-outage recovery requires the engine probe hosts')
        self.probe_dial=probe_dial or self.tls_handshake
        self.probe=probe or self.probe_upstream

    @staticmethod
    async def tls_handshake(host):
        reader,writer=await asyncio.open_connection(host,443,ssl=True)
        writer.close();await writer.wait_closed()
        return True

    async def probe_upstream(self):
        """True only when every probe host of this engine answers TLS."""
        results=await asyncio.gather(*(asyncio.wait_for(self.probe_dial(host),3) for host in self.probe_hosts),
                                     return_exceptions=True)
        for result in results:
            if isinstance(result,BaseException) and not isinstance(result,(OSError,asyncio.TimeoutError)):
                raise result
        return bool(results) and all(result is True for result in results)

    async def liveness(self):
        while True:
            if self.last_pong is not None:
                paused=self.upstream_failed or time.monotonic()-self.last_pong>STALE_S
                if paused:
                    if self.paused_since is None:self.paused_since=time.monotonic()
                    self.publish('paused')
                    if time.monotonic()-self.paused_since>self.grace_s:
                        raise EgressError('Compute heartbeat was lost')
                else:self.paused_since=None
            await asyncio.sleep(HEARTBEAT_S)

    async def upstream_monitor(self):
        failures=0
        while True:
            try:ready=bool(await self.probe())
            except (OSError,asyncio.TimeoutError):ready=False
            if ready:failures=0;self.upstream_failed=False
            else:
                failures+=1
                if failures>=2:self.upstream_failed=True
            await asyncio.sleep(HEARTBEAT_S*2)

    def publish(self, state):
        if self.status:
            atomic(self.status, {'status': state, 'updated_at': time.time(),
                                 'failure_code': self.failure_code, 'streams': len(self.tasks),
                                 'failure_transport': self.failure_transport,
                                 'peak_streams': self.peak_streams,
                                 'transport': self.frames.stats(),
                                 'last_pong_age_s': None if self.last_pong is None else round(time.monotonic()-self.last_pong, 3),
                                 'probe_hosts': list(self.probe_hosts),
                                 **(self.ready or {})})

    async def open_stream(self, identity, host, port):
        writer = None; sink = None
        try:
            if not target_allowed(host, port):
                raise EgressError('Relay destination denied')
            reader, writer = await asyncio.wait_for(self.dial(host, port), 15)
            window = SendWindow()
            sink = StreamSink(writer, self.frames, identity, asyncio.current_task())
            self.streams[identity] = {'writer': writer, 'sink': sink, 'window': window}
            await self.frames.send({'type': 'opened', 'id': identity, 'ok': True})
            await copy_to_frames(reader, self.frames, identity, window)
        except (OSError, asyncio.TimeoutError, EgressError) as error:
            if self.grace_s and isinstance(error,(OSError,asyncio.TimeoutError)):self.upstream_failed=True
            await self.frames.send({'type': 'opened', 'id': identity, 'ok': False})
        finally:
            self.streams.pop(identity, None); self.tasks.pop(identity, None)
            if sink:
                await sink.close()
            if writer:
                writer.close()
            await close_stream(self.frames, identity)

    async def heartbeat(self):
        while True:
            if not self.grace_s and self.last_pong is not None and time.monotonic()-self.last_pong > STALE_S:
                raise EgressError('Compute heartbeat was lost')
            available=not self.upstream_failed and (self.last_pong is None or time.monotonic()-self.last_pong<=STALE_S)
            await self.frames.send({'type': 'ping','network_available':available})
            await asyncio.sleep(HEARTBEAT_S)

    async def messages(self):
        while True:
            message = await self.frames.receive()
            kind, identity = message.get('type'), message.get('id')
            if kind == 'ready':
                if message.get('grace_s',0)!=self.grace_s:raise EgressError('Recovery settings mismatch')
                ready={'job_id':job_id(message['job_id']),'node':message['node'],'instance':message.get('instance')}
                if self.ready is not None and ready!=self.ready:raise EgressError('Relay instance changed')
                self.ready = ready
                self.last_pong = time.monotonic(); self.publish('ready')
            elif kind == 'pong':
                self.last_pong = time.monotonic(); self.publish('paused' if self.upstream_failed else 'ready')
            elif kind == 'open':
                if type(identity) is not int or identity in self.tasks:
                    raise EgressError('Relay stream ownership violated')
                if len(self.tasks) >= MAX_STREAMS:
                    await self.frames.send({'type': 'opened', 'id': identity, 'ok': False})
                    continue
                self.tasks[identity] = asyncio.create_task(self.open_stream(identity, message.get('host'), message.get('port')))
                self.peak_streams = max(self.peak_streams, len(self.tasks))
            elif kind == 'data':
                stream = self.streams.get(identity)
                if stream:
                    stream['sink'].feed(decode_data(message.get('data')))
            elif kind == 'credit':
                stream = self.streams.get(identity)
                if stream:
                    stream['window'].credit(message.get('bytes'))
            elif kind == 'close':
                task = self.tasks.get(identity)
                if task:
                    task.cancel()

    async def run(self):
        control = [asyncio.create_task(self.messages()), asyncio.create_task(self.heartbeat())]
        if self.grace_s:control.extend([asyncio.create_task(self.liveness()),asyncio.create_task(self.upstream_monitor())])
        try:
            done, _ = await asyncio.wait(control, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        except Exception as error:
            self.failure_transport = self.frames.stats()
            if isinstance(error, EgressError) and str(error) == 'Compute heartbeat was lost':
                self.failure_code = 'heartbeat_timeout'
            elif isinstance(error, EOFError):
                self.failure_code = 'channel_eof'
            elif isinstance(error, EgressError):
                self.failure_code = 'protocol_error'
            else:
                self.failure_code = type(error).__name__
            raise
        finally:
            for task in [*control, *self.tasks.values()]:
                task.cancel()
            await asyncio.gather(*control, *list(self.tasks.values()), return_exceptions=True)
            await self.frames.close()
            for stream in self.streams.values():
                stream['writer'].close()
            self.publish('closed')


def ssh_command(args):
    identity = job_id(args.job_id)
    if not re.fullmatch(r'[A-Za-z0-9_][A-Za-z0-9_.@-]*', args.ssh_host):
        raise EgressError('Use a configured SSH host alias')
    root = Path(args.state_root)
    script = Path(args.remote_script)
    if any(not p.is_absolute() or '..' in p.parts for p in (root, script)):
        raise EgressError('Use absolute remote script and private state paths')
    digest = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    # Verify the installed helper before srun. All arguments are public paths or
    # IDs; proxy credentials are generated only inside the compute allocation.
    bootstrap = ('import hashlib,os,sys;'
                 'assert hashlib.sha256(open(sys.argv[1],"rb").read()).hexdigest()==sys.argv[2],"Proxy source mismatch";'
                 'os.execvp(sys.argv[3],sys.argv[3:])')
    command = [args.remote_python, '-I', '-B', '-c', bootstrap, str(script), digest,
               args.srun, '--jobid='+identity, '--nodes=1', '--ntasks=1', '--cpus-per-task=1',
               '--mem=1G', '--overlap', '--exact', '--kill-on-bad-exit=1',
               args.remote_python, '-I', '-B', str(script), 'serve', '--state-root', str(root), '--job-id', identity]
    grace_s=getattr(args,'pause_grace_s',0)
    if grace_s:command.extend(['--pause-grace-s',str(grace_s)])
    if args.slurm_conf:
        command = ['env', 'SLURM_CONF='+args.slurm_conf, *command]
    config = getattr(args, 'ssh_config', '')
    prefix = ['ssh']
    if config:
        path = Path(config).expanduser().absolute()
        if path.resolve() != path:
            raise EgressError('SSH configuration must be canonical')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise EgressError('SSH configuration must be private and operator-owned')
        prefix.extend(['-F', str(path)])
    return [*prefix, '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax='+str(max(3,(grace_s+STALE_S+4)//5+2) if grace_s else 3),
            args.ssh_host, shlex.join(command)]


def tcp_pipe(host, port, interface):
    """Opaque SSH ProxyCommand transport; bind only this socket on macOS."""
    if sys.platform != 'darwin' or not 0 < port < 65536:
        raise EgressError('Interface-bound SSH transport requires macOS and a valid port')
    connection = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        # IP_BOUND_IF from the macOS SDK netinet/in.h; no global route changes.
        connection.setsockopt(socket.IPPROTO_IP, 25, socket.if_nametoindex(interface))
        connection.settimeout(15); connection.connect((host, port)); connection.settimeout(None)
        def upload():
            try:
                while data := os.read(0, 65536):
                    connection.sendall(data)
                connection.shutdown(socket.SHUT_WR)
            except OSError:
                pass
        threading.Thread(target=upload, daemon=True).start()
        while data := connection.recv(65536):
            sys.stdout.buffer.write(data); sys.stdout.buffer.flush()
    finally:
        connection.close()


async def connect(args):
    status = Path(args.status_file).expanduser().absolute()
    private_directory(status.parent, create=True)
    log = status.with_suffix('.ssh.log').open('ab')
    os.chmod(log.name, 0o600)
    process = None; awake = None; relay = None
    current = asyncio.current_task()
    loop = asyncio.get_running_loop()
    for number in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(number, current.cancel)
    try:
        if sys.platform == 'darwin':
            awake = subprocess.Popen(['/usr/bin/caffeinate', '-i', '-s', '-w', str(os.getpid())],
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        atomic(status, {'status': 'connecting', 'job_id': args.job_id, 'updated_at': time.time()})
        process = await asyncio.create_subprocess_exec(*ssh_command(args),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=log, limit=MAX_FRAME)
        relay = MacRelay(Frames(process.stdout, process.stdin), status=status,grace_s=args.pause_grace_s,
                         probe_hosts=probe_hosts(args.engine) if args.engine else ())
        await relay.run()
    finally:
        if process:
            # Drain remaining control frames while reaping SSH; otherwise a full
            # stdout pipe can prevent subprocess.wait() from completing.
            drain = asyncio.create_task(discard_remaining(process.stdout))
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    process.kill(); await process.wait()
            await drain
        if awake and awake.poll() is None:
            awake.terminate(); awake.wait()
        log.close()
        if relay:
            relay.publish('closed')


def main(argv=None):
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    compute = commands.add_parser('serve', help='Internal compute-side entry inside the selected allocation')
    compute.add_argument('--state-root', required=True)
    compute.add_argument('--job-id', required=True)
    compute.add_argument('--pause-grace-s',type=int,default=0)
    mac = commands.add_parser('connect', help='Keep a Mac exit connected to an existing Slurm allocation')
    mac.add_argument('--ssh-host', required=True)
    mac.add_argument('--ssh-config', default='', help='Optional private operator SSH config for this route only')
    mac.add_argument('--job-id', required=True)
    mac.add_argument('--pause-grace-s',type=int,default=0)
    mac.add_argument('--engine', choices=sorted(ENGINE_ROUTES), default='',
                     help="The job's engine; chooses the upstream hosts probed during short-outage recovery")
    mac.add_argument('--state-root', required=True, help='Private durable path on the cluster, outside checkouts')
    mac.add_argument('--remote-script', required=True, help='Published matching robofrontier/slurm_proxy.py on the cluster')
    mac.add_argument('--remote-python', default='python3')
    mac.add_argument('--srun', default='srun')
    mac.add_argument('--slurm-conf', default='')
    mac.add_argument('--status-file', default=str(Path.home()/'.robofrontier/slurm-egress/status.json'))
    pipe = commands.add_parser('tcp-pipe', help='macOS SSH ProxyCommand bound to one network interface')
    pipe.add_argument('--host', required=True)
    pipe.add_argument('--port', required=True, type=int)
    pipe.add_argument('--interface', required=True)
    args = parser.parse_args(argv)
    if hasattr(args,'pause_grace_s') and not 0<=args.pause_grace_s<=600:
        parser.error('pause-grace-s must be between 0 and 600')
    if args.command=='connect' and args.pause_grace_s and not args.engine:
        parser.error('--engine is required with --pause-grace-s')
    try:
        if args.command == 'tcp-pipe':
            tcp_pipe(args.host, args.port, args.interface)
            return 0
        asyncio.run(serve(args.state_root, job_id(args.job_id),grace_s=args.pause_grace_s) if args.command == 'serve' else connect(args))
    except (KeyboardInterrupt, asyncio.CancelledError):
        return 0
    except Exception as error:
        # Native credentials never enter this process; still avoid echoing
        # endpoints, proxy passwords, data frames or raw exception details.
        print('Slurm egress stopped ('+type(error).__name__+'); inspect private status/SSH log.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
