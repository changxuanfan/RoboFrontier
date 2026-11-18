"""policy.tools in the public configuration."""

import unittest

from roboteam.configuration import load_configuration, validate_configuration


class ToolModeConfigurationTests(unittest.TestCase):
    def test_the_default_is_a_full_run(self):
        self.assertEqual(load_configuration()['policy']['tools'], 'full')

    def test_only_the_two_modes_are_accepted(self):
        for mode in ('full', 'robot_only'):
            self.assertEqual(
                load_configuration(overrides={'policy': {'tools': mode}})['policy']['tools'], mode
            )
        with self.assertRaises(ValueError):
            load_configuration(overrides={'policy': {'tools': 'no_shell'}})

    def test_robot_only_codex_uses_no_tool_worker_on_any_host(self):
        for host in (None, 'slurm', 'container'):
            config = load_configuration(
                host=host, overrides={'policy': {'harness': 'codex', 'tools': 'robot_only'}}
            )
            self.assertEqual(config['runtime']['codex_tool_backend'], 'native', host)
        # A full Codex run on Linux keeps the tool worker, as before.
        full = load_configuration(host='slurm', overrides={'policy': {'harness': 'codex'}})
        self.assertEqual(full['runtime']['codex_tool_backend'], 'landlock-v1')
        with self.assertRaisesRegex(ValueError, 'robot_only'):
            load_configuration(
                overrides={
                    'policy': {'harness': 'codex', 'tools': 'robot_only'},
                    'runtime': {'codex_tool_backend': 'landlock-v1'},
                }
            )

    def test_robot_only_claude_validates(self):
        config = load_configuration(overrides={'policy': {'harness': 'claude', 'tools': 'robot_only'}})
        validate_configuration(config)
        self.assertEqual(config['policy']['tools'], 'robot_only')

    def test_a_robot_only_codex_receipt_never_replaces_the_full_one(self):
        from roboteam.cli import _receipt_name
        from roboteam.runtime.tools.tools_mode import receipt_name

        self.assertEqual(receipt_name('luna', 'full'), 'luna')
        self.assertEqual(receipt_name('luna', 'robot_only'), 'luna.robot_only')
        self.assertEqual(_receipt_name({'model': 'luna'}), 'luna')
        self.assertEqual(_receipt_name({'model': 'luna', 'tools': 'robot_only'}), 'luna.robot_only')


if __name__ == '__main__':
    unittest.main()
