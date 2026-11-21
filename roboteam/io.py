"""Shared plumbing: the repository root, file hashes, atomic JSON writes, file clones, the
.env loader and MJCF vectors. It imports nothing else of the package."""

import ctypes
import hashlib
import json
import os
import re
import shlex
import shutil
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path):
    """Hex SHA-256 of a file's bytes, read in blocks."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    """Write JSON atomically: private (0600), fsynced, then renamed into place; NaN is rejected."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    fd, temporary = tempfile.mkstemp(prefix='.' + path.name + '-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as out:
            os.fchmod(out.fileno(), 0o600)
            out.write(payload)
            out.flush()
            os.fsync(out.fileno())
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def vector(values):
    """An MJCF vector attribute from numbers."""
    return " ".join(str(float(x)) for x in values)


try:  # macOS clonefile(2); absent elsewhere.
    _clonefile = ctypes.CDLL(None, use_errno=True).clonefile
    _clonefile.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32)
except (AttributeError, OSError):
    _clonefile = None
FICLONE = 0x40049409  # Linux reflink ioctl (Btrfs, XFS, bcachefs).


def _reflink(source, target):
    import fcntl

    with open(source, 'rb') as src, open(target, 'xb') as dst:
        try:
            fcntl.ioctl(dst.fileno(), FICLONE, src.fileno())
        except OSError:
            dst.close()
            os.unlink(target)
            raise
    shutil.copystat(source, target)


def clone_or_copy(source, target):
    """Copy-on-write clone where the file system supports it (APFS clonefile, Linux
    reflink), else a plain copy.

    A clone takes no extra space yet stays an independent file: writing to a run's
    frozen copy never reaches the source or other runs, unlike a hard link."""
    try:
        if _clonefile is not None:
            if _clonefile(os.fsencode(source), os.fsencode(target), 0) == 0:
                shutil.copystat(source, target)
                return target
        elif hasattr(os, 'uname') and os.uname().sysname == 'Linux':
            _reflink(source, target)
            return target
    except (OSError, ImportError):
        pass
    return shutil.copy2(source, target)


def load_env(path):
    """Load literal KEY=value entries; existing process environment wins."""
    path = Path(path)
    if not path.is_file():
        return
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, sep, raw = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError(f'Invalid .env entry at line {number}')
        try:
            values = shlex.split(raw, comments=True, posix=True)
        except ValueError as error:
            raise ValueError(f'Invalid .env value at line {number}') from error
        if len(values) > 1:
            raise ValueError(f'Quote whitespace in .env value at line {number}')
        os.environ.setdefault(key, values[0] if values else '')
