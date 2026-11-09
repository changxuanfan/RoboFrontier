"""Authenticated relay transport, latching loss and frozen isolation boundaries."""
import argparse
import asyncio
import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from robofrontier import slurm_proxy as proxy
from robofrontier.configuration import load_configuration
from robofrontier.policy_access import record, mode


class DestinationTests(unittest.TestCase):
    def test_only_model_provider_https_destinations_are_relayed(self):
        for host in ('api.openai.com', 'chatgpt.com', 'api.anthropic.com', 'anthropic.com'):
            self.assertTrue(proxy.target_allowed(host, 443), host)
        for host, port in (('api.anthropic.com', 80), ('evilanthropic.com', 443), ('anthropic.com.example', 443),
                           ('claude.ai', 443), ('API.ANTHROPIC.COM', 443), ('example.com', 443)):
            self.assertFalse(proxy.target_allowed(host, port), host)


class EngineProbeTests(unittest.IsolatedAsyncioTestCase):
    """Route health follows the hosts the job's own engine uses (B-3)."""
    def relay(self, engine, failing=()):
        dialled = []
        async def probe_dial(host):
            dialled.append(host)
            if host in failing: raise ConnectionRefusedError('fixture')
            return True
        return proxy.MacRelay(None, grace_s=60, probe_hosts=proxy.probe_hosts(engine), probe_dial=probe_dial), dialled

    def test_probe_hosts_come_from_the_relayed_destination_table(self):
        self.assertEqual(proxy.probe_hosts('claude'), ('api.anthropic.com',))
        self.assertEqual(set(proxy.probe_hosts('codex')), {'chatgpt.com', 'auth.openai.com'})
        for engine, route in proxy.ENGINE_ROUTES.items():
            for host in proxy.probe_hosts(engine):
                self.assertTrue(proxy.target_allowed(host, 443, route['domains']), host)
        with self.assertRaises(proxy.EgressError): proxy.probe_hosts('gemini')
        with self.assertRaises(proxy.EgressError): proxy.MacRelay(None, grace_s=60)
        with self.assertRaises(proxy.EgressError): proxy.MacRelay(None, grace_s=60, probe_hosts=('example.com',))

    async def test_claude_route_stays_available_when_only_openai_auth_fails(self):
        relay, dialled = self.relay('claude', failing=('auth.openai.com',))
        self.assertTrue(await relay.probe_upstream())
        self.assertEqual(dialled, ['api.anthropic.com'])
        with patch.object(proxy, 'HEARTBEAT_S', .005):
            monitor = asyncio.create_task(relay.upstream_monitor())
            await asyncio.sleep(.1); monitor.cancel(); await asyncio.gather(monitor, return_exceptions=True)
        self.assertFalse(relay.upstream_failed)
        self.assertGreater(len(dialled), 3)

    async def test_codex_route_needs_every_engine_host(self):
        relay, dialled = self.relay('codex')
        self.assertTrue(await relay.probe_upstream())
        self.assertEqual(set(dialled), {'chatgpt.com', 'auth.openai.com'})
        for host in ('chatgpt.com', 'auth.openai.com'):
            self.assertFalse(await self.relay('codex', failing=(host,))[0].probe_upstream(), host)
        self.assertFalse(await self.relay('claude', failing=('api.anthropic.com',))[0].probe_upstream())

    def test_connector_requires_an_engine_for_short_outage_recovery(self):
        base = ['connect', '--ssh-host', 'cluster', '--job-id', '123', '--state-root', '/private/egress',
                '--remote-script', '/private/helper.py']
        started = []
        async def connect(args): started.append(args.engine)  # never reaches SSH in this test
        with patch.object(proxy, 'connect', connect):
            for extra in (['--pause-grace-s', '120'], ['--pause-grace-s', '120', '--engine', 'gemini']):
                with patch('sys.stderr'), self.assertRaises(SystemExit):
                    proxy.main([*base, *extra])
            self.assertEqual(started, [])
            self.assertEqual(proxy.main([*base, '--pause-grace-s', '120', '--engine', 'claude']), 0)
        self.assertEqual(started, ['claude'])


