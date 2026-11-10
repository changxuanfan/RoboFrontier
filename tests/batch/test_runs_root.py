"""Run data goes to one root, whichever checkout runs (configuration.runs_root)."""
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from robofrontier.configuration import ROOT, load_configuration, runs_root


class RunsRootTests(unittest.TestCase):
    def test_environment_then_configuration_then_the_repository(self):
        config = load_configuration()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ROBOFRONTIER_RUNS_ROOT', None)
            self.assertEqual(config['paths']['runs_root'], '')
            self.assertEqual(runs_root(config), ROOT/'runs')
            self.assertEqual(runs_root(dict(config, paths={'runs_root': '/data/rf-runs'})), Path('/data/rf-runs'))
            self.assertEqual(runs_root(dict(config, paths={'runs_root': 'elsewhere'})), ROOT/'elsewhere')
            os.environ['ROBOFRONTIER_RUNS_ROOT'] = '/srv/runs'
            self.assertEqual(runs_root(config), Path('/srv/runs'))

    def test_older_configurations_have_no_paths_section(self):
        self.assertNotIn('paths', load_configuration(overrides={'schema_version': 8}))


if __name__ == '__main__': unittest.main()
