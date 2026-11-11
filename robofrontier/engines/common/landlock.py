"""Run one policy Bash command under Landlock, where Claude Code's own sandbox cannot run.

Claude Code confines Bash with bubblewrap on Linux, which needs to create namespaces.
Containers under Docker's default seccomp profile (such as RunPod pods) refuse that,
so every sandboxed command fails. Landlock needs no namespace: a process restricts
itself and everything it starts. Claude Code passes each Bash command to
CLAUDE_CODE_SHELL_PREFIX as one string; this script, run as that prefix, restricts
itself to the run's frozen access table and then runs the string with bash.

As with Claude Code's sandbox only Bash is confined, not the CLI or the robot MCP
(which Claude Code also starts through the prefix; see write_rules).
The rules allow reading and writing exactly what the table grants (Landlock grants by
listed path, so a denied folder inside a readable one is listed around), deny every
TCP connection and bind, and no named Unix socket is made anywhere; seccomp closes what
Landlock does not cover (every socket, signals and tracing of other processes, namespaces,
owner changes, and mode changes, which succeed without effect), as for Codex. It fails closed: without
Landlock network rules (ABI 4, Linux 6.7) or libseccomp the command does not run.

Standard library only (with the system's libseccomp), so the prefix runs it with `python -I`
before any import.
"""
import ctypes
import ctypes.util
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import tempfile

SCHEMA = 'robofrontier.landlock-rules.v1'
CREATE_RULESET, ADD_RULE, RESTRICT_SELF = 444, 445, 446  # Same number on x86_64 and arm64.
PATH_BENEATH, NET_PORT = 1, 2
PR_SET_NO_NEW_PRIVS = 38
EXECUTE, WRITE_FILE, READ_FILE, READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
MAKE_REG, MAKE_SOCK = 1 << 8, 1 << 9
REFER, TRUNCATE, IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15
FILE_ONLY = EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE | IOCTL_DEV
READ = EXECUTE | READ_FILE | READ_DIR
ACCESS = {'list': READ_DIR, 'read': READ}  # 'write' is everything handled (access_for).
BIND_TCP, CONNECT_TCP = 1 << 0, 1 << 1
SCOPE_ABSTRACT_UNIX, SCOPE_SIGNAL = 1 << 0, 1 << 1
NETWORK_ABI = 4
# Devices a shell writes to as a matter of course.
DEVICES = ('/dev/null', '/dev/tty')


def access_for(mode, fs):
    """The Landlock rights for a rule: 'write' is everything handled but making a named Unix
    socket, which in a shared folder such as /tmp would reach other runs' processes."""
    if mode == 'write':
        return fs & ~MAKE_SOCK
    if mode not in ACCESS:
        raise ValueError('Unknown filesystem permission: %r' % (mode,))
    return ACCESS[mode]


# What Landlock does not mediate, closed with seccomp for both engines' Linux Landlock shells:
# sockets (an existing named Unix socket, UDP, abstract sockets), signals and tracing of other
# processes, namespaces and mounts, and metadata changes.
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


# A run with a policy environment needs pip and venv, which set file modes. These calls succeed
# without changing anything, since Landlock cannot limit which of the account's files they reach.
MODE_SYSCALLS = ('chmod', 'fchmod', 'fchmodat', 'fchmodat2')
PRETEND_SUCCESS, DENY = 0x00050000, 0x00050001  # SCMP_ACT_ERRNO(0), SCMP_ACT_ERRNO(EPERM)


def seccomp_filter(filesystem_abi=None, ignore_mode_changes=False):
    name = ctypes.util.find_library('seccomp')
    if not name:
        raise RuntimeError('libseccomp is required for Landlock isolation')
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


def abi():
    """The kernel's Landlock ABI version, or 0 when it is unavailable."""
    if not sys.platform.startswith('linux'):
        return 0
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    version = libc.syscall(CREATE_RULESET, None, ctypes.c_size_t(0), ctypes.c_uint32(1))
    return max(int(version), 0)


def choose():
    """The Bash isolation this host supports, frozen when a Claude run is prepared.

    'claude-sandbox' is Claude Code's own (Seatbelt on macOS, bubblewrap on Linux);
    'landlock-v1' is this script, for a Linux host that cannot create namespaces."""
    if sys.platform == 'darwin':
        return 'claude-sandbox'
    if shutil.which('bwrap') and shutil.which('socat'):
        probe = subprocess.run(['bwrap', '--ro-bind', '/', '/', '--dev', '/dev', '--proc', '/proc',
                                '--unshare-net', 'true'], capture_output=True, timeout=30)
        if probe.returncode == 0:
            return 'claude-sandbox'
    if abi() >= NETWORK_ABI and ctypes.util.find_library('seccomp'):
        return 'landlock-v1'
    raise ValueError('No Bash isolation on this host: bubblewrap cannot create namespaces, and '
                     'Landlock with network rules (ABI 4) or libseccomp is unavailable')


def handled_fs(version):
    mask = (1 << 13) - 1
    if version >= 2: mask |= REFER
    if version >= 3: mask |= TRUNCATE
    if version >= 5: mask |= IOCTL_DEV
    return mask