class EnvironmentTests(unittest.TestCase):
    def test_quota_error_publishing_pause_fences_without_clearing_authority(self):
        import errno
        private=self.root/'engine';private.mkdir(mode=0o700)
        self.config['slurm']['egress_pause_s']=2;self.value.update(state='ready',grace_s=2)
        proxy.atomic(self.path,self.value);write=proxy.atomic
        def quota(path,value):
            if path.name=='EGRESS_PAUSED':raise OSError(errno.EDQUOT,'fixture quota')
            return write(path,value)
        with patch.dict(os.environ,{'SLURM_JOB_ID':'123','ROBOFRONTIER_JOB_PRIVATE_ROOT':str(private)}),patch.object(proxy,'atomic',quota):
            with self.assertRaises(proxy.EgressError):
                with proxy.environment(self.config,on_failure=self.failure.set):
                    write(self.path,{**self.value,'state':'paused'})
                    self.assertTrue(self.failure.wait(2))
        self.assertFalse((private/'EGRESS_PAUSED').exists())

    def test_short_outage_publishes_pause_and_same_instance_health_clears_only_its_marker(self):
        private=self.root/'engine';private.mkdir(mode=0o700)
        self.config['slurm']['egress_pause_s']=2
        self.value.update(state='ready',grace_s=2)
        proxy.atomic(self.path,self.value)
        with patch.dict(os.environ,{'SLURM_JOB_ID':'123','ROBOFRONTIER_JOB_PRIVATE_ROOT':str(private)}):
            with proxy.environment(self.config,on_failure=self.failure.set):
                marker=Path(os.environ['ROBOFRONTIER_EGRESS_PAUSE_FILE'])
                proxy.atomic(self.path,{**self.value,'state':'paused'})
                until=time.monotonic()+2
                while not marker.exists() and time.monotonic()<until:time.sleep(.01)
                self.assertTrue(marker.exists());self.assertFalse(self.failure.is_set())
                proxy.atomic(self.path,{**self.value,'heartbeat':time.time()})
                until=time.monotonic()+2
                while marker.exists() and time.monotonic()<until:time.sleep(.01)
                self.assertFalse(marker.exists());self.assertFalse(self.failure.is_set())

    def test_replaced_instance_fences_even_during_short_outage_grace(self):
        private=self.root/'engine';private.mkdir(mode=0o700)
        self.config['slurm']['egress_pause_s']=2;self.value.update(state='ready',grace_s=2)
        proxy.atomic(self.path,self.value)
        with patch.dict(os.environ,{'SLURM_JOB_ID':'123','ROBOFRONTIER_JOB_PRIVATE_ROOT':str(private)}):
            with self.assertRaises(proxy.EgressError):
                with proxy.environment(self.config,on_failure=self.failure.set):
                    proxy.atomic(self.path,{**self.value,'instance':'f'*32,'state':'paused'})
                    self.assertTrue(self.failure.wait(2))
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.root.chmod(0o700)
        self.directory = self.root/'123'
        self.directory.mkdir(mode=0o700)
        instance = 'a'*32
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args): pass
            def do_GET(self):
                self.send_response(200)
                self.send_header('X-RF-Instance', instance)
                self.send_header('Content-Length', '0'); self.end_headers()
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close); self.addCleanup(self.server.shutdown)
        self.value = {'schema': proxy.SCHEMA, 'job_id': '123', 'node': socket.gethostname(),
                      'instance': instance, 'heartbeat': time.time(),
                      'proxy_url': 'http://rf:'+('b'*64)+'@127.0.0.1:'+str(self.server.server_port)}
        self.path = self.directory/'ready.json'; proxy.atomic(self.path, self.value)
        self.config = {'slurm': {'egress_mode': 'mac-ssh', 'egress_root': str(self.root), 'egress_wait_s': .01}}
        self.failure = threading.Event()

    def test_admission_and_environment_restoration_keep_policy_network_disabled(self):
        with patch.dict(os.environ, {'SLURM_JOB_ID':'123','HTTPS_PROXY':'original','https_proxy':'lower-original'}):
            with proxy.environment(self.config, on_failure=self.failure.set):
                self.assertEqual(os.environ['HTTPS_PROXY'], self.value['proxy_url'])
                self.assertNotIn('https_proxy', os.environ)
                access = record(self.root/'run', checkouts=[])
                self.assertFalse(access['network'])
                self.assertEqual(mode(access['filesystem'], self.path), 'deny')
            self.assertEqual(os.environ['HTTPS_PROXY'], 'original')
            self.assertEqual(os.environ['https_proxy'], 'lower-original')
        self.assertFalse(self.failure.is_set())

    def test_lost_or_replaced_route_is_latched_without_replay(self):
        private=self.root/'engine';private.mkdir(mode=0o700)
        with patch.dict(os.environ, {'SLURM_JOB_ID':'123','ROBOFRONTIER_JOB_PRIVATE_ROOT':str(private)}):
            with self.assertRaisesRegex(proxy.EgressError, 'must not be automatically replayed'):
                with proxy.environment(self.config, on_failure=self.failure.set):
                    proxy.atomic(self.path, {**self.value, 'instance':'c'*32})
                    self.assertTrue(self.failure.wait(2))
                    # A later apparently good record cannot un-fence this owner.
                    proxy.atomic(self.path, self.value)
        diagnostic=json.loads((private/'EGRESS_DIAGNOSTIC.json').read_text())
        self.assertEqual(diagnostic['reason'],'instance_changed')
        self.assertNotIn('proxy_url',diagnostic)

    def test_stale_wrong_node_and_unsafe_record_fail_before_yield(self):
        for key, value in [('heartbeat',time.time()-30),('node','another-node'),('job_id','999')]:
            with self.subTest(key=key), patch.dict(os.environ, {'SLURM_JOB_ID':'123'}):
                proxy.atomic(self.path, {**self.value,key:value})
                with self.assertRaises(proxy.EgressError):
                    with proxy.environment(self.config, on_failure=self.failure.set):
                        self.fail('Unhealthy route admitted')
        proxy.atomic(self.path, self.value); self.path.chmod(0o644)
        with self.assertRaises(proxy.EgressError): proxy.read_record(self.path)

    def test_atomic_heartbeat_replacement_during_read_is_not_route_loss(self):
        original = os.fstat
        replaced = False
        def race(fd):
            nonlocal replaced
            if not replaced:
                replaced = True
                proxy.atomic(self.path, {**self.value, 'heartbeat':time.time()})
            return original(fd)
        with patch.object(proxy.os, 'fstat', race):
            current = proxy.read_record(self.path)
        self.assertEqual(current['instance'], self.value['instance'])
        self.assertGreaterEqual(current['heartbeat'], self.value['heartbeat'])

    def test_hardlinked_record_is_still_rejected(self):
        os.link(self.path, self.directory/'another-link')
        with self.assertRaises(proxy.EgressError):proxy.read_record(self.path)

    def test_old_configuration_shape_and_explicit_subscription_requirement(self):
        old = load_configuration(overrides={'schema_version':6})
        self.assertNotIn('egress_mode', old['slurm'])
        with self.assertRaisesRegex(ValueError, 'requires subscription'):
            load_configuration(overrides={'slurm': {'egress_mode':'mac-ssh','egress_root':str(self.root)}})

    def test_ssh_attaches_only_to_existing_job_with_keepalive_and_source_check(self):
        args = argparse.Namespace(job_id='123',ssh_host='cluster',state_root='/private/egress',
            remote_script='/private/helper.py',remote_python='/usr/bin/python3',srun='/usr/bin/srun',slurm_conf='/etc/slurm.conf')
        command = proxy.ssh_command(args)
        self.assertIn('ServerAliveInterval=5', command)
        self.assertIn('--jobid=123', command[-1])
        self.assertIn('sha256', command[-1])
        self.assertNotIn('sbatch', command[-1])
        self.assertNotIn('password', command[-1])

    def test_operator_ssh_configuration_is_scoped_and_private(self):
        config=self.root/'ssh-config';config.write_text('Host cluster\n');config.chmod(0o600)
        args=argparse.Namespace(job_id='123',ssh_host='cluster',ssh_config=str(config),state_root='/private/egress',
            remote_script='/private/helper.py',remote_python='/usr/bin/python3',srun='/usr/bin/srun',slurm_conf='')
        self.assertEqual(proxy.ssh_command(args)[:3],['ssh','-F',str(config)])
        config.chmod(0o644)
        with self.assertRaises(proxy.EgressError):proxy.ssh_command(args)


