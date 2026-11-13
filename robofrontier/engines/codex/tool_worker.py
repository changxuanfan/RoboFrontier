"""One model-controlled file operation, confined before interpreting its arguments.

The trusted host passes the run; the model cannot select a permission table. Codex
authentication, robot connections and IPC remain in the host, never this worker.
"""
import base64
import ctypes
import ctypes.util
import errno
import json
import os
from pathlib import Path
import resource
import socket
import stat
import sys

from robofrontier.engines.common.landlock import allowlist, seccomp_filter
from robofrontier.engines.codex.file_sandbox import abi, restrict

SCHEMA = 'robofrontier.codex-tools.v1'
# The broker admits a command or path of up to 131000 UTF-8 bytes and sends it as
# JSON.stringify({tool, command}); an escaped control character takes six bytes.
INPUT_LIMIT = 131000
REQUEST_LIMIT = 6*INPUT_LIMIT + 1024


MS_NOSUID, MS_NODEV, MS_REC, MS_PRIVATE = 2, 4, 1 << 14, 1 << 18


def private_shared_memory():
    """Give this command an empty /dev/shm of its own, for Python's multiprocessing locks.

    Other jobs on the node keep data in the real one, and Landlock could only open all of it.
    Runs before Landlock and seccomp, which forbid these calls, and fails rather than fall
    back to the shared folder.
    """
    apparmor = Path('/proc/sys/kernel/apparmor_restrict_unprivileged_userns')
    if apparmor.exists() and apparmor.read_text().strip() == '1':
        raise PermissionError(errno.EPERM, 'AppArmor restricts unprivileged user namespaces')
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
    frozen = access.get('policy_env')
    # The table opens /dev/shm only for a private one (tool_backend.prepare). Where the host forbids
    # the user namespace it needs (a RunPod container), the shared one stays closed: Python's
    # multiprocessing locks then do not work, as under the Claude Landlock shell.
    if frozen:
        try: private_shared_memory()
        # EPERM where namespaces are forbidden; ENOSPC where user.max_user_namespaces is 0; EINVAL in some containers.
        except OSError as error:
            if error.errno not in (errno.EPERM, errno.ENOSPC, errno.EINVAL): raise
            access['filesystem']['/dev/shm'] = 'deny'
    rules = allowlist(access['filesystem'], read=['/dev/urandom'], write=['/dev/null'])
    temporary = run/'workspace/.tmp'
    if not temporary.is_dir():
        raise ValueError('Missing private tool temporary directory')
    # No inherited host descriptors, credentials, Python import controls or shell RC.
    os.closerange(3, resource.getrlimit(resource.RLIMIT_NOFILE)[0])
    os.environ.clear()
    os.environ.update(frozen['variables'] if frozen else dict(
        PATH=str(Path(sys.executable).parent)+':/usr/local/bin:/usr/bin:/bin', LANG='C.UTF-8', TMPDIR=str(temporary)))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
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