def allowlist(table, read=(), write=()):
    """[(path, 'read'|'write')] granting what `table` grants, its most specific path winning.

    A path whose table entries below it all agree with it becomes one rule. One with a
    different entry below is replaced by its children, read now, except the child on the
    way to that entry, which is visited the same way; later children are not covered.
    A symbolic link among those children gets no rule: a rule attaches to the link's
    target, which may be a denied folder (a link beside the repository, or one a policy
    shell planted in /tmp). Its target keeps whatever its own place in the table grants.
    A readable folder whose differing entries are only files directly in it, such as
    /usr/bin with the system Python closed, also gets a 'list' rule so it can still be
    listed; a folder with a differing folder below does not, since listing reaches below.
    `read` and `write` add paths after the table, such as Claude Code's shell snapshots.
    """
    entries = {Path(p): mode for p, mode in table.items()}
    rules = []
    def visit(path, mode):
        below = [p for p, m in entries.items() if path in p.parents and m != mode]
        if not below:
            if mode != 'deny': rules.append((str(path), mode))
            return
        try:
            children = sorted(path.iterdir())
        except OSError:
            return
        if mode != 'deny' and all(p.parent == path and not p.is_dir() for p in below):
            rules.append((str(path), 'list'))
        for child in children:
            if child in entries or child.is_symlink():
                continue
            if any(child == p or child in p.parents for p in below):
                visit(child, mode)
            elif mode != 'deny':
                rules.append((str(child), mode))
    for path, mode in entries.items():
        visit(path, mode)
    return rules + [(str(p), 'read') for p in read] + [(str(p), 'write') for p in write]


def write_atomic(path, text, mode=0o600):
    """Publish a complete file using a unique temporary file in the same directory."""
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            os.fchmod(output.fileno(), mode)
            output.write(text)
        os.replace(temporary, path)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass


def write_rules(path, rules, unconfined=()):
    """Write the rules atomically: roles of one run start turns, and rewrite them, concurrently.

    Claude Code also starts each stdio MCP server through the shell prefix, as one
    shell-quoted string. `unconfined` lists those exact strings for the run's own robot
    MCP servers, which run unconfined like every other harness process. A Bash command
    never matches one: Claude Code wraps it in its shell snapshot and an eval."""
    write_atomic(path, json.dumps({'schema': SCHEMA, 'rules': rules, 'unconfined': sorted(unconfined)},
                                  indent=1) + '\n')


def restrict(rules):
    """Restrict this process and its future children to `rules`; raises OSError if it cannot."""
    version = abi()
    if version < NETWORK_ABI:
        raise OSError('Landlock ABI %d lacks network rules; refusing to run unconfined' % version)
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    fs = handled_fs(version)
    scoped = SCOPE_ABSTRACT_UNIX | SCOPE_SIGNAL if version >= 6 else 0
    attr = (ctypes.c_uint64 * 3)(fs, BIND_TCP | CONNECT_TCP, scoped)
    size = 24 if version >= 6 else 16
    ruleset = libc.syscall(CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(size), ctypes.c_uint32(0))
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), 'landlock_create_ruleset failed')
    class PathBeneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]
    try:
        for path, mode in rules:
            try:
                fd = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
            except OSError:
                continue  # Not there now: nothing to grant.
            try:
                kind = os.fstat(fd).st_mode
                if stat.S_ISLNK(kind):
                    continue  # Never grant a link's target under the link's name (see allowlist).
                access = access_for(mode, fs)
                if not stat.S_ISDIR(kind):
                    access &= FILE_ONLY
                rule = PathBeneath(access & fs, fd)
                if libc.syscall(ADD_RULE, ctypes.c_int(ruleset), ctypes.c_int(PATH_BENEATH),
                                ctypes.byref(rule), ctypes.c_uint32(0)) < 0:
                    raise OSError(ctypes.get_errno(), 'landlock_add_rule failed for ' + path)
            finally:
                os.close(fd)
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
            raise OSError(ctypes.get_errno(), 'PR_SET_NO_NEW_PRIVS failed')
        if libc.syscall(RESTRICT_SELF, ctypes.c_int(ruleset), ctypes.c_uint32(0)) < 0:
            raise OSError(ctypes.get_errno(), 'landlock_restrict_self failed')
    finally:
        os.close(ruleset)


def main(argv):
    if len(argv) != 3:
        sys.stderr.write('usage: landlock.py RULES.json COMMAND\n')
        return 2
    data = json.loads(Path(argv[1]).read_text())
    if data.get('schema') != SCHEMA:
        sys.stderr.write('Unknown Landlock rules\n')
        return 126
    if argv[2] in data.get('unconfined', []):
        os.execv('/bin/bash', ['bash', '-c', argv[2]])
    try:
        # As the Codex tool worker: seccomp for what Landlock leaves open, then the file and TCP rules.
        seccomp_filter(abi(), ignore_mode_changes=True)
        restrict([tuple(rule) for rule in data['rules']])
    except (OSError, RuntimeError) as error:
        sys.stderr.write('Bash isolation unavailable: %s\n' % error)
        return 126
    os.execv('/bin/bash', ['bash', '-c', argv[2]])


if __name__ == '__main__':
    sys.exit(main(sys.argv))
