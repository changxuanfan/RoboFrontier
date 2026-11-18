"""A run's world: the task scene with the hall around it.

The desk a run simulates stays at the origin of its own scene, so task coordinates, cameras
and the evaluator are unchanged. The built hall, without that desk, is attached as one still
body named `hall`, placed where the desk stands in the hall. It comes after everything the
task scene defines, so every body, joint and geom of the task keeps its index, and it takes
no part in collisions, so the motion is the same with and without it.
"""

import copy
import json
import math
from pathlib import Path

import mujoco

from roboteam.sim.hall.flat import BUILT

HALL_BODY = 'hall'
HALL_PREFIX = 'hall/'
MEMORY_BYTES = 1 << 30


def hall_facts(built=BUILT):
    path = Path(built) / 'hall.json'
    return json.loads(path.read_text()) if path.exists() else None


def check_hall(built=BUILT):
    """The built hall is the one this checkout pins; returns its identity for a run's records."""
    from roboteam.io import ROOT, file_sha256

    built = Path(built)
    pinned = json.loads((ROOT / 'benchmark/assets.json').read_text()).get('hall_sha256')
    facts = hall_facts(built)
    if file_sha256(built / 'hall.json') != pinned or file_sha256(built / 'hall.xml') != facts['hall_sha256']:
        raise ValueError('The built hall is not the pinned one; run `roboteam bootstrap`')
    return {'hall_json_sha256': pinned, 'hall_sha256': facts['hall_sha256']}


def has_desk(case_id, built=BUILT):
    facts = hall_facts(built)
    return bool(facts) and case_id in facts['desks']


def load_world(scene_xml, case_id, built=BUILT):
    """The task scene `scene_xml` (text, asset paths absolute) inside the hall, at the desk of `case_id`.

    Returns the world's model and the model of the task scene alone."""
    built = Path(built)
    desk = hall_facts(built)['desks'][case_id]
    plain = mujoco.MjModel.from_xml_string(scene_xml)
    task = mujoco.MjSpec.from_string(scene_xml)
    # The desk this run simulates is left out. hall.xml holds one shape per line (flat.py writes
    # it), and dropping lines is far quicker than removing shapes from a parsed scene of this size.
    own = 'name="' + case_id + '__'
    text = '\n'.join(line for line in (built / 'hall.xml').read_text().split('\n') if own not in line)
    hall = mujoco.MjSpec.from_string(text)
    hall.modelfiledir = str(built)
    # The hall is placed by the inverse of the desk's place in the hall.
    x, y, z = desk['translation_m']
    yaw = desk['yaw_rad']
    cos, sin = math.cos(-yaw), math.sin(-yaw)
    body = task.worldbody.add_body(
        name=HALL_BODY,
        pos=[-(cos * x - sin * y), -(sin * x + cos * y), -z],
        quat=[math.cos(-yaw / 2), 0, 0, math.sin(-yaw / 2)],
    )
    task.attach(hall, prefix=HALL_PREFIX, frame=body.add_frame())
    task.memory = max(int(task.memory), MEMORY_BYTES)
    model = task.compile()
    # What the task scene defined is untouched and comes first.
    for count in ('nq', 'nv', 'nu', 'njnt', 'ncam', 'nkey', 'nsite'):
        if getattr(model, count) != getattr(plain, count):
            raise ValueError('The hall changed the task scene: ' + count)
    if model.nbody != plain.nbody + 1 or model.body(HALL_BODY).id != plain.nbody:
        raise ValueError('The hall is not the last body of the world')
    if int(model.body_geomadr[plain.nbody]) != plain.ngeom:
        raise ValueError('The hall shapes do not follow the task shapes')
    # Camera clipping and shadow range follow the task scene, not the size of the hall.
    model.stat.extent = plain.stat.extent
    model.stat.center[:] = plain.stat.center
    return model, plain


def task_geoms(model):
    """How many geoms the task scene itself has; hall geoms follow them."""
    hall = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, HALL_BODY)
    return int(model.ngeom if hall < 0 else model.body_geomadr[hall])


# What a running world changes in its model: actuator settings, step options and geom colours.
_GEOM_FIELDS = ('geom_rgba', 'geom_pos', 'geom_quat')


def task_copy(model, plain):
    """A copy of the task scene alone that carries the world's current settings.

    Planning ahead (the motion check) works on a copy of the model. The hall has no part in
    it, and copying the hall with every check would take tens of milliseconds."""
    if plain is None:
        return copy.copy(model)
    twin = copy.copy(plain)
    for name in dir(twin):
        if name.startswith('actuator_'):
            ours = getattr(twin, name)
            if hasattr(ours, 'shape') and ours.flags.writeable:
                ours[...] = getattr(model, name)
    for name in _GEOM_FIELDS:
        getattr(twin, name)[...] = getattr(model, name)[: twin.ngeom]
    for name in dir(twin.opt):
        if name.startswith('_'):
            continue
        value = getattr(model.opt, name)
        if hasattr(value, 'shape'):
            getattr(twin.opt, name)[...] = value
        elif isinstance(value, (int, float)):
            setattr(twin.opt, name, value)
    return twin
