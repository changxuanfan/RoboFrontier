import unittest
from pathlib import Path

from roboteam.harness.claude.session.runner import build_env


class ClaudeConfigIsolationTests(unittest.TestCase):
    def test_parallel_jobs_use_distinct_task_configuration_directories(self):
        model_entry = {'env_key': 'ANTHROPIC_API_KEY', 'provider': 'anthropic'}
        env = {'ANTHROPIC_API_KEY': 'fake'}
        configs = [Path('/tmp/batch') / str(i) / 'private/harness/config' for i in range(36)]
        self.assertEqual(len({build_env(model_entry, env, p)['CLAUDE_CONFIG_DIR'] for p in configs}), 36)
