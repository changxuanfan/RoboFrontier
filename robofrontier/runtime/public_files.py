"""Read-only access to a run's public/ folder for a role that has no file tools.

A full run's file tools can read public/ (and nothing they could not read is opened
here): the frozen task inputs, saved observations, delegate reports and robot models. A
robot_only run reaches the same files through the robot tool's `public_file` operation.
Nothing is written, and a path that leaves public/ (also through a symbolic link) is
refused.
"""
from pathlib import Path

MAX_TEXT_BYTES = 200_000
MAX_IMAGE_BYTES = 8_000_000
MAX_ENTRIES = 500
_IMAGES = ((b'\x89PNG\r\n\x1a\n', 'image/png'), (b'\xff\xd8\xff', 'image/jpeg'))


def image_mime(data):
    return next((mime for magic, mime in _IMAGES if data.startswith(magic)), None)


def resolve(run, name):
    """The file or folder `name` means, inside this run's public/ folder.

    `name` is relative to public/inputs/ (as task.json lists its references), or starts
    with public/, or is the absolute path the first message printed.
    """
    run = Path(run).resolve()
    public = run/'public'
    if not isinstance(name, str) or not name or '\0' in name or len(name) > 1024:
        raise ValueError('path must be a nonempty string')
    given = Path(name)
    if given.is_absolute():
        candidates = [given]
    elif given.parts[0] == 'public':
        candidates = [run/given]
    else:
        candidates = [public/'inputs'/given, public/given]
    for candidate in candidates:
        path = candidate.resolve()
        if path.is_relative_to(public) and path.exists():
            return path
    raise ValueError('Not a file or folder in this run\'s public/ folder: ' + name)


def listing(run, folder):
    run = Path(run).resolve()
    entries = []
    for path in sorted(folder.iterdir()):
        if path.is_symlink() or path.name.startswith('.'):
            continue
        entries.append({'path': str(path.relative_to(run)), 'kind': 'directory'} if path.is_dir() else
                       {'path': str(path.relative_to(run)), 'bytes': path.stat().st_size})
    more = len(entries) - MAX_ENTRIES
    return {'path': str(folder.relative_to(run)), 'kind': 'directory', 'entries': entries[-MAX_ENTRIES:],
            **({'earlier_entries_not_listed': more} if more > 0 else {})}


def inputs(run):
    """Every frozen task input, as the first message named them."""
    run = Path(run).resolve()
    root = run/'public/inputs'
    files = [path for path in sorted(root.rglob('*')) if path.is_file() and not path.is_symlink()]
    return {'path': 'public/inputs', 'kind': 'directory',
            'entries': [{'path': str(path.relative_to(run)), 'bytes': path.stat().st_size} for path in files],
            'other_public_folders': sorted(str(path.relative_to(run)) for path in (run/'public').iterdir()
                                           if path.is_dir() and path != root)}


def read(run, data):
    """The result of `public_file`: a listing, a text file's content, or an image reference.

    An image is returned as `image`, the file's path; the role's robot tool loads it as
    it loads an observation.
    """
    if set(data) - {'path'}:
        raise ValueError('public_file accepts an optional path')
    run = Path(run).resolve()
    if 'path' not in data:
        return inputs(run)
    path = resolve(run, data['path'])
    if path.is_dir():
        return listing(run, path)
    relative, size = str(path.relative_to(run)), path.stat().st_size
    with path.open('rb') as stream:
        head = stream.read(8)
    if image_mime(head):
        if size > MAX_IMAGE_BYTES:
            raise ValueError('Image is too large to return: %d bytes' % size)
        return {'path': relative, 'kind': 'image', 'image': str(path)}
    if size > MAX_TEXT_BYTES:
        raise ValueError('File is too large to return (%d bytes; limit %d). For robot geometry, robot_model '
                         'with a robot ID returns one robot.' % (size, MAX_TEXT_BYTES))
    try:
        text = path.read_bytes().decode('utf-8')
    except UnicodeDecodeError:
        raise ValueError('Not a text, PNG or JPEG file: ' + relative) from None
    return {'path': relative, 'kind': 'text', 'text': text}
