"""What physics a world actually ran with, written once when it starts.

The record lists the solver options, every distinct set of contact parameters with how
many collision geoms carry it (and a few of their names), and the family's step settings.
Its hash identifies the physics independently of the scene layout, so two runs can be
compared by one value.
"""
import hashlib
import json
from collections import defaultdict

import mujoco

SCHEMA = 'robofrontier.effective-physics.v1'
OPTIONS = ('timestep', 'impratio', 'tolerance', 'iterations', 'ls_iterations', 'noslip_iterations',
           'noslip_tolerance', 'ccd_iterations', 'o_margin')


def describe(model, family):
    from ..physics.profile import settings
    options = {name: float(getattr(model.opt, name)) for name in OPTIONS}
    options.update(cone=mujoco.mjtCone(model.opt.cone).name, solver=mujoco.mjtSolver(model.opt.solver).name,
                   integrator=mujoco.mjtIntegrator(model.opt.integrator).name,
                   gravity=[float(v) for v in model.opt.gravity])
    groups = defaultdict(list)
    for g in range(model.ngeom):
        if not model.geom_contype[g] | model.geom_conaffinity[g]: continue
        key = (tuple(round(float(v), 9) for v in model.geom_friction[g]), int(model.geom_condim[g]),
               int(model.geom_priority[g]), tuple(round(float(v), 9) for v in model.geom_solref[g]),
               tuple(round(float(v), 9) for v in model.geom_solimp[g]))
        groups[key].append(model.geom(g).name or f'#{g}')
    contacts = [dict(friction=list(key[0]), condim=key[1], priority=key[2], solref=list(key[3]), solimp=list(key[4]),
                     geoms=len(names), examples=sorted(names)[:3])
                for key, names in sorted(groups.items(), key=lambda item: -len(item[1]))]
    physics = dict(options=options, contacts=[{k: v for k, v in c.items() if k not in ('geoms', 'examples')} for c in contacts],
                   step=settings(family), mujoco=mujoco.__version__)
    digest = hashlib.sha256(json.dumps(physics, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    return dict(schema=SCHEMA, sha256=digest, family=family, mujoco=mujoco.__version__, options=options,
                contacts=contacts, step=settings(family))


def write(path, model, family):
    from ..io import write_json
    record = describe(model, family)
    write_json(path, record)
    return record
