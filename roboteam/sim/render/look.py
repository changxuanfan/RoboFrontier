"""How observation images look.

A run's settings name one look as `observation_look`:

direct  MuJoCo lights the scene's colours and textures as they are and the result is written
        unchanged. This is the default.
linear  The renderer works on a copy of the model whose colours and textures are converted to
        linear light, with enough fill light that a white object comes out white, and the
        finished image gets one display transform. The pictures are brighter and less heavy.
        The work per image is one table lookup; the conversion is done once per model.
"""
import copy

import numpy as np

DIRECT, LINEAR = 'direct', 'linear'
DEFAULT_LOOK = DIRECT

GAMMA = 2.2
EXPOSURE = 1.12
SHOULDER = .25  # soft roll-off towards white: x*(1+s)/(1+s*x)
AMBIENT = .30   # headlight ambient: fill light that reaches every surface
HEADLIGHT = .16  # headlight diffuse: a weak light from the camera
UNSET_RGBA = (.5, .5, .5, 1.)  # a geom with this colour takes its colour from its material

_steps = np.arange(256) / 255.
TO_LINEAR = np.round(_steps ** GAMMA * 255).astype(np.uint8)
_lit = _steps * EXPOSURE
TO_DISPLAY = np.round(np.clip(_lit * (1 + SHOULDER) / (1 + SHOULDER * _lit), 0, 1) ** (1 / GAMMA) * 255).astype(np.uint8)


def _own_colour(geom_rgba):
    return ~np.all(np.isclose(geom_rgba, UNSET_RGBA), axis=1)


def look_of(config):
    """The look frozen run settings name; settings without the field draw directly."""
    look = config.get('observation_look', DEFAULT_LOOK)
    if look not in (DIRECT, LINEAR):
        raise ValueError('Unknown observation look: ' + str(look))
    return look


def set_colours(visual, geom_rgba, look=DEFAULT_LOOK):
    """Give the copy the scene's current geom colours, in linear light for the linear look."""
    visual.geom_rgba[:] = geom_rgba
    if look == LINEAR:
        own = _own_colour(geom_rgba)
        visual.geom_rgba[own, :3] = geom_rgba[own, :3] ** GAMMA


def look_model(model, look=DEFAULT_LOOK):
    """A copy of `model` to draw observations from. `model` itself is not changed."""
    visual = copy.copy(model)
    if look == DIRECT:
        return visual
    set_colours(visual, model.geom_rgba.copy(), look)
    visual.mat_rgba[:, :3] = model.mat_rgba[:, :3] ** GAMMA
    pixels = visual.tex_data if hasattr(visual, 'tex_data') else visual.tex_rgb
    channels = getattr(visual, 'tex_nchannel', None)
    for index in range(visual.ntex):
        count = 3 if channels is None else int(channels[index])
        start = visual.tex_adr[index]
        block = pixels[start:start + visual.tex_height[index] * visual.tex_width[index] * count].reshape(-1, count)
        block[:, :min(count, 3)] = TO_LINEAR[block[:, :min(count, 3)]]  # alpha stays as it is
    visual.vis.headlight.ambient[:] = AMBIENT
    visual.vis.headlight.diffuse[:] = HEADLIGHT
    return visual


def display(rgb, look=DEFAULT_LOOK):
    """The renderer's 8-bit pixels as display pixels: unchanged, or transformed from linear light."""
    return TO_DISPLAY[rgb] if look == LINEAR else rgb
