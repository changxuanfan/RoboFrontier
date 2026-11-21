"""Run data goes to one root, whichever checkout runs (configuration.runs_root)."""

import os
import unittest
from pathlib import Path
from unittest.mock import patch

from roboteam.configuration import ROOT, load_configuration, runs_root


class RunsRootTests(unittest.TestCase):
    def test_environment_then_configuration_then_the_repository(self):
        config = load_configuration()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop('ROBOTEAM_RUNS_ROOT', None)
            self.assertEqual(config['paths']['runs_root'], '')
            self.assertEqual(runs_root(config), ROOT / 'runs')
            self.assertEqual(
                runs_root(dict(config, paths={'runs_root': '/data/roboteam-runs'})),
                Path('/data/roboteam-runs'),
            )
            self.assertEqual(runs_root(dict(config, paths={'runs_root': 'elsewhere'})), ROOT / 'elsewhere')
            os.environ['ROBOTEAM_RUNS_ROOT'] = '/srv/runs'
            self.assertEqual(runs_root(config), Path('/srv/runs'))


if __name__ == '__main__':
    unittest.main()
