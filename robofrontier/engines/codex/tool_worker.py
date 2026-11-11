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
import socket
import stat
import sys

from robofrontier.engines.common.landlock import allowlist
from robofrontier.engines.codex.file_sandbox import abi, restrict

SCHEMA = 'robofrontier.codex-tools.v1'
# The broker admits a command or path of up to 131000 UTF-8 bytes and sends it as
# JSON.stringify({tool, command}); an escaped control character takes six bytes.
INPUT_LIMIT = 131000
REQUEST_LIMIT = 6*INPUT_LIMIT + 1024
DENIED_SYSCALLS = (
    'socket', 'socketpair', 'socketcall', 'connect', 'bind', 'listen', 'accept', 'accept4',
    'sendmsg', 'recvmsg', 'sendto', 'recvfrom', 'sendmmsg', 'recvmmsg',
    'io_uring_setup', 'io_uring_enter', 'io_uring_register',
    'ptrace', 'process_vm_readv', 'process_vm_writev', 'pidfd_getfd', 'pidfd_send_signal',
    'kill', 'tkill', 'tgkill', 'rt_sigqueueinfo', 'rt_tgsigqueueinfo',
    'mount', 'umount2', 'pivot_root', 'setns', 'unshare', 'setsid', 'setpgid', 'open_by_handle_at',
    'bpf', 'perf_event_open',
    # Landlock does not mediate these metadata changes, including on newer ABIs.
    'chmod', 'fchmod', 'fchmodat', 'fchmodat2', 'chown', 'fchown', 'lchown', 'fchownat',
    'chown32', 'fchown32', 'lchown32', 'setxattr', 'lsetxattr', 'fsetxattr',
    'removexattr', 'lremovexattr', 'fremovexattr', 'utime', 'utimes', 'futimesat',
    'utimensat', 'utimensat_time64',
)


MS_NOSUID, MS_NODEV, MS_REC, MS_PRIVATE = 2, 4, 1 << 14, 1 << 18


def private_shared_memory():
    """Give this command an empty /dev/shm of its own, for Python's multiprocessing locks.

    Other jobs on the node keep data in the real one, and Landlock could only open all of it.
    Runs before Landlock and seccomp, which forbid these calls, and fails rather than fall
    back to the shared folder.
    """
    uid, gid = os.getuid(), os.getgid()
    os.unshare(os.CLONE_NEWUSER | os.CLONE_NEWNS)
    Path('/proc/self/setgroups').write_text('deny')
    Path('/proc/self/uid_map').write_text('%d %d 1' % (uid, uid))
    Path('/proc/self/gid_map').write_text('%d %d 1' % (gid, gid))
    libc = ctypes.CDLL(None, use_errno=True)
    for source, target, kind, flags in ((b'none', b'/', None, MS_REC | MS_PRIVATE),
                                        (b'tmpfs', b'/dev/shm', b'tmpfs', MS_NOSUID | MS_NODEV)):
        if libc.mount(source, target, kind, flags, None):
            raise OSError(ctypes.get_errno(), 'Cannot prepare a private /dev/shm')


# A run with a policy environment needs pip and venv, which set file modes. These calls succeed
# without changing anything, since Landlock cannot limit which of the account's files they reach.
MODE_SYSCALLS = ('chmod', 'fchmod', 'fchmodat', 'fchmodat2')
PRETEND_SUCCESS, DENY = 0x00050000, 0x00050001  # SCMP_ACT_ERRNO(0), SCMP_ACT_ERRNO(EPERM)


def seccomp_filter(filesystem_abi=None, ignore_mode_changes=False):
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
    class ArgCompare(ctypes.Structure):
        _fields_ = [('arg', ctypes.c_uint), ('op', ctypes.c_uint),
                    ('datum_a', ctypes.c_uint64), ('datum_b', ctypes.c_uint64)]
    library.seccomp_rule_add_array.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int,
                                              ctypes.c_uint, ctypes.POINTER(ArgCompare)]
    library.seccomp_rule_add_array.restype = ctypes.c_int
    library.seccomp_load.argtypes = [ctypes.c_void_p]
    library.seccomp_load.restype = ctypes.c_int
    library.seccomp_release.argtypes = [ctypes.c_void_p]
    context = library.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
    if not context:
        raise RuntimeError('seccomp_init failed')
    try:
        for name in DENIED_SYSCALLS:
            number = library.seccomp_syscall_resolve_name(name.encode())
            if name == 'fchmodat2' and number < 0:
                number = 452  # x86_64/aarch64: old libseccomp, newer kernel.
            action = PRETEND_SUCCESS if ignore_mode_changes and name in MODE_SYSCALLS else DENY
            if number >= 0 and library.seccomp_rule_add(context, action, number, 0):
                raise RuntimeError('Cannot enforce syscall restriction: ' + name)
        version = abi() if filesystem_abi is None else filesystem_abi
        if version < 3:
            for name in ('truncate', 'truncate64'):
                number = library.seccomp_syscall_resolve_name(name.encode())
                if number >= 0 and library.seccomp_rule_add(context, 0x00050001, number, 0):
                    raise RuntimeError('Cannot enforce legacy truncate restriction')
            # openat2 keeps its flags in a pointer, which classic seccomp cannot
            # inspect. ENOSYS allows safe libc/tool fallbacks to filtered openat.
            number = library.seccomp_syscall_resolve_name(b'openat2')
            if number < 0:
                number = 437
            if library.seccomp_rule_add(context, 0x00050026, number, 0):
                raise RuntimeError('Cannot enforce legacy openat2 restriction')
            for name, argument in (('open', 1), ('openat', 2)):
                number = library.seccomp_syscall_resolve_name(name.encode())
                if number < 0:
                    if name == 'openat':
                        raise RuntimeError('Cannot resolve legacy openat restriction')
                    continue
                # Normal O_WRONLY/O_RDWR writes remain governed by Landlock.
                # Deny truncation through read-only and invalid access modes.
                for access in (os.O_RDONLY, os.O_ACCMODE):
                    compare = ArgCompare(argument, 7, os.O_TRUNC | os.O_ACCMODE, os.O_TRUNC | access)
                    if library.seccomp_rule_add_array(context, 0x00050001, number, 1, ctypes.byref(compare)):
                        raise RuntimeError('Cannot enforce legacy open flags restriction')
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


