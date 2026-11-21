"""What a policy role observes the task with in a run.

'images' (the default): camera images through the robot tool, as every ordinary run.
'ground_truth' gives the role the simulator's own state instead of camera images:
`observe` returns robot feedback without images, the robot tool's `state` operation
returns object poses, joint state and the evaluator's progress (ground_truth.py), the
run's public inputs carry the full task definition and the task scene
(tasks/ground_truth.py), and the role's Python has a simulator (the `mujoco` variant of
the policy environment). The Dial code stays private in both modes. The mode is frozen
in the run's run.json; a run without the field is an images run.
"""

import json
from pathlib import Path

from roboteam.tasks import tools_mode

IMAGES, GROUND_TRUTH = 'images', 'ground_truth'
MODES = (IMAGES, GROUND_TRUTH)
# Robot operations that exist only in a ground_truth run.
GROUND_TRUTH_OPS = ('state',)
# Robot operations a ground_truth run refuses: they return images.
IMAGE_OPS = ('public_image',)
# The policy environment variant each mode's shells use (sandbox/policy_env.py).
ENVIRONMENT_VARIANT = {IMAGES: None, GROUND_TRUTH: 'mujoco'}


def of(config):
    """The mode a run's settings name."""
    mode = (config or {}).get('observation', IMAGES)
    if mode not in MODES:
        raise ValueError('Unknown observation mode: ' + str(mode))
    return mode


def of_run(run):
    """The frozen mode of a prepared run."""
    path = Path(run) / 'private/inputs/run.json'
    return of(json.loads(path.read_text())) if path.is_file() else IMAGES


def check_combination(config):
    """Refuse settings that cannot go together; returns the observation mode."""
    mode = of(config)
    if mode == GROUND_TRUTH and tools_mode.of(config) == tools_mode.ROBOT_ONLY:
        raise ValueError(
            'observation = "ground_truth" needs tools = "full": the role uses its code tools to '
            'read the ground-truth files and run the simulator'
        )
    return mode


def receipt_name(name, mode):
    """The folder of a Codex preflight receipt, after tools_mode.receipt_name. A ground_truth
    launch differs from the images one, so it has a receipt of its own."""
    return name + ('.ground_truth' if mode == GROUND_TRUTH else '')


def environment_variant(config):
    """The policy environment variant a run with these settings uses."""
    return ENVIRONMENT_VARIANT[of(config)]


def render(text, mode):
    """A prompt template for one observation mode: the passages between
    `<!-- observation:<mode> -->` and `<!-- /observation -->` (tools_mode.render_marked)."""
    if mode not in MODES:
        raise ValueError('Unknown observation mode: ' + str(mode))
    return tools_mode.render_marked(text, 'observation', MODES, mode)
