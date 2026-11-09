import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import fetch_robot

XML = b'<mujoco><asset><mesh file="link0.stl"/></asset></mujoco>'
FILES = {'panda.xml': XML, 'assets/link0.stl': b'mesh', 'LICENSE': b'license', 'README.md': b'readme'}


def served(url):
    return FILES[next(name for name in FILES if url.endswith('/'+name))]


class FetchRobotTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def run_fetch(self, pinned, argv=()):
        root = self.root
        (root/'manifest.json').write_text(json.dumps({'robot_source': pinned}))
        urls = []
        def get(url):
            urls.append(url)
            return served(url)
        with mock.patch.object(fetch_robot, 'DEST', root/'vendor/panda'), \
                mock.patch.object(fetch_robot, 'PINNED', root/'manifest.json'), \
                mock.patch.object(fetch_robot, 'get', side_effect=get), mock.patch('builtins.print'):
            fetch_robot.main(list(argv))
        return root/'vendor/panda', urls

    def pinned(self, **changes):
        hashes = {name: hashlib.sha256(data).hexdigest() for name, data in FILES.items()}
        hashes.update(changes)
        return {'repository': 'r', 'commit': 'pinned123', 'sha256': hashes}

    def test_without_a_source_file_the_pinned_commit_is_fetched_and_verified(self):
        dest, urls = self.run_fetch(self.pinned())
        self.assertTrue(all('/pinned123/' in url for url in urls))
        self.assertEqual(json.loads((dest/'SOURCE.json').read_text())['commit'], 'pinned123')
        self.assertEqual((dest/'assets/link0.stl').read_bytes(), b'mesh')

    def test_a_wrong_hash_aborts_without_writing_vendor(self):
        with self.assertRaisesRegex(SystemExit, 'assets/link0.stl'):
            self.run_fetch(self.pinned(**{'assets/link0.stl': '0'*64}))
        self.assertFalse((self.root/'vendor').exists())

    def test_another_commit_needs_an_explicit_flag(self):
        dest, urls = self.run_fetch(self.pinned(), ['--commit', 'other456'])
        self.assertTrue(all('/other456/' in url for url in urls))


if __name__ == '__main__':
    unittest.main()