def standard_stream(fd):
    kind = os.fstat(fd).st_mode
    if stat.S_ISFIFO(kind):
        return True
    if not stat.S_ISSOCK(kind):
        return False
    # libuv implements Node's stdio='pipe' using anonymous socketpairs on
    # Linux. Accept only those connected Unix streams, never a named IPC
    # endpoint, network socket, listening socket or inherited regular file.
    try:
        with socket.socket(fileno=os.dup(fd)) as stream:
            return (stream.family == socket.AF_UNIX
                    and stream.getsockopt(socket.SOL_SOCKET, socket.SO_TYPE) == socket.SOCK_STREAM
                    and not stream.getsockopt(socket.SOL_SOCKET, socket.SO_ACCEPTCONN)
                    and stream.getsockname() in ('', b'')
                    and stream.getpeername() in ('', b''))
    except OSError:
        return False


def read_request(stream):
    """The whole JSON request: any input the broker admits fits, however it was escaped."""
    data = stream.read(REQUEST_LIMIT + 1)
    if len(data) > REQUEST_LIMIT:
        raise ValueError('Tool request too large')
    request = json.loads(data)
    if not isinstance(request, dict):
        raise ValueError('Invalid tool request')
    return request


def main():
    if len(sys.argv) != 3 or sys.argv[1] != '--run-dir' or not sys.platform.startswith('linux'):
        raise ValueError('The Landlock tool worker requires a bound Linux run')
    run = Path(sys.argv[2]).resolve()
    backend = json.loads((run/'private/inputs/codex-tools.json').read_text())
    access = json.loads((run/'private/inputs/policy-access.json').read_text())
    if backend != {'schema': SCHEMA, 'backend': 'landlock-v1'} or access.get('network') is not False:
        raise ValueError('Unsupported or network-enabled tool configuration')
    if os.uname().machine not in ('x86_64', 'aarch64'):
        raise ValueError('Unsupported worker syscall architecture')
    # An inherited regular stdout/stderr could bypass filesystem-open checks.
    if any(not standard_stream(fd) for fd in (0, 1, 2)):
        raise ValueError('Isolated tools require pipe-backed or anonymous Unix stream standard descriptors')
    # Some Python builds fall back from getrandom() to this read-only entropy
    # source. No other device becomes readable through the /dev deny table.
    rules = allowlist(access['filesystem'], read=['/dev/urandom'], write=['/dev/null'])
    temporary = run/'workspace/.tmp'
    if not temporary.is_dir():
        raise ValueError('Missing private tool temporary directory')
    # No inherited host descriptors, credentials, Python import controls or shell RC.
    os.closerange(3, resource.getrlimit(resource.RLIMIT_NOFILE)[0])
    os.environ.clear()
    frozen = access.get('policy_env')
    os.environ.update(frozen['variables'] if frozen else dict(
        PATH=str(Path(sys.executable).parent)+':/usr/local/bin:/usr/bin:/bin', LANG='C.UTF-8', TMPDIR=str(temporary)))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    if frozen:
        # Where the host forbids user namespaces (a RunPod container), there is no private
        # /dev/shm: Landlock keeps the shared one closed, so multiprocessing locks do not work,
        # as under the Claude Landlock shell; nothing shared opens.
        try: private_shared_memory()
        except PermissionError: pass
    seccomp_filter(abi(), ignore_mode_changes=bool(frozen))
    restrict(rules)
    drop_capabilities()
    os.chdir(run/'workspace')
    request = read_request(sys.stdin.buffer)
    if request.get('tool') == 'policy_exec' and set(request) == {'tool', 'command'}:
        command = request['command']
        if not isinstance(command, str) or not 0 < len(command.encode()) <= INPUT_LIMIT:
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
