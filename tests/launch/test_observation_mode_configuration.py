"""policy.observation in the public configuration, the CLI and a run's frozen settings."""

import contextlib
import io
import unittest

from roboteam import cli
from roboteam.configuration import load_configuration, validate_configuration
from roboteam.runtime.tools import observation_mode
from roboteam.tasks.config import load_run_settings


class ObservationModeConfigurationTests(unittest.TestCase):
    def test_the_default_is_an_images_run(self):
        self.assertEqual(load_configuration()['policy']['observation'], 'images')
        self.assertEqual(observation_mode.of({}), 'images')
        self.assertEqual(observation_mode.of(load_run_settings()), 'images')

    def test_only_the_two_modes_are_accepted(self):
        for mode in ('images', 'ground_truth'):
            config = load_configuration(overrides={'policy': {'observation': mode}})
            self.assertEqual(config['policy']['observation'], mode)
        with self.assertRaisesRegex(ValueError, 'observation'):
            load_configuration(overrides={'policy': {'observation': 'depth'}})
        with self.assertRaisesRegex(ValueError, 'Unknown observation mode'):
            observation_mode.of({'observation': 'depth'})

    def test_ground_truth_needs_the_code_tools(self):
        for harness in ('codex', 'claude'):
            with self.assertRaisesRegex(ValueError, 'ground_truth.*needs tools = "full"'):
                load_configuration(
                    overrides={
                        'policy': {'harness': harness, 'tools': 'robot_only', 'observation': 'ground_truth'}
                    }
                )
        with self.assertRaisesRegex(ValueError, 'needs tools'):
            observation_mode.check_combination({'tools': 'robot_only', 'observation': 'ground_truth'})
        self.assertEqual(observation_mode.check_combination({'tools': 'robot_only'}), 'images')
        self.assertEqual(observation_mode.check_combination({'observation': 'ground_truth'}), 'ground_truth')

    def test_any_harness_and_system_may_select_it(self):
        for harness in ('codex', 'claude'):
            for system in ('single-agent', 'adaptive', 'hierarchical', 'decentralized'):
                config = load_configuration(
                    overrides={
                        'policy': {'harness': harness, 'system': system, 'observation': 'ground_truth'}
                    }
                )
                validate_configuration(config)

    def test_a_configuration_frozen_before_the_setting_is_an_images_one(self):
        config = load_configuration()
        del config['policy']['observation']
        validate_configuration(config)
        self.assertNotIn('observation', config['policy'])  # Read as it is, never rewritten.
        self.assertEqual(observation_mode.of(config['policy']), 'images')

    def test_the_cli_takes_the_flag_wherever_it_takes_tools(self):
        parser = cli.argument_parser()
        for command in ('config', 'plan', 'prepare', 'doctor', 'preflight', 'slurm-submit'):
            extra = ['--output', 'x'] if command in ('prepare', 'slurm-submit') else []
            args = parser.parse_args([command, '--observation', 'ground_truth', '--tools', 'full', *extra])
            self.assertEqual(args.observation, 'ground_truth')
            self.assertIsNone(parser.parse_args([command, *extra]).observation)
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            parser.parse_args(['prepare', '--output', 'x', '--observation', 'depth'])

    def test_an_images_run_freezes_the_run_settings_it_always_did(self):
        images = cli._run_settings(load_configuration())
        self.assertEqual(
            sorted(images),
            [
                'observation_image_profile',
                'record_realtime_video',
                'render_device',
                'startup_protocol',
                'startup_timeout_s',
                'system',
            ],
        )
        truth = cli._run_settings(load_configuration(overrides={'policy': {'observation': 'ground_truth'}}))
        self.assertEqual(truth, {**images, 'observation': 'ground_truth'})
        # The Codex model entry, whose hash a preflight receipt pins, changes only for ground truth.
        entry = cli._catalog(load_configuration())['models']['sol']
        self.assertNotIn('observation', entry)
        entry = cli._catalog(load_configuration(overrides={'policy': {'observation': 'ground_truth'}}))
        self.assertEqual(entry['models']['sol']['observation'], 'ground_truth')

    def test_a_ground_truth_receipt_never_replaces_the_images_one(self):
        self.assertEqual(observation_mode.receipt_name('sol', 'images'), 'sol')
        self.assertEqual(observation_mode.receipt_name('sol', 'ground_truth'), 'sol.ground_truth')
        self.assertEqual(cli._receipt_name({'model': 'sol'}), 'sol')
        self.assertEqual(cli._receipt_name({'model': 'sol', 'observation': 'images'}), 'sol')
        self.assertEqual(
            cli._receipt_name({'model': 'sol', 'observation': 'ground_truth'}), 'sol.ground_truth'
        )
        self.assertEqual(cli._receipt_name({'model': 'sol', 'tools': 'robot_only'}), 'sol.robot_only')

    def test_each_mode_names_its_policy_environment(self):
        self.assertIsNone(observation_mode.environment_variant({}))
        self.assertIsNone(observation_mode.environment_variant({'observation': 'images'}))
        self.assertEqual(observation_mode.environment_variant({'observation': 'ground_truth'}), 'mujoco')


if __name__ == '__main__':
    unittest.main()
