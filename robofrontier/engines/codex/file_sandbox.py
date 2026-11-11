"""Filesystem Landlock for the Codex worker, paired with mandatory seccomp.

ABI 1/2 lack TCP and truncate rules. The worker installs its socket, legacy
truncate/open and metadata seccomp restrictions BEFORE calling this function.
Claude's independent Bash prefix retains its existing ABI 4 requirement.
"""
import ctypes
import os
import stat

from robofrontier.engines.common.landlock import (
    abi, handled_fs, access_for, FILE_ONLY, CREATE_RULESET, ADD_RULE, RESTRICT_SELF,
    PATH_BENEATH, PR_SET_NO_NEW_PRIVS, BIND_TCP, CONNECT_TCP,
    SCOPE_ABSTRACT_UNIX, SCOPE_SIGNAL,
)


def restrict(rules):
    version = abi()
    if version < 1:
        raise OSError('Landlock filesystem isolation is unavailable; refusing to run')
    libc = ctypes.CDLL(None, use_errno=True)
    libc.syscall.restype = ctypes.c_long
    fs = handled_fs(version)
    # Do not send unsupported network/scope attributes to an older kernel.
    net = BIND_TCP | CONNECT_TCP if version >= 4 else 0
    scoped = SCOPE_ABSTRACT_UNIX | SCOPE_SIGNAL if version >= 6 else 0
    attr = (ctypes.c_uint64 * 3)(fs, net, scoped)
    size = 24 if version >= 6 else 16 if version >= 4 else 8
    ruleset = libc.syscall(CREATE_RULESET, ctypes.byref(attr), ctypes.c_size_t(size), ctypes.c_uint32(0))
    if ruleset < 0:
        raise OSError(ctypes.get_errno(), 'landlock_create_ruleset failed')
    class PathBeneath(ctypes.Structure):
        _pack_ = 1
        _fields_ = [('allowed_access', ctypes.c_uint64), ('parent_fd', ctypes.c_int32)]
    try:
        for path, mode in rules:
            if mode not in ('list', 'read', 'write'):
                raise ValueError('Unknown filesystem permission')
            try:
                fd = os.open(path, os.O_PATH | os.O_NOFOLLOW | os.O_CLOEXEC)
            except FileNotFoundError:
                continue
            try:
                kind = os.fstat(fd).st_mode
                if stat.S_ISLNK(kind):
                    continue  # A rule would attach to the link's target, which the table may deny.
                access = access_for(mode, fs)
                if not stat.S_ISDIR(kind):
                    access &= FILE_ONLY
                rule = PathBeneath(access & fs, fd)
                if libc.syscall(ADD_RULE, ctypes.c_int(ruleset), ctypes.c_int(PATH_BENEATH),
                                ctypes.byref(rule), ctypes.c_uint32(0)) < 0:
                    raise OSError(ctypes.get_errno(), 'landlock_add_rule failed')
            finally:
                os.close(fd)
        if libc.prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0):
            raise OSError(ctypes.get_errno(), 'PR_SET_NO_NEW_PRIVS failed')
        if libc.syscall(RESTRICT_SELF, ctypes.c_int(ruleset), ctypes.c_uint32(0)) < 0:
            raise OSError(ctypes.get_errno(), 'landlock_restrict_self failed')
    finally:
        os.close(ruleset)
