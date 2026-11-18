"""Which tools a policy role has in a run.

'full' (the default): the harness's own file and shell tools beside the bound robot
tool. 'robot_only' leaves the robot tool alone: no shell, no code execution, no file
tools. What a role used files for stays available through the robot tool instead
(public_files.py, run_skills.py). The mode is frozen in the run's run.json; a harness
without the field is a full run.
"""

import json
import re
from pathlib import Path

FULL, ROBOT_ONLY = 'full', 'robot_only'
MODES = (FULL, ROBOT_ONLY)
# Robot operations that exist only in a robot_only run.
ROBOT_ONLY_OPS = ('public_file', 'skills')


def render_marked(text, setting, modes, mode):
    """A prompt template for one value of a run setting (`tools` here, `observation` in
    observation_mode.py).

    A passage that depends on the setting sits between `<!-- <setting>:<mode> -->` and
    `<!-- /<setting> -->`, each alone on a line; only the passages of `mode` are kept and the
    marker lines are removed. Text outside the markers is shared by every mode.
    """
    if mode not in modes:
        raise ValueError('Unknown %s mode: %s' % (setting, mode))
    block = re.compile(
        r'^<!-- %s:(%s) -->\n(.*?)^<!-- /%s -->\n' % (setting, '|'.join(modes), setting), re.M | re.S
    )
    rendered = block.sub(lambda match: match.group(2) if match.group(1) == mode else '', text)
    if '<!-- %s:' % setting in rendered or '<!-- /%s -->' % setting in rendered:
        raise ValueError('Unbalanced %s-mode markers in a prompt template' % setting)
    return rendered


def of(config):
    """The mode a run's settings name."""
    mode = (config or {}).get('tools', FULL)
    if mode not in MODES:
        raise ValueError('Unknown tool mode: ' + str(mode))
    return mode


def receipt_name(model_entry_name, mode):
    """The folder of a model's Codex preflight receipt. A robot_only launch differs from the
    full one, so it has a receipt of its own and never replaces the full run's."""
    return model_entry_name + ('.robot_only' if mode == ROBOT_ONLY else '')


def of_run(run):
    """The frozen mode of a prepared run."""
    path = Path(run) / 'private/inputs/run.json'
    return of(json.loads(path.read_text())) if path.is_file() else FULL


def render(text, mode):
    """A prompt template for one tool mode: the passages between `<!-- tools:<mode> -->` and
    `<!-- /tools -->` (render_marked)."""
    if mode not in MODES:
        raise ValueError('Unknown tool mode: ' + str(mode))
    return render_marked(text, 'tools', MODES, mode)