class SchedulingTests(unittest.IsolatedAsyncioTestCase):
    async def test_credit_writer_failure_closes_channel_and_surfaces_to_receiver(self):
        reader = asyncio.StreamReader()
        class Writer:
            closed = False
            def write(self, data): raise BrokenPipeError('fixture')
            async def drain(self): pass
            def close(self): self.closed = True
        writer = Writer(); frames = proxy.Frames(reader, writer)
        reader.feed_data(b'{"type":"data","id":1,"data":"fixture"}\n')
        self.assertEqual((await frames.receive())['type'], 'data')
        await asyncio.sleep(0)
        self.assertTrue(writer.closed)
        with self.assertRaises(BrokenPipeError): await frames.receive()
        await frames.close()

    async def test_close_reaps_a_credit_writer_blocked_in_drain(self):
        reader = asyncio.StreamReader(); entered = asyncio.Event()
        class Writer:
            def write(self, data): pass
            async def drain(self): entered.set(); await asyncio.Event().wait()
        frames = proxy.Frames(reader, Writer())
        reader.feed_data(b'{"type":"data","id":1,"data":"fixture"}\n')
        await frames.receive(); await entered.wait()
        credit = frames.credit_task
        self.assertGreaterEqual(frames.stats()['active_write_wait_s'], 0)
        await asyncio.wait_for(frames.close(), .2)
        self.assertTrue(credit.done())
        self.assertIsNone(frames.credit_task)

    async def test_full_duplex_backpressure_keeps_receivers_and_heartbeats_live(self):
        # SSH/Slurm pipes have high/low water marks. Both writers can pause
        # while several complete incoming frames are already available.
        class Pipe:
            def __init__(self):
                self.queue = asyncio.Queue(); self.buffered = 0
                self.writable = asyncio.Event(); self.writable.set()
                self.paused = asyncio.Event()
            def write(self, data):
                self.queue.put_nowait(data); self.buffered += len(data)
                if self.buffered > 32768:
                    self.writable.clear(); self.paused.set()
            async def drain(self):
                await self.writable.wait()
            async def readline(self):
                data = await self.queue.get(); self.buffered -= len(data)
                if self.buffered <= 8192: self.writable.set()
                return data
        outgoing, incoming = Pipe(), Pipe()
        left = proxy.Frames(incoming, outgoing)
        right = proxy.Frames(outgoing, incoming)
        tasks = []
        observed = [asyncio.Event(), asyncio.Event()]
        async def receive(frames, done):
            while True:
                value = await frames.receive()
                if value['type'] == 'ping': done.set()
        try:
            for frames in (left, right):
                tasks += [asyncio.create_task(frames.send({'type':'data','id':i,'data':'x'*11000})) for i in range(20)]
            await asyncio.wait_for(asyncio.gather(outgoing.paused.wait(), incoming.paused.wait()), 1)
            tasks += [asyncio.create_task(receive(left, observed[0])), asyncio.create_task(receive(right, observed[1]))]
            sends = [asyncio.create_task(frames.send({'type':'ping'})) for frames in (left, right)]
            tasks += sends
            await asyncio.wait_for(asyncio.gather(*sends, *(event.wait() for event in observed)), 1)
            await asyncio.wait_for(asyncio.gather(*tasks[:-4]), 1)
        finally:
            for task in tasks: task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

    async def test_shared_channel_bounds_bytes_buffered_below_the_frame_scheduler(self):
        sent=[]
        class Writer:
            def write(self,data):sent.append(data)
            async def drain(self):pass  # SSH can accept bytes before network delivery.
        frames=proxy.Frames(None,Writer())
        bulk=[asyncio.create_task(frames.send({'type':'data','id':i,'data':'x'*11000})) for i in range(96)]
        try:
            await asyncio.sleep(.03)
            await asyncio.wait_for(frames.send({'type':'ping'}),.1)
            buffered=sum(len(data) for data in sent if json.loads(data)['type']=='data')
            self.assertLessEqual(buffered,getattr(proxy,'CHANNEL_WINDOW',65536))
            self.assertGreater(buffered,0)
            self.assertEqual(json.loads(sent[-1])['type'],'ping')
        finally:
            for task in bulk:task.cancel()
            await asyncio.gather(*bulk,return_exceptions=True)

    async def test_heartbeat_overtakes_queued_bulk_frames_on_a_slow_channel(self):
        release=asyncio.Event();entered=asyncio.Event();sent=[]
        class Writer:
            def write(self,data):sent.append(json.loads(data)['type']);entered.set()
            async def drain(self):await release.wait();await asyncio.sleep(.01)
        frames=proxy.Frames(None,Writer())
        bulk=[asyncio.create_task(frames.send({'type':'data','id':i,'data':'fixture'})) for i in range(36)]
        await entered.wait();await asyncio.sleep(0)
        heartbeat=asyncio.create_task(frames.send({'type':'pong'}))
        await asyncio.sleep(0);release.set()
        try:
            await asyncio.wait_for(heartbeat,.15)
            self.assertEqual(sent[:2],['data','pong'])
        finally:
            for task in [*bulk,heartbeat]:task.cancel()
            await asyncio.gather(*bulk,heartbeat,return_exceptions=True)


