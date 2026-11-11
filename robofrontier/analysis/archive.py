"""Read one run's files in place from a directory, tar, zip or object archive. Nothing is unpacked.

A run key names the run relative to a data root: `dir/of/run` for a plain folder, or
`container//inner/prefix` for a run inside a `.tar`, a `.zip` (optionally `manifest.json::prefix`
for a content-addressed zip) or a content-addressed folder with `manifest.json` and `objects/`.

A key that resolves to no files raises FileNotFoundError, so a typo or an unmounted drive is
never read as an empty run. Content-addressed objects are named by the SHA-256 of their
(decompressed) bytes; every read checks it.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import re
import tarfile
import tempfile
import zipfile
import zlib


def default_cache_dir():
    return Path(tempfile.gettempdir()) / 'robofrontier-tar-index'


OBJECT_NAME = re.compile(r'[0-9a-f]{64}')


def object_name(name):
    """A content address from a manifest; anything else (a path, `..`) is refused."""
    if not isinstance(name, str) or not OBJECT_NAME.fullmatch(name):
        raise ValueError('Invalid object name in manifest: %r' % (name,))
    return name


def tar_index(path, cache_dir=None):
    """Member offsets of an uncompressed tar, cached so later runs seek directly.

    The cache is bound to the archive's identity (resolved path, size, modification time, inode
    and a hash of its first and last 64 KiB), so a tar that was rewritten or was still growing is
    indexed again, also where a rewrite in place keeps size and inode and the file system's
    modification time is coarse (Lustre)."""
    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    st = os.stat(path)
    edges = hashlib.sha256()
    with open(path, 'rb') as stream:
        edges.update(stream.read(65536))
        if st.st_size > 65536:
            stream.seek(max(65536, st.st_size - 65536)); edges.update(stream.read())
    ident = '%s|%d|%d|%d|%s' % (Path(path).resolve(), st.st_size, st.st_mtime_ns, st.st_ino, edges.hexdigest())
    p = cache / (hashlib.sha1(ident.encode()).hexdigest()[:16] + '.jsonl')
    if not p.exists():
        tmp = p.with_suffix('.tmp.%d' % os.getpid())
        with tarfile.open(path, 'r:') as a, open(tmp, 'w') as o:
            for m in a:
                if m.isfile():
                    o.write(json.dumps([m.name, m.offset_data, m.size]) + '\n')
                a.members = []
        os.replace(tmp, p)
    return p


def _verified(data, want):
    if hashlib.sha256(data).hexdigest() != want:
        raise ValueError('Object %s does not match its content address' % want)
    return data


class Run:
    def __init__(self, k, root, cache_dir=None):
        V = Path(root)
        self.k = k
        self.files = {}
        if '//' not in k:
            self.kind = 'dir'
            b = V / k
            if not b.is_dir():
                raise FileNotFoundError('Run folder missing: %s' % b)
            for d, _, fs in os.walk(b):
                for f in fs:
                    q = Path(d) / f
                    self.files[str(q.relative_to(b))] = q
            self._require_files()
            return
        c, rest = k.split('//', 1)
        C = V / c
        if c.endswith('.tar'):
            self.kind = 'tar'
            pre = rest.rstrip('/') + '/'
            self.fh = open(C, 'rb')
            with open(tar_index(C, cache_dir)) as idx:
                for l in idx:
                    n, o, s = json.loads(l)
                    if n.startswith(pre):
                        self.files[n[len(pre) :]] = (o, s)
        elif c.endswith('.zip'):
            self.z = zipfile.ZipFile(C)
            if '::' in rest:
                man, pre = rest.split('::', 1)
                pre = pre.rstrip('/')
                pre = pre + '/' if pre and pre != 'private' else ''
                m = json.loads(self.z.read(man))
                if isinstance(m, dict):
                    self.kind = 'zip_objects'
                    self.pre = man[: -len('manifest.json')]
                    for f in m['files']:
                        if f['path'].startswith(pre):
                            object_name(f['object'])
                            self.files[f['path'][len(pre) :]] = f
                else:
                    self.kind = 'zip_custom'
                    for f in m:
                        if f['path'].startswith(pre):
                            object_name(f['sha256'])
                            self.files[f['path'][len(pre) :]] = f
            else:
                self.kind = 'zip'
                pre = rest.rstrip('/') + '/'
                for n in self.z.namelist():
                    if n.startswith(pre) and not n.endswith('/'):
                        self.files[n[len(pre) :]] = n
        else:
            self.kind = 'dir_objects'
            self.base = C
            m = json.loads((C / 'manifest.json').read_text())
            pre = rest.rstrip('/') + '/'
            for f in m['files']:
                if f['path'].startswith(pre):
                    object_name(f['object'])
                    self.files[f['path'][len(pre) :]] = f
        self._require_files()

    def _require_files(self):
        if not self.files:
            self.close()
            raise FileNotFoundError('No files for run key %s' % self.k)

    def close(self):
        for h in (getattr(self, 'fh', None), getattr(self, 'z', None)):
            if h:
                h.close()

    def has(self, n):
        return n in self.files

    def read(self, n):
        h = self.files[n]
        K = self.kind
        if K == 'dir':
            return h.read_bytes()
        if K == 'tar':
            self.fh.seek(h[0])
            return self.fh.read(h[1])
        if K == 'zip':
            return self.z.read(h)
        if K == 'zip_custom':
            return _verified(self.z.read('objects/' + h['sha256'][:2] + '/' + h['sha256']), h['sha256'])
        if K == 'zip_objects':
            raw = self.z.read(self.pre + 'objects/' + h['object'][:2] + '/' + h['object'])
        else:
            raw = (self.base / 'objects' / h['object'][:2] / h['object']).read_bytes()
        return _verified(zlib.decompress(raw), h['object'])

    def lines(self, n):
        """Stream text lines without holding a large log in memory."""
        h = self.files[n]
        K = self.kind
        if K == 'dir':
            with open(h, errors='replace') as f:
                yield from f
            return
        if K == 'tar':
            fh = open(self.fh.name, 'rb')
            fh.seek(h[0])
            left = h[1]
            tail = b''
            while left > 0:
                b = fh.read(min(left, 1 << 22))
                left -= len(b)
                if not b:
                    break
                parts = (tail + b).split(b'\n')
                tail = parts.pop()
                for p in parts:
                    yield p.decode(errors='replace')
            if tail:
                yield tail.decode(errors='replace')
            return
        if K == 'zip':
            with self.z.open(h) as f:
                for p in io.TextIOWrapper(f, errors='replace'):
                    yield p
            return
        if K == 'zip_custom':
            raw, d, want = self.z.open('objects/' + h['sha256'][:2] + '/' + h['sha256']), None, h['sha256']
        elif K == 'zip_objects':
            raw = self.z.open(self.pre + 'objects/' + h['object'][:2] + '/' + h['object'])
            d, want = zlib.decompressobj(), h['object']
        else:
            raw = open(self.base / 'objects' / h['object'][:2] / h['object'], 'rb')
            d, want = zlib.decompressobj(), h['object']
        digest = hashlib.sha256()
        tail = b''
        with raw:
            while True:
                b = raw.read(1 << 22)
                if not b:
                    break
                b = d.decompress(b) if d else b
                digest.update(b)
                parts = (tail + b).split(b'\n')
                tail = parts.pop()
                for p in parts:
                    yield p.decode(errors='replace')
        if d:
            rest = d.flush()
            digest.update(rest)
            tail += rest
        # Every line was already yielded; a mismatch still fails the caller before it finishes.
        if digest.hexdigest() != want:
            raise ValueError('Object %s does not match its content address (%s)' % (want, n))
        if tail:
            yield tail.decode(errors='replace')

    def find(self, *ends):
        for e in ends:
            for n in self.files:
                if n == e or n.endswith('/' + e):
                    return n
