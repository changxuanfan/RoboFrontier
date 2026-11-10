"""Kept records may name history removed from the tree, but only through benchmark/pruned-paths.json."""
import json
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PREFIXES = ('configs/', 'benchmark/', 'benchmarks/', 'prompts/', 'robofrontier/', 'scripts/', 'docs/', 'tests/', 'site/')


def tracked():
    names = set(subprocess.run(['git', 'ls-files'], capture_output=True, text=True, cwd=ROOT, check=True).stdout.split())
    folders = {str(parent) for name in names for parent in Path(name).parents if str(parent) != '.'}
    return names, folders


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from strings(item)


class PrunedPathsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = json.loads((ROOT/'benchmark/pruned-paths.json').read_text())
        cls.names, cls.folders = tracked()

    def present(self, path):
        return path in self.names or path in self.folders

    def all_pruned(self):
        return self.index['paths'] + [p for group in self.index['later'] for p in group['paths']]

    def test_pruned_and_moved_paths_are_gone_and_moves_point_at_files(self):
        self.assertEqual([p for p in self.all_pruned() if self.present(p)], [])
        for old, new in self.index['moved'].items():
            self.assertFalse(self.present(old), old)
            self.assertIn(new, self.names)

    def test_every_path_a_record_names_exists_or_is_indexed(self):
        legacy = json.loads((ROOT/'benchmark/legacy-paths.json').read_text())['paths']
        def current(name):
            for old in sorted(legacy, key=len, reverse=True):
                if name == old or name.startswith(old+'/'):
                    return legacy[old]+name[len(old):]
            return name
        pruned = tuple(self.all_pruned())
        missing = set()
        for record in sorted(n for n in self.names if n.endswith('.json') and n.startswith(('configs/', 'benchmark/'))):
            if record in ('benchmark/legacy-paths.json', 'benchmark/pruned-paths.json'):
                continue  # Mappings, not records; the index itself is checked above.
            for value in strings(json.loads((ROOT/record).read_text())):
                if not value.startswith(PREFIXES) or ' ' in value or len(value) > 300:
                    continue
                path = current(value.split('#')[0].split('::')[0].rstrip('/'))
                if (self.present(path) or '/assets/' in path or path.endswith('/assets')  # Restored by bootstrap.
                        or path in self.index['moved'] or path.startswith(tuple(self.index['generated']))
                        or any(path == p or path.startswith(p+'/') for p in pruned)):
                    continue
                missing.add((record, value))
        self.assertEqual(sorted(missing), [], 'restore these paths or add them to benchmark/pruned-paths.json')

    def test_pruned_paths_exist_at_their_archive_tag(self):
        groups = [(self.index['archive_tag'], self.index['paths'])]
        groups += [(group['archive_tag'], group['paths']) for group in self.index['later']]
        for tag, paths in groups:
            listed = subprocess.run(['git', 'ls-tree', '-r', '--name-only', tag], capture_output=True, text=True, cwd=ROOT)
            if listed.returncode:
                self.skipTest('Archive tag not fetched: '+tag)
            archived = set(listed.stdout.split())
            archived |= {str(parent) for name in archived for parent in Path(name).parents}
            self.assertEqual([p for p in paths if p not in archived], [], tag)


if __name__ == '__main__':
    unittest.main()
