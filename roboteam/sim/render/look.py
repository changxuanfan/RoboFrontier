"""How observation images look, and which hall shapes each image draws.

The renderer works on a copy of the world's model. In the copy, colours and textures are
converted to linear light, a weak ambient and camera light fill in what the hall's lights do
not reach, and the finished image gets one display transform. The values were fitted once
against an offline (Cycles) picture of the same frame.

In a world with the hall (`roboteam.sim.hall.world`), the hall's key light casts the shadows,
the task scene's own light and floor are not drawn, and each image draws only the hall shapes
that can show in it: those that touch the camera's view and those whose shadow can fall into it.
The image is the one that drawing every shape gives (tests/sim/hall/test_view.py).
"""

import copy

import mujoco
import numpy as np

from roboteam.sim.hall.flat import HALL_GROUP
from roboteam.sim.hall.world import HALL_BODY, task_geoms

GAMMA = 2.2
EXPOSURE = 1.12
SHOULDER = 0.25  # soft roll-off towards white: x*(1+s)/(1+s*x)
AMBIENT = 0.30  # headlight ambient: fill light that reaches every surface
HEADLIGHT = 0.16  # headlight diffuse: a weak light from the camera
HEADLIGHT_SPECULAR = 0.02
UNSET_RGBA = (0.5, 0.5, 0.5, 1.0)  # a geom with this colour takes its colour from its material
SHADOW_REACH = 1.0  # the key light's shadows cover this many scene extents around the desk
SHADOW_MAP = 4096  # 1 to 2 mm of desk per shadow texel
KEY_DISTANCE_M = 9.0  # the key light stands this far from the desk, against its direction
HIDDEN_GROUP = 5  # shapes an image does not draw
MAX_GEOM = 40000

_steps = np.arange(256) / 255.0
TO_LINEAR = np.round(_steps**GAMMA * 255).astype(np.uint8)
_lit = _steps * EXPOSURE
TO_DISPLAY = np.round(
    np.clip(_lit * (1 + SHOULDER) / (1 + SHOULDER * _lit), 0, 1) ** (1 / GAMMA) * 255
).astype(np.uint8)


def _own_colour(geom_rgba):
    return ~np.all(np.isclose(geom_rgba, UNSET_RGBA), axis=1)


def set_colours(visual, geom_rgba):
    """Give the copy the task's current geom colours, in linear light. Hall colours never change."""
    count = len(geom_rgba)
    visual.geom_rgba[:count] = geom_rgba
    own = _own_colour(geom_rgba)
    visual.geom_rgba[:count][own, :3] = geom_rgba[own, :3] ** GAMMA


def look_model(model):
    """A copy of `model` to draw observations from. `model` itself is not changed."""
    visual = copy.copy(model)
    own = _own_colour(model.geom_rgba)
    visual.geom_rgba[own, :3] = model.geom_rgba[own, :3] ** GAMMA
    visual.mat_rgba[:, :3] = model.mat_rgba[:, :3] ** GAMMA
    pixels = visual.tex_data if hasattr(visual, 'tex_data') else visual.tex_rgb
    channels = getattr(visual, 'tex_nchannel', None)
    for index in range(visual.ntex):
        count = 3 if channels is None else int(channels[index])
        start = visual.tex_adr[index]
        block = pixels[start : start + visual.tex_height[index] * visual.tex_width[index] * count].reshape(
            -1, count
        )
        block[:, : min(count, 3)] = TO_LINEAR[block[:, : min(count, 3)]]  # alpha stays as it is
    visual.vis.headlight.ambient[:] = AMBIENT
    visual.vis.headlight.diffuse[:] = HEADLIGHT
    visual.vis.headlight.specular[:] = HEADLIGHT_SPECULAR
    hall = mujoco.mj_name2id(visual, mujoco.mjtObj.mjOBJ_BODY, HALL_BODY)
    if hall >= 0:
        # The hall lights the scene and is the floor: the task scene's own light and floor are not drawn.
        rotation = np.zeros(9)
        mujoco.mju_quat2Mat(rotation, visual.body_quat[hall])
        rotation = rotation.reshape(3, 3)
        for light in range(visual.nlight):
            if int(visual.light_bodyid[light]) != hall:
                visual.light_active[light] = 0
            elif visual.light_castshadow[light]:
                # MuJoCo draws a directional light's shadows from its position: above the desk.
                direction = rotation @ visual.light_dir[light]
                position = visual.stat.center - KEY_DISTANCE_M * direction / np.linalg.norm(direction)
                visual.light_pos[light] = rotation.T @ (position - visual.body_pos[hall])
        for geom in range(task_geoms(visual)):
            if int(visual.geom_bodyid[geom]) == 0 and visual.geom_type[geom] == mujoco.mjtGeom.mjGEOM_PLANE:
                visual.geom_group[geom] = HIDDEN_GROUP
        visual.vis.map.shadowclip = SHADOW_REACH
        visual.vis.quality.shadowsize = SHADOW_MAP
    return visual


