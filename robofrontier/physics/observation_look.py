"""How observation images look.

Colours and textures in a scene are display values. MuJoCo lights them as they are and writes
the result unchanged, which gives dark, heavy pictures. Here the renderer works on a copy of
the model whose colours and textures are converted to linear light, with enough fill light
that a white object comes out white, and the finished image gets one display transform.
The work per image is one table lookup; the conversion is done once per model.
"""
import copy

import numpy as np

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


def set_colours(visual, geom_rgba):
    """Give the copy the scene's current geom colours, in linear light."""
    visual.geom_rgba[:] = geom_rgba
    own = _own_colour(geom_rgba)
    visual.geom_rgba[own, :3] = geom_rgba[own, :3] ** GAMMA


def look_model(model):
    """A copy of `model` to draw observations from. `model` itself is not changed."""
    visual = copy.copy(model)
    set_colours(visual, model.geom_rgba.copy())
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


def display(rgb):
    """Linear 8-bit pixels from the renderer as display pixels."""
    return TO_DISPLAY[rgb]
