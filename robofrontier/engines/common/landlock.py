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
TCP connection and bind, and fail closed: without Landlock network rules (ABI 4,
Linux 6.7) the command does not run. Landlock does not cover UDP or named Unix
sockets, and before ABI 6 it does not stop signals.

Standard library only, so the prefix runs it with `python -I` before any import.
"""
import ctypes
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
REFER, TRUNCATE, IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15
FILE_ONLY = EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE | IOCTL_DEV
READ = EXECUTE | READ_FILE | READ_DIR
BIND_TCP, CONNECT_TCP = 1 << 0, 1 << 1
SCOPE_ABSTRACT_UNIX, SCOPE_SIGNAL = 1 << 0, 1 << 1
NETWORK_ABI = 4
# Devices a shell writes to as a matter of course.
DEVICES = ('/dev/null', '/dev/tty')


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
    if abi() >= NETWORK_ABI:
        return 'landlock-v1'
    raise ValueError('No Bash isolation on this host: bubblewrap cannot create namespaces and '
                     'Landlock with network rules (ABI 4) is unavailable')


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
                access = (READ if mode == 'read' else fs)
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
        restrict([tuple(rule) for rule in data['rules']])
    except OSError as error:
        sys.stderr.write('Bash isolation unavailable: %s\n' % error)
        return 126
    os.execv('/bin/bash', ['bash', '-c', argv[2]])


if __name__ == '__main__':
    sys.exit(main(sys.argv))