class RelayFixture:
    grace_s=0
    async def asyncSetUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name).resolve(); self.directory.chmod(0o700)
        self.future = asyncio.get_running_loop().create_future()
        async def accept(reader, writer): self.future.set_result(proxy.Frames(reader, writer))
        self.frame_server = await asyncio.start_server(accept, '127.0.0.1', 0)
        self.mac_reader, self.mac_writer = await asyncio.open_connection('127.0.0.1', self.frame_server.sockets[0].getsockname()[1],limit=proxy.MAX_FRAME)
        self.compute_frames = await self.future
        async def echo(reader, writer):
            try:
                while data := await reader.read(32768): writer.write(data); await writer.drain()
            except OSError:
                pass  # The abandoned-stream case deliberately resets its peer.
            finally: writer.close()
        self.echo_server = await asyncio.start_server(echo, '127.0.0.1', 0)
        async def dial(host, port):
            return await asyncio.open_connection('127.0.0.1', self.echo_server.sockets[0].getsockname()[1])
        async def probe():return True
        self.compute = proxy.ComputeRelay(self.compute_frames, self.directory, '123',grace_s=self.grace_s)
        self.mac = proxy.MacRelay(proxy.Frames(self.mac_reader, self.mac_writer), dial=dial,grace_s=self.grace_s,probe=probe)
        self.compute_task = asyncio.create_task(self.compute.run())
        self.mac_task = asyncio.create_task(self.mac.run())
        for _ in range(50):
            if (self.directory/'ready.json').exists(): break
            await asyncio.sleep(.02)
        self.value = proxy.read_record(self.directory/'ready.json')
        self.port = proxy.validate_record(self.value, '123', socket.gethostname()).port

    async def asyncTearDown(self):
        for task in (self.mac_task,self.compute_task): task.cancel()
        await asyncio.gather(self.mac_task,self.compute_task,return_exceptions=True)
        for writer in (self.mac_writer,self.compute_frames.writer):
            writer.close()
        for server in (self.echo_server,self.frame_server):
            server.close(); await server.wait_closed()
        self.temporary.cleanup()

    async def request(self, target, auth=True):
        reader, writer = await asyncio.open_connection('127.0.0.1',self.port)
        header = 'Proxy-Authorization: '+self.compute.authorization+'\r\n' if auth else ''
        writer.write(('CONNECT '+target+' HTTP/1.1\r\n'+header+'\r\n').encode());await writer.drain()
        reply = await asyncio.wait_for(reader.readuntil(b'\r\n\r\n'),2)
        return reader,writer,reply

