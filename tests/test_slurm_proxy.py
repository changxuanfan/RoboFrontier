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


class EnvironmentTests(unittest.TestCase):
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


class TransportTests(unittest.IsolatedAsyncioTestCase):
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
        self.compute = proxy.ComputeRelay(self.compute_frames, self.directory, '123')
        self.mac = proxy.MacRelay(proxy.Frames(self.mac_reader, self.mac_writer), dial=dial)
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

    async def test_channel_eof_removes_readiness_and_closes_listener(self):
        self.mac_task.cancel();await asyncio.gather(self.mac_task,return_exceptions=True)
        self.mac_writer.close()
        await asyncio.wait_for(asyncio.gather(self.compute_task,return_exceptions=True),2)
        self.assertFalse((self.directory/'ready.json').exists())
        self.assertTrue((self.directory/'closed.json').exists())
        with self.assertRaises(OSError):await asyncio.open_connection('127.0.0.1',self.port)

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


if __name__=='__main__':unittest.main()
