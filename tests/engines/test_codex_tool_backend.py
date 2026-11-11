"""Kernel-enforced broker boundaries, including concurrent roles and forged paths."""
import base64
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.engines.common.landlock import abi
from robofrontier.engines.codex import tool_backend
from robofrontier.engines.codex.launch import launch_config
from robofrontier.configuration import load_configuration
from robofrontier.runtime.access import record, mode
from robofrontier.runtime.setup import write_json


def fixture(base, name):
    run = base/'repo'/name
    for folder in ('private/inputs', 'public', 'workspace'):
        (run/folder).mkdir(parents=True)
    (run/'private/secret').write_text('PRIVATE_CANARY')
    (run/'public/input').write_text('PUBLIC_CANARY')
    write_json(run/'private/inputs/policy-access.json', record(run, checkouts=[base/'repo']))
    tool_backend.prepare(run, {'tool_backend': 'landlock-v1'})
    return run


class WorkerRequestTests(unittest.TestCase):
    def test_any_command_the_broker_admits_reaches_the_worker_whole_however_it_is_escaped(self):
        import io
        from robofrontier.engines.codex import tool_worker
        # JSON.stringify escapes these as the broker sends them: newline as two bytes, control as six.
        for command in ('a\n'*60000, '\x01'*131000, 'x'*131000):
            data = json.dumps({'tool': 'policy_exec', 'command': command}).encode()
            self.assertEqual(tool_worker.read_request(io.BytesIO(data))['command'], command)
        with self.assertRaisesRegex(ValueError, 'too large'):
            tool_worker.read_request(io.BytesIO(b' '*(tool_worker.REQUEST_LIMIT+1)))


