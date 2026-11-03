"""Real worker syscalls with ABI 1/2 filesystem masks, without models or robots.

A newer Linux kernel can exercise the old ruleset masks by limiting only the
trusted test child's ABI query. Production has no environment/config ABI override.
This does not replace admission on the actual cluster kernel.
"""
import base64
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.claude.landlock_shell import abi
from robofrontier.codex import tool_worker


def fixture(base):
    run = base/'run'
    for name in ('private/inputs', 'public', 'workspace/.tmp'):
        (run/name).mkdir(parents=True)
    (base/'other-task-secret').write_text('OTHER_TASK_SECRET')
    (base/'auth.json').write_text('FAKE_CREDENTIAL_CANARY')
    (run/'private/answer').write_text('PRIVATE_ANSWER')
    (run/'public/input').write_text('PUBLIC_READ_ONLY_CANARY')
    (run/'public/input').chmod(0o644)
    access = {'network': False, 'filesystem': {'/': 'read', str(base): 'deny',
              str(run/'public'): 'read', str(run/'workspace'): 'write',
              '/proc': 'deny', '/dev': 'deny', '/tmp': 'deny'}}
    (run/'private/inputs/policy-access.json').write_text(json.dumps(access))
    (run/'private/inputs/codex-tools.json').write_text(json.dumps(
        {'schema': tool_worker.SCHEMA, 'backend': 'landlock-v1'}))
    return run


def worker(run, request, version, *, output=None):
    code = ('import sys;sys.path.insert(0,'+repr(str(Path(tool_worker.__file__).resolve().parents[2]))+');'
            'from robofrontier.claude import landlock_shell as ll;'
            'assert ll.abi()>='+str(version)+';ll.abi=lambda:'+str(version)+';'
            'from robofrontier.codex.tool_worker import main;main()')
    return subprocess.run([sys.executable, '-I', '-c', code, '--run-dir', str(run)],
                          input=json.dumps(request), text=True,
                          **({'capture_output': True} if output is None else {'stdout': output, 'stderr': subprocess.PIPE}),
                          env={'PATH': os.environ.get('PATH', '/usr/bin:/bin')}, timeout=20)


class FailClosedTests(unittest.TestCase):
    def test_no_libseccomp_never_enables_a_filesystem_only_fallback(self):
        with patch.object(tool_worker.ctypes.util, 'find_library', return_value=None):
            with self.assertRaisesRegex(RuntimeError, 'libseccomp'):
                tool_worker.seccomp_filter()


@unittest.skipUnless(sys.platform.startswith('linux') and abi() >= 1, 'Linux Landlock required')
class LegacyKernelBoundaryTests(unittest.TestCase):
    def test_abi1_and_abi2_preserve_boundaries_and_workspace_operations(self):
        for version in (1, 2):
            with self.subTest(abi=version), tempfile.TemporaryDirectory() as temporary:
                base = Path(temporary).resolve()
                run = fixture(base)
                probe = r'''import ctypes,errno,json,os,socket
from pathlib import Path
r=Path.cwd().parent
p=r/'public/input'
checks={}
def denied(name,fn):
 try:fn()
 except PermissionError:checks[name]=True;return
 checks[name]=False
checks['public_read']=p.read_text()=='PUBLIC_READ_ONLY_CANARY'
Path('note').write_text('first');Path('note').write_text('updated')
with Path('note').open('a') as f:f.write('-append')
Path('replacement').write_text('replace');os.replace('replacement','note')
checks['workspace_write']=Path('note').read_text()=='replace'
with Path('note').open('r+') as f:f.truncate(3)
checks['workspace_ftruncate']=Path('note').read_text()=='rep'
for name,path in [('private',r/'private/answer'),('other_task',r.parent/'other-task-secret'),
                  ('credentials',r.parent/'auth.json'),('proc',Path('/proc/self/environ'))]:
 denied(name,lambda path=path:path.read_bytes())
denied('public_write',lambda:p.write_text('BAD'))
denied('truncate_path',lambda:os.truncate(p,0))
denied('readonly_o_trunc',lambda:os.open(p,os.O_RDONLY|os.O_TRUNC))
denied('readonly_o_trunc_cloexec',lambda:os.open(p,os.O_RDONLY|os.O_TRUNC|os.O_CLOEXEC))
denied('invalid_access_o_trunc',lambda:os.open(p,os.O_ACCMODE|os.O_TRUNC))
denied('chmod',lambda:os.chmod(p,0o777))
denied('utime',lambda:os.utime(p,(1,1)))
for name,family,kind in [('unix',socket.AF_UNIX,socket.SOCK_STREAM),('tcp',socket.AF_INET,socket.SOCK_STREAM),
                         ('udp',socket.AF_INET,socket.SOCK_DGRAM)]:
 denied(name,lambda family=family,kind=kind:socket.socket(family,kind))
class How(ctypes.Structure):
 _fields_=[('flags',ctypes.c_uint64),('mode',ctypes.c_uint64),('resolve',ctypes.c_uint64)]
libc=ctypes.CDLL(None,use_errno=True)
how=How(os.O_RDONLY|os.O_TRUNC,0,0)
result=libc.syscall(437,-100,str(p).encode(),ctypes.byref(how),ctypes.sizeof(how))
checks['openat2_falls_back']=result==-1 and ctypes.get_errno()==errno.ENOSYS
checks['public_intact']=p.read_text()=='PUBLIC_READ_ONLY_CANARY'
print(json.dumps(checks))
assert all(checks.values()),checks
'''
                (run/'public/probe.py').write_text(probe)
                command = shlex.join([str(Path(sys.executable).resolve()), str(run/'public/probe.py')])
                result = worker(run, {'tool': 'policy_exec', 'command': command}, version)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertTrue(all(json.loads(result.stdout).values()))
                self.assertEqual((run/'public/input').read_text(), 'PUBLIC_READ_ONLY_CANARY')
                self.assertEqual((run/'public/input').stat().st_mode & 0o777, 0o644)
                self.assertEqual((base/'auth.json').read_text(), 'FAKE_CREDENTIAL_CANARY')

    def test_legacy_image_reads_reject_private_and_symlink_targets(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = fixture(Path(temporary).resolve())
            image = b'\x89PNG\r\n\x1a\nfixture-image'
            (run/'public/image.png').write_bytes(image)
            (run/'workspace/escape').symlink_to(run/'private/answer')
            good = worker(run, {'tool': 'policy_image', 'path': str(run/'public/image.png')}, 1)
            self.assertEqual(good.returncode, 0, good.stderr)
            self.assertEqual(base64.b64decode(json.loads(good.stdout)['data']), image)
            for target in ('escape', '../private/answer'):
                bad = worker(run, {'tool': 'policy_image', 'path': target}, 1)
                self.assertNotEqual(bad.returncode, 0)
                self.assertNotIn('PRIVATE_ANSWER', bad.stdout)

    def test_absent_landlock_still_refuses_before_any_command(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = fixture(Path(temporary).resolve())
            result = worker(run, {'tool': 'policy_exec', 'command': 'echo BAD > touched'}, 0)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((run/'workspace/touched').exists())

    def test_regular_stdout_cannot_bypass_filesystem_open_checks(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary).resolve()
            run = fixture(base)
            protected = base/'host-log'
            protected.write_text('HOST_LOG_CANARY')
            with protected.open('ab') as output:
                result = worker(run, {'tool': 'policy_exec', 'command': 'echo BAD'}, 1, output=output)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('pipe-backed', result.stderr)
            self.assertEqual(protected.read_text(), 'HOST_LOG_CANARY')
