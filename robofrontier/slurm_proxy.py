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

SCHEMA = 'robofrontier.slurm-egress.v1'
HEARTBEAT_S = 2
STALE_S = 12
MAX_STREAMS = 256
MAX_FRAME = 100000


class EgressError(RuntimeError):
    pass


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
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1 or info.st_size > 16384):
            raise EgressError('Unsafe egress readiness record')
        value = json.loads(stream.read(16385))
    return value


def job_id(value):
    if not re.fullmatch(r'[0-9]{1,16}', value):
        raise EgressError('An existing numeric Slurm allocation is required')
    return value


def target_allowed(host, port):
    return (port == 443 and isinstance(host, str) and len(host) <= 253
            and bool(re.fullmatch(r'[a-z0-9.-]+', host))
            and any(host == domain or host.endswith('.'+domain)
                    for domain in ('openai.com', 'chatgpt.com')))


def validate_record(record, identity, node):
    try:
        url = urlsplit(record['proxy_url'])
        good = (record['schema'] == SCHEMA and record['job_id'] == identity and record['node'] == node
                and isinstance(record['instance'], str) and len(record['instance']) == 32
                and -2 <= time.time()-record['heartbeat'] < STALE_S
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
    root = private_directory(slurm['egress_root'], create=True)
    directory = root/identity
    deadline = time.monotonic()+slurm['egress_wait_s']
    while True:
        try:
            private_directory(directory)
            record = read_record(directory/'ready.json')
            url = validate_record(record, identity, socket.gethostname())
            health(record, url)
            break
        except (OSError, ValueError, EgressError):
            if time.monotonic() >= deadline:
                raise EgressError('Managed Mac egress did not become ready before admission') from None
            time.sleep(.2)
    keys = ('HTTPS_PROXY', 'HTTP_PROXY', 'ALL_PROXY', 'NO_PROXY', 'https_proxy', 'http_proxy',
            'all_proxy', 'no_proxy', 'ROBOFRONTIER_EGRESS_ROOT', 'ROBOFRONTIER_EGRESS_INSTANCE')
    saved = {k: os.environ.get(k) for k in keys}
    for key in keys:
        os.environ.pop(key, None)
    os.environ.update(HTTPS_PROXY=record['proxy_url'], HTTP_PROXY=record['proxy_url'],
                      ALL_PROXY=record['proxy_url'], NO_PROXY='127.0.0.1,localhost',
                      ROBOFRONTIER_EGRESS_ROOT=str(root), ROBOFRONTIER_EGRESS_INSTANCE=record['instance'])
    stopped = threading.Event()
    failed = threading.Event()
    def watch():
        while not stopped.wait(.5):
            try:
                current = read_record(directory/'ready.json')
                validate_record(current, identity, socket.gethostname())
                if current['instance'] != record['instance'] or current['proxy_url'] != record['proxy_url']:
                    raise EgressError('Egress identity changed')
            except Exception:
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
        self.lock = asyncio.Lock()

    async def send(self, value):
        data = json.dumps(value, separators=(',', ':')).encode()+b'\n'
        if len(data) > MAX_FRAME:
            raise EgressError('Relay frame limit exceeded')
        async with self.lock:
            self.writer.write(data)
            await self.writer.drain()

    async def receive(self):
        line = await self.reader.readline()
        if not line:
            raise EOFError()
        if len(line) > MAX_FRAME:
            raise EgressError('Relay frame limit exceeded')
        value = json.loads(line)
        if not isinstance(value, dict):
            raise EgressError('Invalid relay frame')
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


async def copy_to_frames(reader, frames, identity):
    while data := await reader.read(32768):
        await frames.send({'type': 'data', 'id': identity, 'data': base64.b64encode(data).decode()})


class ComputeRelay:
    def __init__(self, frames, directory, identity):
        self.frames, self.directory, self.identity = frames, directory, identity
        self.instance = secrets.token_hex(16)
        self.password = secrets.token_hex(32)
        self.authorization = 'Basic '+base64.b64encode(('rf:'+self.password).encode()).decode()
        self.streams = {}; self.next_id = 0; self.last_ping = time.monotonic()

    async def client(self, reader, writer):
        identity = None
        try:
            header = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'), 10)
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
                writer.write(('HTTP/1.1 200 OK\r\nContent-Length: 0\r\nX-RF-Instance: '+self.instance+'\r\n\r\n').encode())
                await writer.drain(); return
            host, port = target.rsplit(':', 1)
            if (method != 'CONNECT' or version != 'HTTP/1.1' or not target_allowed(host, int(port))
                    or len(self.streams) >= MAX_STREAMS):
                writer.write(b'HTTP/1.1 403 Forbidden\r\nContent-Length: 0\r\n\r\n')
                await writer.drain(); return
            self.next_id += 1; identity = self.next_id
            opened = asyncio.get_running_loop().create_future()
            self.streams[identity] = {'writer': writer, 'opened': opened}
            await self.frames.send({'type': 'open', 'id': identity, 'host': host, 'port': int(port)})
            if not await asyncio.wait_for(opened, 20):
                return
            writer.write(b'HTTP/1.1 200 Connection Established\r\n\r\n'); await writer.drain()
            await copy_to_frames(reader, self.frames, identity)
        except (OSError, ValueError, EOFError, asyncio.TimeoutError, asyncio.IncompleteReadError,
                asyncio.LimitOverrunError, EgressError):
            pass
        finally:
            if identity is not None:
                self.streams.pop(identity, None)
                try:
                    await self.frames.send({'type': 'close', 'id': identity})
                except (OSError, EgressError):
                    pass
            writer.close()

    async def messages(self):
        while True:
            if time.monotonic()-self.last_ping > STALE_S:
                raise EgressError('Mac heartbeat was lost')
            message = await asyncio.wait_for(self.frames.receive(), STALE_S)
            kind = message.get('type')
            if kind == 'ping':
                self.last_ping = time.monotonic()
                atomic(self.directory/'ready.json', {**self.record, 'heartbeat': time.time()})
                await self.frames.send({'type': 'pong'})
                continue
            stream = self.streams.get(message.get('id'))
            if stream is None:
                continue
            if kind == 'opened' and not stream['opened'].done():
                stream['opened'].set_result(message.get('ok') is True)
            elif kind == 'data':
                try:
                    stream['writer'].write(decode_data(message.get('data')))
                    await stream['writer'].drain()
                except OSError:
                    stream['writer'].close()
                    await self.frames.send({'type': 'close', 'id': message['id']})
            elif kind == 'close':
                if not stream['opened'].done():
                    stream['opened'].set_result(False)
                stream['writer'].close()

    async def run(self):
        server = await asyncio.start_server(self.client, '127.0.0.1', 0, limit=8193)
        port = server.sockets[0].getsockname()[1]
        self.record = {'schema': SCHEMA, 'job_id': self.identity, 'node': socket.gethostname(),
                       'instance': self.instance, 'proxy_url': 'http://rf:'+self.password+'@127.0.0.1:'+str(port),
                       'heartbeat': time.time()}
        atomic(self.directory/'ready.json', self.record)
        try:
            await self.frames.send({'type': 'ready', 'job_id': self.identity, 'node': self.record['node']})
            async with server:
                await self.messages()
        finally:
            server.close(); await server.wait_closed()
            for stream in list(self.streams.values()):
                stream['writer'].close()
            current = self.directory/'ready.json'
            if current.exists() and read_record(current).get('instance') == self.instance:
                current.unlink()
            atomic(self.directory/'closed.json', {'schema': SCHEMA, 'instance': self.instance, 'closed_at': time.time()})


async def serve(root, identity):
    if sys.platform != 'linux' or os.environ.get('SLURM_JOB_ID') != identity:
        raise EgressError('Compute egress must run inside the selected Slurm allocation')
    current = asyncio.current_task()
    for number in (signal.SIGTERM, signal.SIGINT):
        asyncio.get_running_loop().add_signal_handler(number, current.cancel)
    root = private_directory(root, create=True)
    directory = private_directory(root/job_id(identity), create=True)
    fd = os.open(directory/'owner.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077 or info.st_nlink != 1:
            raise EgressError('Unsafe egress ownership lock')
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            await ComputeRelay(await stdio_frames(), directory, identity).run()
        except EOFError:
            pass  # Channel closure is terminal; never restart or replay it.
    finally:
        os.close(fd)


class MacRelay:
    def __init__(self, frames, *, status=None, dial=None):
        self.frames, self.status = frames, status
        self.dial = dial or asyncio.open_connection
        self.streams = {}; self.tasks = {}; self.last_pong = None; self.ready = None

    def publish(self, state):
        if self.status:
            atomic(self.status, {'status': state, 'updated_at': time.time(),
                                 **(self.ready or {})})

    async def open_stream(self, identity, host, port):
        writer = None
        try:
            if not target_allowed(host, port):
                raise EgressError('Relay destination denied')
            reader, writer = await asyncio.wait_for(self.dial(host, port), 15)
            self.streams[identity] = writer
            await self.frames.send({'type': 'opened', 'id': identity, 'ok': True})
            await copy_to_frames(reader, self.frames, identity)
        except (OSError, asyncio.TimeoutError, EgressError):
            await self.frames.send({'type': 'opened', 'id': identity, 'ok': False})
        finally:
            self.streams.pop(identity, None); self.tasks.pop(identity, None)
            if writer:
                writer.close()
            await self.frames.send({'type': 'close', 'id': identity})

    async def heartbeat(self):
        while True:
            if self.last_pong is not None and time.monotonic()-self.last_pong > STALE_S:
                raise EgressError('Compute heartbeat was lost')
            await self.frames.send({'type': 'ping'})
            await asyncio.sleep(HEARTBEAT_S)

    async def messages(self):
        while True:
            message = await self.frames.receive()
            kind, identity = message.get('type'), message.get('id')
            if kind == 'ready':
                self.ready = {'job_id': job_id(message['job_id']), 'node': message['node']}
                self.last_pong = time.monotonic(); self.publish('ready')
            elif kind == 'pong':
                self.last_pong = time.monotonic(); self.publish('ready')
            elif kind == 'open':
                if type(identity) is not int or identity in self.tasks or len(self.tasks) >= MAX_STREAMS:
                    raise EgressError('Relay stream ownership/limit violated')
                self.tasks[identity] = asyncio.create_task(self.open_stream(identity, message.get('host'), message.get('port')))
            elif kind == 'data':
                writer = self.streams.get(identity)
                if writer:
                    try:
                        writer.write(decode_data(message.get('data'))); await writer.drain()
                    except OSError:
                        writer.close()
                        await self.frames.send({'type': 'close', 'id': identity})
            elif kind == 'close':
                writer = self.streams.get(identity)
                if writer:
                    writer.close()
                task = self.tasks.get(identity)
                if task:
                    task.cancel()

    async def run(self):
        control = [asyncio.create_task(self.messages()), asyncio.create_task(self.heartbeat())]
        try:
            done, _ = await asyncio.wait(control, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                await task
        finally:
            for task in [*control, *self.tasks.values()]:
                task.cancel()
            await asyncio.gather(*control, *list(self.tasks.values()), return_exceptions=True)
            for writer in self.streams.values():
                writer.close()
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
    command = [args.remote_python, '-I', '-c', bootstrap, str(script), digest,
               args.srun, '--jobid='+identity, '--nodes=1', '--ntasks=1', '--cpus-per-task=1',
               '--mem=1G', '--overlap', '--exact', '--kill-on-bad-exit=1',
               args.remote_python, '-I', str(script), 'serve', '--state-root', str(root), '--job-id', identity]
    if args.slurm_conf:
        command = ['env', 'SLURM_CONF='+args.slurm_conf, *command]
    return ['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=20',
            '-o', 'ServerAliveInterval=5', '-o', 'ServerAliveCountMax=3',
            args.ssh_host, shlex.join(command)]


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
        relay = MacRelay(Frames(process.stdout, process.stdin), status=status)
        await relay.run()
    finally:
        if process:
            process.stdin.close()
            try:
                await asyncio.wait_for(process.wait(), 5)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), 3)
                except asyncio.TimeoutError:
                    process.kill(); await process.wait()
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
    mac = commands.add_parser('connect', help='Keep a Mac exit connected to an existing Slurm allocation')
    mac.add_argument('--ssh-host', required=True)
    mac.add_argument('--job-id', required=True)
    mac.add_argument('--state-root', required=True, help='Private durable path on the cluster, outside checkouts')
    mac.add_argument('--remote-script', required=True, help='Published matching robofrontier/slurm_proxy.py on the cluster')
    mac.add_argument('--remote-python', default='python3')
    mac.add_argument('--srun', default='srun')
    mac.add_argument('--slurm-conf', default='')
    mac.add_argument('--status-file', default=str(Path.home()/'.robofrontier/slurm-egress/status.json'))
    args = parser.parse_args(argv)
    try:
        asyncio.run(serve(args.state_root, job_id(args.job_id)) if args.command == 'serve' else connect(args))
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