class ConfigurationTests(unittest.TestCase):
    def test_shared_volume_clones_and_archives_are_denied_without_blocking_own_workspace(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();shared=base/'shared';run=base/'staged/run'
            with patch.dict(os.environ, {'ROBOFRONTIER_SHARED_DENY_ROOTS':json.dumps([str(shared)])}):
                access=record(run,checkouts=[base/'staged'])
            self.assertEqual(mode(access['filesystem'],shared/'another-clone/answers.json'),'deny')
            self.assertEqual(mode(access['filesystem'],shared/'source.tar'),'deny')
            self.assertEqual(mode(access['filesystem'],run/'workspace/note'),'write')
    def test_job_local_python_gets_only_readonly_runtime_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            run = fixture(base, 'runtime')
            prefix = base/'python'
            packages = prefix/'lib/python3.12/site-packages'
            packages.mkdir(parents=True)
            (prefix/'pyvenv.cfg').write_text('home = /usr/bin\n')
            (prefix/'auth.json').write_text('RUNTIME_PRIVATE_CANARY')
            with patch.object(tool_backend.sys, 'prefix', str(prefix)), \
                    patch.object(tool_backend.sysconfig, 'get_path', return_value=str(packages)):
                tool_backend.prepare(run, {'tool_backend': 'landlock-v1'})
            access = json.loads((run/'private/inputs/policy-access.json').read_text())['filesystem']
            self.assertEqual(mode(access, prefix/'pyvenv.cfg'), 'read')
            self.assertEqual(mode(access, packages/'library.py'), 'read')
            self.assertEqual(mode(access, prefix/'auth.json'), 'deny')
            self.assertEqual(mode(access, prefix), 'deny')
            self.assertEqual(mode(access, run/'private/secret'), 'deny')
    def test_receipt_cannot_qualify_a_different_backend_or_changed_source(self):
        profile = {'tool_backend': 'landlock-v1'}
        digest = tool_backend.fingerprint(profile)
        launch = {'profile':profile,'tool_backend_sha256':digest}
        receipt = {'passed':True,'broker_tools_verified':True,'tool_backend':'landlock-v1','tool_backend_sha256':digest}
        tool_backend.verify_receipt(launch, receipt)
        for key, value in [('passed',False),('broker_tools_verified',False),('tool_backend','native'),('tool_backend_sha256','old')]:
            with self.subTest(key=key), self.assertRaises(ValueError):
                tool_backend.verify_receipt(launch, {**receipt,key:value})
        with self.assertRaises(ValueError):
            tool_backend.verify_receipt({**launch,'tool_backend_sha256':'old'},receipt)

    def test_backend_is_explicit_and_old_frozen_configuration_keeps_its_shape(self):
        # The default `auto` is Codex's own sandbox on macOS and the checked Landlock worker on Linux.
        expected = 'landlock-v1' if sys.platform.startswith('linux') else 'native'
        self.assertEqual(load_configuration()['runtime']['codex_tool_backend'], expected)
        self.assertEqual(load_configuration(host='slurm')['runtime']['codex_tool_backend'], 'landlock-v1')
        claude = load_configuration(overrides={'policy': {'engine': 'claude'}}, host='slurm')
        self.assertEqual(claude['runtime']['codex_tool_backend'], 'native')
        config = load_configuration(overrides={'schema_version': 4})
        self.assertNotIn('codex_tool_backend', config['runtime'])
        with self.assertRaises(ValueError):
            load_configuration(overrides={'runtime': {'codex_tool_backend': 'unconfined'}})

    def test_broker_removes_native_handlers_and_pins_subagent_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            out = Path(temporary)
            profile = dict(model='test', provider='openai', effort='high', context_window=300000,
                           auto_compact_token_limit=267000, tool_backend='landlock-v1', use_cached_model_metadata=False)
            launch = launch_config(profile, out)
            self.assertIn('agents.enabled=false', launch['args'])
            self.assertIn('features.shell_tool=false', launch['args'])
            self.assertEqual(launch['provider'], 'robofrontier_openai_http')
            self.assertEqual(launch['profile']['provider'], 'openai')
            self.assertIn('model_providers.robofrontier_openai_http.requires_openai_auth=true', launch['args'])
            self.assertIn('model_providers.robofrontier_openai_http.supports_websockets=false', launch['args'])
            self.assertNotIn('sandbox_mode="danger-full-access"', launch['args'])
            model = json.loads((out/'models.json').read_text())['models'][0]
            self.assertIsNone(model['apply_patch_tool_type'])
            self.assertEqual(model['multi_agent_version'], 'disabled')
            self.assertEqual(launch['tool_backend_sha256'], tool_backend.fingerprint(profile))


@unittest.skipUnless(sys.platform.startswith('linux') and abi() >= 1, 'Linux Landlock required')
class KernelBoundaryTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'Node required')
    def test_native_node_broker_exec_and_image_preserve_isolation(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = fixture(Path(temporary).resolve(), 'node')
            (run/'public/image.png').write_bytes(b'\x89PNG\r\n\x1a\nimage-canary')
            broker = Path(tool_backend.__file__).with_name('tool_broker.js')
            script = r'''
const assert=require('node:assert/strict');
const broker=require(process.argv[1]),run=process.argv[2],python=process.argv[3];
(async()=>{
 const result=await broker.call(run,python,'policy_exec',{command:
  'cat ../public/input && printf note > node-note && ! cat ../private/secret'});
 assert.equal(result.success,true,JSON.stringify(result));
 const output=JSON.parse(result.contentItems[0].text);
 assert.equal(output.exit_code,0);assert.equal(output.stdout,'PUBLIC_CANARY');
 assert.ok(!JSON.stringify(result).includes('PRIVATE_CANARY'));
 const image=await broker.call(run,python,'policy_image',{path:run+'/public/image.png'});
 assert.equal(image.success,true,JSON.stringify(image));
 assert.equal(image.contentItems[0].type,'inputImage');
 const denied=await broker.call(run,python,'policy_image',{path:run+'/private/secret'});
 assert.equal(denied.success,false);assert.ok(!JSON.stringify(denied).includes('PRIVATE_CANARY'));
})().catch(error=>{console.error(error.message);process.exitCode=1;});
'''
            result = subprocess.run(['node', '-e', script, str(broker), str(run), sys.executable],
                                    capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((run/'workspace/node-note').read_text(), 'note')

    def test_regular_standard_output_is_rejected_before_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = fixture(Path(temporary).resolve(), 'regular-output')
            with (run/'private/secret').open('a') as output:
                result = subprocess.run([sys.executable, '-I', '-m', 'robofrontier.engines.codex.tool_worker',
                    '--run-dir', str(run)], input=json.dumps({'tool':'policy_exec','command':'printf BAD'}),
                    stdout=output, stderr=subprocess.PIPE, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual((run/'private/secret').read_text(), 'PRIVATE_CANARY')

    def test_local_doctor_exercises_the_actual_worker(self):
        report = tool_backend.doctor()
        self.assertTrue(all(report['checks'].values()))

    def test_concurrent_roles_can_write_own_notes_but_not_read_other_runs(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            runs = [fixture(base, str(n)) for n in range(2)]
            def role(n):
                run, other = runs[n%2], runs[(n+1)%2]
                command = ('cat ../public/input && printf note > '+shlex.quote('note-'+str(n))+
                           ' && ! cat '+shlex.quote(str(other/'private/secret'))+
                           ' && ! cat ../private/secret')
                return tool_backend.execute(run, {'tool': 'policy_exec', 'command': command})
            with ThreadPoolExecutor(max_workers=8) as pool:
                results = list(pool.map(role, range(8)))
            for result in results:
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertNotIn('PRIVATE_CANARY', result.stdout)
            self.assertEqual(sum(len(list((r/'workspace').glob('note-*'))) for r in runs), 8)

    def test_images_are_opened_under_landlock_including_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = fixture(Path(temporary).resolve(), 'one')
            image = b'\x89PNG\r\n\x1a\nimage-canary'
            (run/'public/image.png').write_bytes(image)
            (run/'workspace/escape').symlink_to(run/'private/secret')
            result = tool_backend.execute(run, {'tool': 'policy_image', 'path': str(run/'public/image.png')})
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(base64.b64decode(json.loads(result.stdout)['data']), image)
            for path in ('../private/secret', 'escape'):
                denied = tool_backend.execute(run, {'tool': 'policy_image', 'path': path})
                self.assertNotEqual(denied.returncode, 0)
                self.assertNotIn('PRIVATE_CANARY', denied.stdout+denied.stderr)

    def test_inherited_descriptors_env_and_additional_kernel_ipc_are_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = fixture(Path(temporary).resolve(), 'one')
            with (run/'private/secret').open() as secret:
                script = '''import ctypes,errno,os
fd=FD_VALUE
try:os.fstat(fd)
except OSError as e:assert e.errno==errno.EBADF
else:raise RuntimeError('Inherited private descriptor')
assert 'WORKER_FAKE_SECRET' not in os.environ
lib=ctypes.CDLL('libseccomp.so.2');lib.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p]
libc=ctypes.CDLL(None,use_errno=True)
for name in ('io_uring_setup','pidfd_send_signal','rt_sigqueueinfo','process_vm_readv','setpgid'):
 n=lib.seccomp_syscall_resolve_name(name.encode())
 if n>=0:
  assert libc.syscall(n,-1,0,0,0,0,0)==-1 and ctypes.get_errno()==errno.EPERM,name
print('IPC_AND_FD_OK')
'''.replace('FD_VALUE', str(secret.fileno()))
                (run/'public/check.py').write_text(script)
                command = shlex.join([sys.executable, str(run/'public/check.py')])
                result = subprocess.run([sys.executable, '-I', '-m', 'robofrontier.engines.codex.tool_worker',
                    '--run-dir', str(run)], input=json.dumps({'tool':'policy_exec','command':command}),
                    env={**os.environ, 'WORKER_FAKE_SECRET':'FAKE_CANARY'}, pass_fds=(secret.fileno(),),
                    text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(result.stdout.strip(), 'IPC_AND_FD_OK')

    def test_invalid_rules_fail_before_model_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = fixture(Path(temporary).resolve(), 'one')
            write_json(run/'private/inputs/codex-tools.json', {'schema':'unknown','backend':'landlock-v1'})
            result = tool_backend.execute(run, {'tool':'policy_exec','command':'printf SHOULD_NOT_RUN'})
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('SHOULD_NOT_RUN', result.stdout)


if __name__ == '__main__':
    unittest.main()
