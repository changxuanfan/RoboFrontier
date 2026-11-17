"""Shared plumbing: the repository root, file hashes, atomic JSON writes and MJCF vectors."""
import hashlib
import json
import os
from pathlib import Path
import tempfile


ROOT = Path(__file__).resolve().parents[1]


def file_sha256(path):
    """Hex SHA-256 of a file's bytes, read in blocks."""
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_json(path, value):
    """Write JSON atomically: private (0600), fsynced, then renamed into place; NaN is rejected."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n'
    fd, temporary = tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
    try:
        with os.fdopen(fd,'w') as out:
            os.fchmod(out.fileno(),0o600)
            out.write(payload);out.flush();os.fsync(out.fileno())
        os.replace(temporary,path)
    finally:
        if Path(temporary).exists():Path(temporary).unlink()


def vector(values):
    """An MJCF vector attribute from numbers."""
    return " ".join(str(float(x)) for x in values)
