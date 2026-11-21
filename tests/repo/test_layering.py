"""The subpackages of roboteam/ are layered: a lower one never imports a higher one.

sim < tasks < runtime < harness < launch. roboteam/io.py is below all of them.
docs/development/repository-layout.md states the rule.
"""

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ORDER = ('sim', 'tasks', 'runtime', 'harness', 'launch')
# Two harness entry points that start a launcher service or archive on purpose.
ALLOWED = {
    ('roboteam/harness/claude/recover_task.py', 'roboteam.launch.local'),
    ('roboteam/harness/codex/job_harness.py', 'roboteam.launch.results.session_archive'),
}


def imported_modules(path):
    """Absolute names of the roboteam modules a file imports, at any depth of the file."""
    package = path.relative_to(ROOT).with_suffix('').parts[:-1]
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            yield from ((a.name, node.lineno) for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                names = [node.module] if node.module else [a.name for a in node.names]
                yield from (('.'.join((*base, name)), node.lineno) for name in names)
            elif node.module:
                yield node.module, node.lineno


class LayeringTests(unittest.TestCase):
    def test_no_subpackage_imports_a_higher_one(self):
        wrong = []
        for path in sorted((ROOT / 'roboteam').rglob('*.py')):
            parts = path.relative_to(ROOT).parts
            if len(parts) < 3 or parts[1] not in ORDER:
                continue
            for module, line in imported_modules(path):
                target = module.split('.')
                if target[0] != 'roboteam' or len(target) < 2:
                    continue
                name = '/'.join(parts)
                if target[1] == 'cli' and parts[1] != 'launch':
                    wrong.append(f'{name}:{line} imports the command line ({module})')
                elif target[1] in ORDER and ORDER.index(target[1]) > ORDER.index(parts[1]):
                    if not any(name == file and module.startswith(prefix) for file, prefix in ALLOWED):
                        wrong.append(f'{name}:{line} imports {module}')
        self.assertEqual(wrong, [])

    def test_the_shared_plumbing_imports_nothing_of_the_package(self):
        for module, line in imported_modules(ROOT / 'roboteam/io.py'):
            self.assertFalse(module.startswith('roboteam'), f'roboteam/io.py:{line} imports {module}')


if __name__ == '__main__':
    unittest.main()
