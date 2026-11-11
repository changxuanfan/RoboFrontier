"""A Claude subscription token reaches the CLI on a pipe, never in its environment."""
import os
from pathlib import Path
import subprocess
import sys
import unittest

from robofrontier.engines.claude.runner import TOKEN_FD_VARIABLE, start_cli


class TokenPipeTests(unittest.TestCase):
    def test_the_token_is_read_from_a_pipe_and_absent_from_the_environment(self):
        show = ('import os,sys;fd=int(os.environ[%r]);print(os.read(fd,100).decode());'
                'print("CLAUDE_CODE_OAUTH_TOKEN" in os.environ)' % TOKEN_FD_VARIABLE)
        child = start_cli([sys.executable, '-c', show], {'PATH': os.environ['PATH'], 'CLAUDE_CODE_OAUTH_TOKEN': 'secret-1'},
                          stdout=subprocess.PIPE, text=True)
        out, _ = child.communicate(timeout=30)
        self.assertEqual(out.split(), ['secret-1', 'False'])

    def test_without_a_token_nothing_changes(self):
        child = start_cli([sys.executable, '-c', 'import os;print(%r in os.environ)' % TOKEN_FD_VARIABLE],
                          {'PATH': os.environ['PATH']}, stdout=subprocess.PIPE, text=True)
        self.assertEqual(child.communicate(timeout=30)[0].strip(), 'False')

    @unittest.skipUnless(sys.platform.startswith('linux'), '/proc environments are Linux')
    def test_a_token_in_an_ancestors_starting_environment_is_refused(self):
        # The child starts with the name in its environment; loading it later (.env) would not show.
        probe = ('import os;os.environ["ROBOFRONTIER_PROBE_LATER"]="x";'
                 'from robofrontier.engines.claude.runner import environment_holders as h;'
                 'print(bool(h("ROBOFRONTIER_PROBE_EARLY")), bool(h("ROBOFRONTIER_PROBE_LATER")))')
        out = subprocess.run([sys.executable, '-c', probe], env={**os.environ, 'ROBOFRONTIER_PROBE_EARLY': '1'},
                             capture_output=True, text=True, check=True).stdout
        self.assertEqual(out.split(), ['True', 'False'])


if __name__ == '__main__': unittest.main()