class TransportTests(RelayFixture,unittest.IsolatedAsyncioTestCase):
    async def test_actual_authenticated_connect_multiplexes_opaque_bytes(self):
        async def stream(index):
            reader,writer,reply = await self.request('auth.openai.com:443')
            self.assertIn(b'200 Connection Established',reply)
            data=b'\x16\x03\x01OPAQUE_TLS_FIXTURE_'+bytes([index])*(proxy.WINDOW*4)
            writer.write(data);await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)),15),data)
            writer.close()
        await asyncio.gather(*(stream(i) for i in range(36)))
        self.assertEqual((self.directory/'ready.json').stat().st_mode&0o777,0o600)

    async def test_missing_auth_and_non_openai_destination_never_dial(self):
        for target,auth,status in [('auth.openai.com:443',False,b'407'),('example.org:443',True,b'403'),
                                   ('127.0.0.1:443',True,b'403'),('auth.openai.com:80',True,b'403')]:
            reader,writer,reply=await self.request(target,auth)
            self.assertIn(status,reply);writer.close()
        self.assertEqual(self.mac.tasks,{})

    async def test_36_uploads_keep_heartbeat_alive_on_a_throttled_shared_channel(self):
        self.mac_task.cancel();await asyncio.gather(self.mac_task,return_exceptions=True)
        self.mac.last_pong=None
        class SlowChannel:
            def __init__(self,writer):self.writer=writer
            def write(self,data):self.writer.write(data)
            async def drain(self):await asyncio.sleep(.015);await self.writer.drain()
            def close(self):self.writer.close()
        for frames in (self.mac.frames,self.compute_frames):frames.writer=SlowChannel(frames.writer)
        async def stream(i):
            reader,writer,reply=await self.request('auth.openai.com:443')
            self.assertIn(b'200 Connection Established',reply)
            data=bytes([i])*(proxy.CHUNK*4)
            writer.write(data);await writer.drain()
            self.assertEqual(await asyncio.wait_for(reader.readexactly(len(data)),15),data)
            writer.close()
        with patch.object(proxy,'HEARTBEAT_S',.03),patch.object(proxy,'STALE_S',.35):
            self.mac_task=asyncio.create_task(self.mac.run())
            await asyncio.gather(*(stream(i) for i in range(36)))
            await asyncio.sleep(.4)
            self.assertFalse(self.mac_task.done());self.assertFalse(self.compute_task.done())
            self.assertLess(self.mac.frames.max_control_wait_s,.25)
            self.assertLess(self.compute_frames.max_control_wait_s,.25)

    async def test_channel_eof_removes_readiness_and_closes_listener(self):
        self.mac_task.cancel();await asyncio.gather(self.mac_task,return_exceptions=True)
        self.mac_writer.close()
        await asyncio.wait_for(asyncio.gather(self.compute_task,return_exceptions=True),2)
        self.assertFalse((self.directory/'ready.json').exists())
        self.assertTrue((self.directory/'closed.json').exists())
        with self.assertRaises(OSError):await asyncio.open_connection('127.0.0.1',self.port)

    async def test_shutdown_does_not_hold_route_ownership_on_a_blocked_channel(self):
        _,client,reply=await self.request('auth.openai.com:443')
        self.assertIn(b'200 Connection Established',reply)
        blocked=asyncio.Event()
        class BlockedWriter:
            def __init__(self,writer):self.writer=writer
            def write(self,data):self.writer.write(data)
            async def drain(self):await blocked.wait()
            def close(self):self.writer.close()
        self.compute_frames.writer=BlockedWriter(self.compute_frames.writer)
        self.compute_task.cancel()
        try:
            await asyncio.wait_for(asyncio.shield(asyncio.gather(self.compute_task,return_exceptions=True)),3)
            self.assertFalse((self.directory/'ready.json').exists())
            self.assertEqual(len(self.compute.clients),0)
        finally:blocked.set();client.close()

    async def test_an_abandoned_stream_does_not_close_other_connections(self):
        _,writer,reply=await self.request('auth.openai.com:443')
        self.assertIn(b'200 Connection Established',reply)
        writer.write(b'abandoned'*32768);await writer.drain();writer.close()
        await asyncio.sleep(.1)
        reader,writer,reply=await self.request('api.openai.com:443')
        self.assertIn(b'200 Connection Established',reply)
        writer.write(b'still-connected');await writer.drain()
        self.assertEqual(await asyncio.wait_for(reader.readexactly(15),2),b'still-connected')
        self.assertFalse(self.compute_task.done());self.assertFalse(self.mac_task.done());writer.close()

    async def test_slow_destination_does_not_block_other_streams_or_heartbeat(self):
        self.mac_task.cancel();await asyncio.gather(self.mac_task,return_exceptions=True)
        release=asyncio.Event()
        class SlowWriter:
            def __init__(self,writer):self.writer=writer
            def write(self,data):self.writer.write(data)
            async def drain(self):await release.wait();await self.writer.drain()
            def close(self):self.writer.close()
        async def dial(host,port):
            reader,writer=await asyncio.open_connection('127.0.0.1',self.echo_server.sockets[0].getsockname()[1])
            return reader,SlowWriter(writer) if host=='slow.openai.com' else writer
        self.mac.dial=dial;self.mac.last_pong=None
        with patch.object(proxy,'HEARTBEAT_S',.03),patch.object(proxy,'STALE_S',.35):
            self.mac_task=asyncio.create_task(self.mac.run())
            try:
                _,slow,_=await self.request('slow.openai.com:443')
                slow.write(b'blocked');await slow.drain();await asyncio.sleep(.05)
                reader,fast,reply=await self.request('auth.openai.com:443')
                self.assertIn(b'200 Connection Established',reply)
                fast.write(b'fast');await fast.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(4),.3),b'fast')
                await asyncio.sleep(.5)
                self.assertFalse(self.mac_task.done());self.assertFalse(self.compute_task.done())
                fast.close();slow.close()
            finally:release.set()

    async def test_slow_native_consumer_does_not_block_other_streams_or_heartbeat(self):
        self.mac_task.cancel();await asyncio.gather(self.mac_task,return_exceptions=True)
        self.mac.last_pong=None
        release=asyncio.Event()
        class SlowWriter:
            def __init__(self,writer):self.writer=writer
            def write(self,data):self.writer.write(data)
            async def drain(self):await release.wait();await self.writer.drain()
            def close(self):self.writer.close()
        with patch.object(proxy,'HEARTBEAT_S',.03),patch.object(proxy,'STALE_S',.35):
            self.mac_task=asyncio.create_task(self.mac.run())
            try:
                _,slow,_=await self.request('auth.openai.com:443')
                stream=next(iter(self.compute.streams.values()))
                sink=stream['sink'];sink.writer=SlowWriter(sink.writer)
                slow.write(b'x'*(proxy.WINDOW*4));await slow.drain()
                await asyncio.sleep(.05)
                reader,fast,reply=await self.request('api.openai.com:443')
                self.assertIn(b'200 Connection Established',reply)
                fast.write(b'fast');await fast.drain()
                self.assertEqual(await asyncio.wait_for(reader.readexactly(4),.3),b'fast')
                await asyncio.sleep(.5)
                self.assertFalse(self.mac_task.done());self.assertFalse(self.compute_task.done())
                self.assertLessEqual(sink.pending,proxy.WINDOW)
                fast.close();slow.close()
            finally:release.set()


