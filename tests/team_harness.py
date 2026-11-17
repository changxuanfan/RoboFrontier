"""The hierarchical team harness for tests of standing roles.

The repository harness (configs/harness.json) is adaptive, with one Controller. Tests of a
Controller with one Worker per arm name the hierarchical topology here.
"""
import json
from pathlib import Path
import tempfile

from roboteam.runtime import setup
from roboteam.tasks.config import load_harness as _load_harness, startup_protocol


def load_harness():
    """The repository harness with the hierarchical topology."""
    config = _load_harness()
    config.update(topology='hierarchical', startup_protocol=startup_protocol('hierarchical'))
    return config


def prepare_run(directory, task_path=None, harness_path=None, private_puzzle_path=None):
    """runtime.setup.prepare_run, with the hierarchical harness when none is given."""
    if harness_path is not None:
        return setup.prepare_run(directory, task_path, harness_path, private_puzzle_path)
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder)/'harness.json'
        path.write_text(json.dumps(load_harness()))
        return setup.prepare_run(directory, task_path, path, private_puzzle_path)
