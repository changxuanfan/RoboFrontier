"""The hierarchical team harness for tests of standing roles.

The repository harness (roboteam/runtime/run/defaults.json) is adaptive, with one Controller. Tests of a
Controller with one Worker per arm name the hierarchical system here.
"""

import json
import tempfile
from pathlib import Path

from roboteam.runtime.run import setup
from roboteam.tasks.config import load_run_settings as _load_run_settings
from roboteam.tasks.config import startup_protocol


def load_run_settings():
    """The repository harness with the hierarchical system."""
    config = _load_run_settings()
    config.update(system='hierarchical', startup_protocol=startup_protocol('hierarchical'))
    return config


def prepare_run(directory, task_path=None, run_settings_path=None, private_puzzle_path=None):
    """runtime.setup.prepare_run, with the hierarchical harness when none is given."""
    if run_settings_path is not None:
        return setup.prepare_run(directory, task_path, run_settings_path, private_puzzle_path)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / 'run.json'
        path.write_text(json.dumps(load_run_settings()))
        return setup.prepare_run(directory, task_path, path, private_puzzle_path)