class RecoverableTransportTests(RelayFixture,unittest.IsolatedAsyncioTestCase):
    grace_s=1.2
    async def asyncSetUp(self):
        self.clocks=[patch.object(proxy,'HEARTBEAT_S',.02),patch.object(proxy,'STALE_S',.15)]
        for item in self.clocks:item.start()
        try:await RelayFixture.asyncSetUp(self)
        except BaseException:
            for item in self.clocks:item.stop()
            raise
    async def asyncTearDown(self):
        try:await RelayFixture.asyncTearDown(self)
        finally:
            for item in self.clocks:item.stop()
    async def test_short_blackhole_keeps_instance_listener_and_original_stream(self):
        reader,writer,_=await self.request('auth.openai.com:443')
        writer.write(b'before');await writer.drain();self.assertEqual(await reader.readexactly(6),b'before')
        release=asyncio.Event();original=self.mac.frames.reader
        class PausedReader:
            async def readline(self):await release.wait();return await original.readline()
        self.mac.frames.reader=PausedReader()
        await asyncio.sleep(.4)
        paused=proxy.read_record(self.directory/'ready.json')
        self.assertEqual(paused['state'],'paused')
        self.assertFalse(self.mac_task.done());self.assertFalse(self.compute_task.done())
        release.set();await asyncio.sleep(.2)
        recovered=proxy.read_record(self.directory/'ready.json')
        self.assertEqual(recovered['state'],'ready');self.assertEqual(recovered['instance'],self.value['instance'])
        self.assertEqual(recovered['proxy_url'],self.value['proxy_url'])
        writer.write(b'after');await writer.drain();self.assertEqual(await reader.readexactly(5),b'after');writer.close()
    async def test_long_blackhole_fences_and_never_recreates_listener(self):
        original=self.mac.frames.reader
        class PausedReader:
            async def readline(self):await asyncio.Event().wait();return await original.readline()
        self.mac.frames.reader=PausedReader()
        await asyncio.sleep(1.7)
        self.assertTrue(self.mac_task.done())
        self.assertFalse((self.directory/'ready.json').exists())

    async def test_upstream_outage_holds_new_tunnel_until_probe_recovers(self):
        self.mac.upstream_failed=True
        available=False
        async def probe():return available
        self.mac.probe=probe
        await asyncio.sleep(.08)
        self.assertEqual(proxy.read_record(self.directory/'ready.json')['state'],'paused')
        request=asyncio.create_task(self.request('auth.openai.com:443'))
        await asyncio.sleep(.12);self.assertFalse(request.done())
        available=True
        reader,writer,reply=await asyncio.wait_for(request,.6)
        self.assertIn(b'200 Connection Established',reply)
        writer.write(b'unique');await writer.drain();self.assertEqual(await reader.readexactly(6),b'unique');writer.close()

    async def until(self,condition,timeout=1.5):
        deadline=time.monotonic()+timeout
        while not condition() and time.monotonic()<deadline:await asyncio.sleep(.01)
        return condition()

    async def test_one_stream_reset_fails_only_that_stream(self):
        # Block the probe so only the stream failures could change route health (B-4).
        self.mac.probe=lambda:asyncio.Event().wait()
        pings=[];send=self.mac.frames.send
        async def record(value):
            if value.get('type')=='ping':pings.append(value['network_available'])
            return await send(value)
        self.mac.frames.send=record
        class ResetReader:
            async def read(self,size):raise ConnectionResetError('fixture reset by provider')
        echo=self.echo_server.sockets[0].getsockname()[1];dials=[]
        async def dial(host,port):
            dials.append(host)
            if len(dials)==1:raise ConnectionResetError('fixture dial reset')
            _,writer=await asyncio.open_connection('127.0.0.1',echo)
            return ResetReader(),writer
        self.mac.dial=dial
        for target in ('api.anthropic.com:443','chatgpt.com:443'):
            reader,writer=await asyncio.open_connection('127.0.0.1',self.port)
            writer.write(('CONNECT '+target+' HTTP/1.1\r\nProxy-Authorization: '+self.compute.authorization+'\r\n\r\n').encode())
            await writer.drain()
            await asyncio.wait_for(reader.read(),2);writer.close()
        self.assertEqual(len(dials),2)
        pings.clear()
        self.assertTrue(await self.until(lambda:len(pings)>=3))
        self.assertFalse(self.mac.upstream_failed);self.assertTrue(all(pings))
        self.assertTrue(self.compute.upstream_ready)
        self.assertEqual(proxy.read_record(self.directory/'ready.json')['state'],'ready')
        reader,writer,reply=await self.request('auth.openai.com:443')
        self.assertIn(b'200 Connection Established',reply);writer.close()

    async def test_three_failed_probes_pause_and_one_success_resumes(self):
        results=asyncio.Queue();taken=[]
        async def probe():
            value=await results.get();taken.append(value);return value
        self.mac.probe=probe
        for _ in range(2):results.put_nowait(False)  # the documented threshold is three
        self.assertTrue(await self.until(lambda:len(taken)==2))
        await asyncio.sleep(.1)
        self.assertFalse(self.mac.upstream_failed)
        self.assertEqual(proxy.read_record(self.directory/'ready.json')['state'],'ready')
        results.put_nowait(False)
        self.assertTrue(await self.until(lambda:self.mac.upstream_failed))
        self.assertTrue(await self.until(lambda:proxy.read_record(self.directory/'ready.json')['state']=='paused'))
        results.put_nowait(True)
        self.assertTrue(await self.until(lambda:not self.mac.upstream_failed))
        self.assertTrue(await self.until(lambda:proxy.read_record(self.directory/'ready.json')['state']=='ready'))
        self.assertFalse(self.mac_task.done());self.assertFalse(self.compute_task.done())

if __name__=='__main__':unittest.main()
