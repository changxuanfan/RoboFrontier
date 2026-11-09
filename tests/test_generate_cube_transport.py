import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import generate_cube_transport as script


def fake_environment(count, base, render, rows, manifest, summaries, task_overview):
    rows.append({'environment': f'e{count}', 'arms': count, 'seed': 0})
    manifest.append({'environment': f'e{count}'})
    summaries.append({'environment': f'e{count}', 'passed': True})


class GenerateCubeTransportTests(unittest.TestCase):
    def test_a_count_subset_leaves_collection_files_unchanged(self):
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            (base/'references').mkdir()
            files = {base/'manifest.json': json.dumps({'environments': [{'environment': f'e{n}'} for n in range(3, 13)]}),
                     base/'references/summary.csv': 'all ten\n', base/'tasks.md': 'catalog\n'}
            for path, text in files.items():
                path.write_text(text)
            with mock.patch.object(script, 'generate_environment', side_effect=fake_environment), \
                    mock.patch.object(script, 'check_robot_source', return_value={}), mock.patch('builtins.print'):
                script.generate([7], render=False, base=base)
            for path, text in files.items():
                self.assertEqual(path.read_text(), text, path)

    def test_a_different_vendored_panda_is_refused(self):
        with tempfile.TemporaryDirectory() as root:
            root = Path(root)
            (root/'vendor/panda').mkdir(parents=True)
            (root/'vendor/panda/SOURCE.json').write_text(json.dumps({'commit': 'new'}))
            (root/'manifest.json').write_text(json.dumps({'robot_source': {'commit': 'pinned'}}))
            with self.assertRaisesRegex(ValueError, 'pinned'):
                script.check_robot_source(root, root)
            (root/'vendor/panda/SOURCE.json').write_text(json.dumps({'commit': 'pinned'}))
            self.assertEqual(script.check_robot_source(root, root), {'commit': 'pinned'})


if __name__ == '__main__':
    unittest.main()