def view_options():
    """What observation images draw: visual shapes and the hall, not collision shapes."""
    options = mujoco.MjvOption()
    options.geomgroup[3] = 0
    options.geomgroup[HALL_GROUP] = 1
    options.geomgroup[HIDDEN_GROUP] = 0
    return options


class HallView:
    """Chooses, for one camera at a time, the hall shapes its image draws.

    Hall shapes never move, so their bounding spheres and the reach of their shadows are
    computed once. `select` then tests them against the camera's view."""

    def __init__(self, visual):
        self.first = task_geoms(visual)
        self.count = visual.ngeom - self.first
        if not self.count:
            return
        data = mujoco.MjData(visual)
        mujoco.mj_kinematics(visual, data)
        mujoco.mj_camlight(visual, data)
        self.centre = data.geom_xpos[self.first :].copy()
        bound = visual.geom_rbound[self.first :]
        self.always = bound <= 0  # planes have no bounding sphere
        self.radius = bound * 1.02 + 0.01  # a margin for the renderer's own rounding
        hall = visual.body(HALL_BODY).id
        keys = [
            light
            for light in range(visual.nlight)
            if int(visual.light_bodyid[light]) == hall and visual.light_castshadow[light]
        ]
        # A shape shades the points behind it along the light, down to the floor.
        self.shadow_end = self.centre.copy()
        if keys:
            direction = data.light_xdir[keys[0]] / np.linalg.norm(data.light_xdir[keys[0]])
            if direction[2] < -1e-6:
                reach = np.clip(self.centre[:, 2] + self.radius, 0, None) / -direction[2]
                self.shadow_end = self.centre + reach[:, None] * direction

    def select(self, visual, data, camera_id, width, height):
        """Set the hall shapes of `visual` drawn for this camera. `data` holds the capture's poses."""
        if not self.count:
            return
        groups = visual.geom_group[self.first :]
        if visual.cam_projection[camera_id] or np.any(visual.cam_sensorsize[camera_id]):
            groups[:] = HALL_GROUP
            return
        rotation = data.cam_xmat[camera_id].reshape(3, 3)
        eye = data.cam_xpos[camera_id]
        up = np.tan(np.radians(float(visual.cam_fovy[camera_id])) / 2)
        side = up * width / height
        # Inward normals of the four sides of the view, in the camera's frame (it looks along -z).
        planes = np.array([[-1, 0, -side], [1, 0, -side], [0, -1, -up], [0, 1, -up]], float)
        planes /= np.linalg.norm(planes, axis=1)[:, None]
        normals = planes @ rotation.T
        near = (self.centre - eye) @ normals.T
        far = (self.shadow_end - eye) @ normals.T
        outside = np.any(np.maximum(near, far) < -self.radius[:, None], axis=1)
        groups[:] = np.where(outside & ~self.always, HIDDEN_GROUP, HALL_GROUP)

    def everything(self, visual):
        if self.count:
            visual.geom_group[self.first :] = HALL_GROUP


def display(rgb):
    """The renderer's 8-bit pixels, which are linear light, as display pixels."""
    return TO_DISPLAY[rgb]
