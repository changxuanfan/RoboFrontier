"""policy.tool_mode in the public configuration."""
import unittest

from roboteam.configuration import load_configuration, validate_configuration


class ToolModeConfigurationTests(unittest.TestCase):
    def test_the_default_is_a_full_run(self):
        self.assertEqual(load_configuration()['policy']['tool_mode'], 'full')

    def test_only_the_two_modes_are_accepted(self):
        for mode in ('full', 'robot_only'):
            self.assertEqual(load_configuration(overrides={'policy': {'tool_mode': mode}})['policy']['tool_mode'], mode)
        with self.assertRaises(ValueError):
            load_configuration(overrides={'policy': {'tool_mode': 'no_shell'}})

    def test_robot_only_codex_uses_no_tool_worker_on_any_host(self):
        for host in (None, 'slurm', 'container'):
            config = load_configuration(host=host, overrides={'policy': {'engine': 'codex', 'tool_mode': 'robot_only'}})
            self.assertEqual(config['runtime']['codex_tool_backend'], 'native', host)
        # A full Codex run on Linux keeps the tool worker, as before.
        full = load_configuration(host='slurm', overrides={'policy': {'engine': 'codex'}})
        self.assertEqual(full['runtime']['codex_tool_backend'], 'landlock-v1')
        with self.assertRaisesRegex(ValueError, 'robot_only'):
            load_configuration(overrides={'policy': {'engine': 'codex', 'tool_mode': 'robot_only'},
                                          'runtime': {'codex_tool_backend': 'landlock-v1'}})

    def test_robot_only_claude_validates(self):
        config = load_configuration(overrides={'policy': {'engine': 'claude', 'tool_mode': 'robot_only'}})
        validate_configuration(config)
        self.assertEqual(config['policy']['tool_mode'], 'robot_only')

    def test_a_robot_only_codex_receipt_never_replaces_the_full_one(self):
        from roboteam.cli import _receipt_name
        from roboteam.runtime.tool_mode import receipt_name
        self.assertEqual(receipt_name('luna', 'full'), 'luna')
        self.assertEqual(receipt_name('luna', 'robot_only'), 'luna.robot_only')
        self.assertEqual(_receipt_name({'profile': 'luna'}), 'luna')
        self.assertEqual(_receipt_name({'profile': 'luna', 'tool_mode': 'robot_only'}), 'luna.robot_only')


if __name__ == '__main__':
    unittest.main()
