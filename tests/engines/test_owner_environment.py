"""Both engines start the physics owner with one environment, without credentials (E4)."""
import json
import os
import subprocess
import sys
import unittest

from robofrontier.engines.common import owner
from robofrontier.io import ROOT


class OwnerEnvironmentTests(unittest.TestCase):
    def test_credentials_never_reach_the_owner_and_threads_are_fixed(self):
        base = {'PATH': '/bin', 'HOME': '/h', 'ANTHROPIC_API_KEY': 'sk-x', 'CLAUDE_CODE_OAUTH_TOKEN': 't', 'OPENAI_API_KEY': 'k',
                'OMP_NUM_THREADS': '64', 'MUJOCO_GL': 'egl'}
        env = owner.environment(base)
        self.assertEqual({k for k in env if 'KEY' in k or 'TOKEN' in k}, set())
        self.assertEqual((env['PATH'], env['MUJOCO_GL'], env['OMP_NUM_THREADS'], env['LP_NUM_THREADS']), ('/bin', 'egl', '1', '2'))

    def test_the_codex_host_reads_the_same_environment(self):
        printed = subprocess.run([sys.executable, '-m', 'robofrontier.engines.common.owner', 'env'], cwd=ROOT, capture_output=True,
                                 text=True, check=True, env={**os.environ, 'OPENAI_API_KEY': 'secret'}).stdout
        env = json.loads(printed)
        self.assertNotIn('OPENAI_API_KEY', env); self.assertEqual(env['OPENBLAS_NUM_THREADS'], '1')
        host = (ROOT/'robofrontier/engines/codex/codex_policy_host.js').read_text()
        self.assertIn("'robofrontier.engines.common.owner','env'", host)
        self.assertIn('env:ownerEnv,detached:true', host)


if __name__ == '__main__':
    unittest.main()
