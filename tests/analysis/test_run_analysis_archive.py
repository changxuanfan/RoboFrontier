"""Run archive reader: missing runs, stale tar indexes and content-addressed objects; synthetic data."""

import hashlib
import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
import zlib

from robofrontier.analysis.archive import Run

LOG = 'private/outputs/suite-process.jsonl'


def write_tar(path, members):
    """An uncompressed tar holding `members` ({name: bytes}) in this order."""
    with tarfile.open(path, 'w') as tar:
        for name, data in members.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def object_package(root, files):
    """A content-addressed folder: manifest.json plus zlib objects named by their content hash."""
    entries = []
    for name, data in files.items():
        key = hashlib.sha256(data).hexdigest()
        obj = root / 'objects' / key[:2] / key
        obj.parent.mkdir(parents=True, exist_ok=True)
        obj.write_bytes(zlib.compress(data))
        entries.append(dict(path=name, object=key, size=len(data)))
    (root / 'manifest.json').write_text(json.dumps(dict(files=entries)))
    return entries


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def test_a_missing_run_folder_or_an_unmatched_prefix_is_an_error_not_an_empty_run(self):
        with self.assertRaises(FileNotFoundError):
            Run('does/not/exist', self.root)
        write_tar(self.root / 'batch.tar', {'runs/r1/' + LOG: b'x\n'})
        with self.assertRaises(FileNotFoundError):
            Run('batch.tar//runs/typo', self.root, self.root / 'cache')
        (self.root / 'empty').mkdir()
        with self.assertRaises(FileNotFoundError):
            Run('empty', self.root)

    def test_a_rewritten_tar_is_indexed_again(self):
        tar = self.root / 'batch.tar'
        cache = self.root / 'cache'
        write_tar(tar, {'runs/r1/' + LOG: b'{"matched_goals": 1}\n'})
        first = Run('batch.tar//runs/r1', self.root, cache)
        self.assertEqual(first.read(LOG), b'{"matched_goals": 1}\n')
        first.close()
        # Same path, new content at shifted offsets (an archive rewritten in place).
        write_tar(tar, {'runs/r0/' + LOG: b'x' * 700, 'runs/r1/' + LOG: b'{"matched_goals": 3}\n'})
        second = Run('batch.tar//runs/r1', self.root, cache)
        self.assertEqual(second.read(LOG), b'{"matched_goals": 3}\n')
        second.close()
        other = Run('batch.tar//runs/r0', self.root, cache)
        self.assertEqual(other.read(LOG), b'x' * 700)
        other.close()

    def test_objects_are_checked_against_their_content_address(self):
        pack = self.root / 'pack'
        entries = object_package(pack, {'r/' + LOG: b'a\nb\n'})
        run = Run('pack//r', self.root)
        self.assertEqual(run.read(LOG), b'a\nb\n')
        self.assertEqual(list(run.lines(LOG)), ['a', 'b'])
        key = entries[0]['object']
        (pack / 'objects' / key[:2] / key).write_bytes(zlib.compress(b'a\nX\n'))
        with self.assertRaises(ValueError):
            run.read(LOG)
        with self.assertRaises(ValueError):
            list(run.lines(LOG))

    def test_an_object_name_that_is_not_a_hash_is_refused(self):
        pack = self.root / 'pack'
        pack.mkdir()
        (pack / 'manifest.json').write_text(json.dumps(dict(files=[dict(path='r/a.json', object='../../x')])))
        with self.assertRaises(ValueError):
            Run('pack//r', self.root)


if __name__ == '__main__':
    unittest.main()
