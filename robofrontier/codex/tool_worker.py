"""One model-controlled file operation, confined before interpreting its arguments.

The trusted host passes the run; the model cannot select a permission table. Codex
authentication, robot connections and IPC remain in the host, never this worker.
"""
import base64
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import resource
import sys

from robofrontier.claude.landlock_shell import allowlist, restrict

SCHEMA = 'robofrontier.codex-tools.v1'
DENIED_SYSCALLS = (
    'socket', 'socketpair', 'socketcall', 'connect', 'bind', 'listen', 'accept', 'accept4',
    'sendmsg', 'recvmsg', 'sendto', 'recvfrom', 'sendmmsg', 'recvmmsg',
    'io_uring_setup', 'io_uring_enter', 'io_uring_register',
    'ptrace', 'process_vm_readv', 'process_vm_writev', 'pidfd_getfd', 'pidfd_send_signal',
    'kill', 'tkill', 'tgkill', 'rt_sigqueueinfo', 'rt_tgsigqueueinfo',
    'mount', 'umount2', 'pivot_root', 'setns', 'unshare', 'setsid', 'setpgid', 'open_by_handle_at',
    'bpf', 'perf_event_open',
)


def seccomp_filter():
    name = ctypes.util.find_library('seccomp')
    if not name:
        raise RuntimeError('libseccomp is required for the Codex Landlock backend')
    library = ctypes.CDLL(name, use_errno=True)
    library.seccomp_init.argtypes = [ctypes.c_uint32]
    library.seccomp_init.restype = ctypes.c_void_p
    library.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
    library.seccomp_syscall_resolve_name.restype = ctypes.c_int
    library.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
    library.seccomp_rule_add.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError('seccomp_init failed')
    try:
        for name in DENIED_SYSCALLS:
            number = library.seccomp_syscall_resolve_name(name.encode())
            if number >= 0 and library.seccomp_rule_add(context, 0x00050001, number, 0):
                raise RuntimeError('Cannot enforce syscall restriction: ' + name)
        if library.seccomp_load(context):
            raise RuntimeError('Cannot install seccomp restrictions')
    finally:
        library.seccomp_release(context)


def drop_capabilities():
    class Header(ctypes.Structure):
        _fields_ = [('version', ctypes.c_uint32), ('pid', ctypes.c_int)]
    class Data(ctypes.Structure):
        _fields_ = [('effective', ctypes.c_uint32), ('permitted', ctypes.c_uint32),
                    ('inheritable', ctypes.c_uint32)]
    libc = ctypes.CDLL(None, use_errno=True)
    header, data = Header(0x20080522, 0), (Data * 2)()
    if libc.capset(ctypes.byref(header), ctypes.byref(data)):
        raise RuntimeError('Cannot drop worker capabilities')


def main():
    if len(sys.argv) != 3 or sys.argv[1] != '--run-dir' or not sys.platform.startswith('linux'):
        raise ValueError('The Landlock tool worker requires a bound Linux run')
    run = Path(sys.argv[2]).resolve()
    backend = json.loads((run/'private/inputs/codex-tools.json').read_text())
    access = json.loads((run/'private/inputs/policy-access.json').read_text())
    if backend != {'schema': SCHEMA, 'backend': 'landlock-v1'} or access.get('network') is not False:
        raise ValueError('Unsupported or network-enabled tool configuration')
    rules = allowlist(access['filesystem'], write=['/dev/null'])
    temporary = run/'workspace/.tmp'
    if not temporary.is_dir():
        raise ValueError('Missing private tool temporary directory')
    # No inherited host descriptors, credentials, Python import controls or shell RC.
    os.closerange(3, resource.getrlimit(resource.RLIMIT_NOFILE)[0])
    os.environ.clear()
    os.environ.update(PATH=str(Path(sys.executable).parent)+':/usr/local/bin:/usr/bin:/bin',
                      LANG='C.UTF-8', TMPDIR=str(temporary))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    seccomp_filter()
    restrict(rules)
    drop_capabilities()
    os.chdir(run/'workspace')
    request = json.loads(sys.stdin.buffer.read(131073))
    if not isinstance(request, dict):
        raise ValueError('Invalid tool request')
    if request.get('tool') == 'policy_exec' and set(request) == {'tool', 'command'}:
        command = request['command']
        if not isinstance(command, str) or not 0 < len(command.encode()) <= 131000:
            raise ValueError('Invalid shell command')
        os.execve('/bin/bash', ['/bin/bash', '--noprofile', '--norc', '-c', command], dict(os.environ))
    elif request.get('tool') == 'policy_image' and set(request) == {'tool', 'path'}:
        if not isinstance(request['path'], str):
            raise ValueError('Invalid image path')
        with open(request['path'], 'rb') as image:
            data = image.read(8*1024*1024+1)
        if len(data) > 8*1024*1024:
            raise ValueError('Image exceeds 8 MiB')
        mime = 'image/png' if data.startswith(b'\x89PNG\r\n\x1a\n') else 'image/jpeg' if data.startswith(b'\xff\xd8\xff') else None
        if mime is None:
            raise ValueError('Expected a PNG or JPEG image')
        print(json.dumps({'mime': mime, 'data': base64.b64encode(data).decode()}))
    else:
        raise ValueError('Unsupported tool request')


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        # Do not return tracebacks, permission-table contents or host command lines.
        print(type(error).__name__+': '+str(error), file=sys.stderr)
        raise SystemExit(126)
