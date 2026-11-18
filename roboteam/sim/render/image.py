"""Frozen per-run policy observation formats."""

from copy import deepcopy

DEFAULT_PROFILE = 'jpeg_1280x800_q90'
# The low-resolution condition: the default camera at one tenth of its resolution on each side.
# Rendered as the default, then every 10 x 10 block of pixels averaged into one, encoded at
# quality 95. Deterministic, no noise.
LOW_RESOLUTION_PROFILE = 'jpeg_128x80_q95'
PROFILES = {
    DEFAULT_PROFILE: {'width': 1280, 'height': 800, 'format': 'JPEG', 'quality': 90, 'extension': '.jpg'},
    LOW_RESOLUTION_PROFILE: {
        'width': 128,
        'height': 80,
        'format': 'JPEG',
        'quality': 95,
        'extension': '.jpg',
        'render_size': [1280, 800],
    },
}


def observation_profile(config):
    name = config.get('observation_image_profile')
    if not isinstance(name, str) or name not in PROFILES:
        raise ValueError('Unknown observation image profile: ' + str(name))
    return deepcopy(PROFILES[name])


def render_size(profile):
    """The size a camera is drawn at: the image size, unless the profile reduces it afterwards."""
    width, height = profile.get('render_size', (profile['width'], profile['height']))
    return width, height


def reduced_size(profile):
    """The size a rendered frame is reduced to before encoding, or None when it is encoded as drawn."""
    return [profile['width'], profile['height']] if 'render_size' in profile else None


def save_observation(Image, rgb, path, format, save_options, output_size=None):
    """Encode one rendered frame (bottom row first, as OpenGL reads it) as an observation file.

    Every live camera image a policy receives is written here, by the world or its render
    worker. Without `output_size` the pixels are encoded as rendered; with it, the frame is
    first reduced to that size by averaging."""
    image = Image.fromarray(rgb[::-1])
    if output_size:
        image = image.resize(tuple(output_size), Image.BOX)
    image.save(path, format=format, **save_options)
