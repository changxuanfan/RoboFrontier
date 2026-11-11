"""Which tools a policy role has in a run.

'full' is every earlier run: the engine's own file and shell tools beside the bound robot
tool. 'robot_only' leaves the robot tool alone: no shell, no code execution, no file
tools. What a role used files for stays available through the robot tool instead
(public_files.py, run_skills.py). The mode is frozen in the run's harness.json; a harness
without the field is a full run.
"""
import json
from pathlib import Path
import re

FULL, ROBOT_ONLY = 'full', 'robot_only'
MODES = (FULL, ROBOT_ONLY)
# Robot operations that exist only in a robot_only run.
ROBOT_ONLY_OPS = ('public_file', 'skills')

_BLOCK = re.compile(r'^<!-- tools:(full|robot_only) -->\n(.*?)^<!-- /tools -->\n', re.M | re.S)


def of(config):
    """The mode of a harness configuration."""
    mode = (config or {}).get('tool_mode', FULL)
    if mode not in MODES:
        raise ValueError('Unknown tool mode: ' + str(mode))
    return mode


def of_run(run):
    """The frozen mode of a prepared run."""
    path = Path(run)/'private/inputs/harness.json'
    return of(json.loads(path.read_text())) if path.is_file() else FULL


def render(text, mode):
    """A prompt template for one mode.

    A passage that depends on the tools sits between `<!-- tools:<mode> -->` and
    `<!-- /tools -->`, each alone on a line; only the passages of `mode` are kept and the
    marker lines are removed. Text outside the markers is shared by both modes.
    """
    if mode not in MODES:
        raise ValueError('Unknown tool mode: ' + str(mode))
    rendered = _BLOCK.sub(lambda match: match.group(2) if match.group(1) == mode else '', text)
    if '<!-- tools:' in rendered or '<!-- /tools -->' in rendered:
        raise ValueError('Unbalanced tool-mode markers in a prompt template')
    return rendered
