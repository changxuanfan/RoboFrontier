"""Package the verified content-addressed evidence archive as one portable ZIP."""
import os
from pathlib import Path, PurePosixPath
import stat
import tempfile
import zipfile


def pack(archive, output):
    """Publish a new ZIP atomically, retaining both the collection and sources."""
    from robofrontier.batch.archive_policy_batch import verify
    archive, output = Path(archive).resolve(), Path(output).resolve()
    if output.exists() or output.is_relative_to(archive):
        raise ValueError('ZIP output must be new and outside the archive directory')
    verify(archive)
    output.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix='.rf-evidence-', suffix='.zip', dir=output.parent)
    os.close(fd)
    try:
        # Object payloads already use their own lossless encoding. Recompressing
        # the container costs CPU without improving those objects materially.
        with zipfile.ZipFile(temporary, 'w', compression=zipfile.ZIP_STORED, allowZip64=True) as target:
            for path in sorted(archive.rglob('*')):
                if path.is_symlink():
                    raise ValueError('Symlinks are not supported in evidence ZIPs')
                if path.is_file():
                    target.write(path, path.relative_to(archive).as_posix())
        with zipfile.ZipFile(temporary) as result:
            if result.testzip() is not None:
                raise ValueError('Evidence ZIP failed its CRC check')
        with open(temporary, 'rb') as stream:
            os.fsync(stream.fileno())
        # Same-filesystem publication without replacing an existing result.
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return output


def unpack(source, output):
    """Extract an archive into a new directory, rejecting unsafe members."""
    output = Path(output).resolve()
    if output.exists():
        raise ValueError('Choose a new evidence extraction directory')
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        names = set()
        for member in members:
            name = PurePosixPath(member.filename)
            mode = member.external_attr >> 16
            if (not name.parts or name.is_absolute() or '..' in name.parts or
                    '\\' in member.filename or ':' in name.parts[0] or
                    stat.S_ISLNK(mode) or member.filename in names):
                raise ValueError('Unsafe or duplicate ZIP member')
            if mode and stat.S_IFMT(mode) not in (0, stat.S_IFREG, stat.S_IFDIR):
                raise ValueError('Nonregular ZIP member')
            names.add(member.filename)
        if 'manifest.json' not in names:
            raise ValueError('Expected an evidence archive manifest')
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.rf-unpack-', dir=output.parent) as temporary:
            staged = Path(temporary)/'archive'
            archive.extractall(staged)
            from robofrontier.batch.archive_policy_batch import verify
            report = verify(staged)
            if output.exists():
                raise FileExistsError(output)
            staged.rename(output)
    return report
