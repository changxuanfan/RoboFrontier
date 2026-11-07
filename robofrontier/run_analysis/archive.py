"""Read one run's files in place from a directory, tar, zip or object archive. Nothing is unpacked.

A run key names the run relative to a data root: `dir/of/run` for a plain folder, or
`container//inner/prefix` for a run inside a `.tar`, a `.zip` (optionally `manifest.json::prefix`
for a content-addressed zip) or a content-addressed folder with `manifest.json` and `objects/`.
"""

import hashlib
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import zipfile
import zlib


def default_cache_dir():
    return Path(tempfile.gettempdir()) / 'robofrontier-tar-index'


def tar_index(path, cache_dir=None):
    """Member offsets of an uncompressed tar, cached so later runs seek directly."""
    cache = Path(cache_dir) if cache_dir else default_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    p = cache / (hashlib.sha1(str(path).encode()).hexdigest()[:16] + '.jsonl')
    if not p.exists():
        tmp = p.with_suffix('.tmp.%d' % os.getpid())
        with tarfile.open(path, 'r:') as a, open(tmp, 'w') as o:
            for m in a:
                if m.isfile():
                    o.write(json.dumps([m.name, m.offset_data, m.size]) + '\n')
                a.members = []
        os.replace(tmp, p)
    return p


class Run:
    def __init__(self, k, root, cache_dir=None):
        V = Path(root)
        self.k = k
        self.files = {}
        if '//' not in k:
            self.kind = 'dir'
            b = V / k
            for d, _, fs in os.walk(b):
                for f in fs:
                    q = Path(d) / f
                    self.files[str(q.relative_to(b))] = q
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
                            self.files[f['path'][len(pre) :]] = f
                else:
                    self.kind = 'zip_custom'
                    for f in m:
                        if f['path'].startswith(pre):
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
                    self.files[f['path'][len(pre) :]] = f

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
            return self.z.read('objects/' + h['sha256'][:2] + '/' + h['sha256'])
        if K == 'zip_objects':
            raw = self.z.read(self.pre + 'objects/' + h['object'][:2] + '/' + h['object'])
        else:
            raw = (self.base / 'objects' / h['object'][:2] / h['object']).read_bytes()
        return zlib.decompress(raw)

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
        if K in ('zip', 'zip_custom'):
            name = h if K == 'zip' else 'objects/' + h['sha256'][:2] + '/' + h['sha256']
            with self.z.open(name) as f:
                for p in io.TextIOWrapper(f, errors='replace'):
                    yield p
            return
        raw = (
            self.z.open(self.pre + 'objects/' + h['object'][:2] + '/' + h['object'])
            if K == 'zip_objects'
            else open(self.base / 'objects' / h['object'][:2] / h['object'], 'rb')
        )
        d = zlib.decompressobj()
        tail = b''
        with raw:
            while True:
                b = raw.read(1 << 22)
                if not b:
                    break
                parts = (tail + d.decompress(b)).split(b'\n')
                tail = parts.pop()
                for p in parts:
                    yield p.decode(errors='replace')
        if tail:
            yield tail.decode(errors='replace')

    def find(self, *ends):
        for e in ends:
            for n in self.files:
                if n == e or n.endswith('/' + e):
                    return n
