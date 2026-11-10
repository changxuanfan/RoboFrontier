import py_compile
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class ScriptsIndexTests(unittest.TestCase):
    def tracked_scripts(self):
        names = subprocess.run(['git', 'ls-files', 'scripts'], capture_output=True, text=True, cwd=ROOT,
                               check=True).stdout.split()
        return {Path(n).name for n in names if Path(n).name != 'README.md'}

    def test_every_script_is_indexed_and_every_index_entry_exists(self):
        index = (ROOT/'scripts/README.md').read_text()
        listed = set(re.findall(r'\| `([A-Za-z0-9_]+\.(?:py|js|sh|sbatch))`', index))
        scripts = self.tracked_scripts()
        self.assertEqual(sorted(scripts - listed), [], 'add these scripts to scripts/README.md')
        self.assertEqual(sorted(listed - scripts), [], 'remove these entries from scripts/README.md')

    def test_every_python_script_compiles(self):
        with tempfile.TemporaryDirectory() as temporary:
            for name in sorted(n for n in self.tracked_scripts() if n.endswith('.py')):
                with self.subTest(script=name):
                    py_compile.compile(str(ROOT/'scripts'/name), cfile=str(Path(temporary)/(name+'c')), doraise=True)


if __name__ == '__main__':
    unittest.main()
