"""Frozen physics settings that let a large world keep real time, off by default.

A run names a profile in its harness (`physics_profile`); a run that names none is
untouched. A profile changes results compared with full physics, so one batch must not
mix profiles. See docs/running/physics-profiles.md.
"""
import re

import mujoco

SLEEP = int(mujoco.mjtEnableBit.mjENBL_SLEEP)
# Mosaic objects do not creep, and its motion is below real time without sleep. Elsewhere
# motion stays full physics. Tighter noslip stops the solver's slow drift of resting objects;
# Relay keeps the default because it does not help there, and settles before it may sleep.
# A Dial grip makes about 130 contacts that module condim 6 makes expensive. Fingers therefore
# set the terms of their own contacts; modules keep rolling friction against the table, which
# they need to stop after release.
PROFILES = {'realtime-v1': {
    'mosaic': {'sleep': 'always'},
    'transport': {'sleep': 'idle', 'noslip_tolerance': 1e-12},
    'dial': {'sleep': 'idle', 'noslip_tolerance': 1e-12, 'noslip_iterations': 10, 'finger_condim': 4},
    'relay': {'sleep': 'idle', 'settle_s': 30.},
}}
# realtime-v2 (the default for new policy runs): realtime-v1's sleep, plus in every family
# elliptic friction cones, impratio 1, noslip 1e-9 with 10 iterations, finger-owned condim 4
# contacts and one contact rule for the scene (unify_contacts). Pushed, released or resting
# objects then stop and stay still, where realtime-v1 left Dial modules drifting by up to
# about 12 mm/min. See docs/running/physics-profiles.md for the measurements.
# noslip 1e-9 stops creep as well as 1e-12; at 1e-12 a Relay receiver's fingers could not
# slide along a held beam on approach and lifted it out of the carriers' grip.
# An arm's arrival, gripper and stop settle counts take one sample per simulation tick
# (poll_stability), so polling more often between two physics steps cannot shorten them.
_V2 = {'cone': 'elliptic', 'impratio': 1., 'noslip_tolerance': 1e-9, 'noslip_iterations': 10,
       'finger_condim': 4, 'unify_contacts': True, 'poll_stability': 'per-tick'}
PROFILES['realtime-v2'] = {family: {**settings, **_V2} for family, settings in PROFILES['realtime-v1'].items()}
IDLE_BEFORE_SLEEP_S = 2.


class IdleSleep:
    """Objects sleep only after every arm has been idle; any action restores full physics."""

    def __init__(self, world, settle_s=0.):
        self.world = world
        self.not_before = float(world.data.time)+settle_s
        self.last_busy = float(world.data.time)

    def before_step(self):
        model, now = self.world.model, float(self.world.data.time)
        if any(arm.job is not None for arm in self.world.arms.values()):
            self.last_busy = now
            model.opt.enableflags &= ~SLEEP
        elif now >= self.not_before and now-self.last_busy >= IDLE_BEFORE_SLEEP_S:
            model.opt.enableflags |= SLEEP


def forward_after_step(world):
    """The end-of-step forward without noslip: identical states and scores, less time.

    The next mj_step solves its own constraints, and control reads no noslip result.
    """
    options = world.model.opt
    iterations = options.noslip_iterations
    options.noslip_iterations = 0
    try: mujoco.mj_forward(world.model, world.data)
    finally: options.noslip_iterations = iterations


HOOK = re.compile(r'_(hook|weight_eye)_\d+$')
MODULE = re.compile(r'_module_(disk|stem)$')
ROBOT_JOINT = re.compile(r'[A-Z]_(joint[1-7]|finger_joint[12])')


def unify_contacts(model):
    """One contact rule for every scene part that is not a robot.

    Friction is 1, 0.005 and 0.0001. Static parts have condim 4 or more; moving parts have
    condim 4. Cylinders and spheres of loose bodies have condim 6 and rolling friction 0.1 x
    radius, so they roll a little and stop. Fingers own their contacts, so grasps do not see
    this. Boxes stay at condim 4: rolling friction between packed Mosaic stock changed how
    tiles settle and lift, and the Mosaic Oracle could no longer retract a lifted tile.
    Two values are kept because they act:
    Relay hooks and eyes (0.5 lets a hook slide into its eye), and Dial modules, whose disk
    leans on its rim and needs rolling 0.03 to stop.
    """
    robot = set()  # bodies with a robot joint, and the mounts that carry them
    for j in range(model.njnt):
        if ROBOT_JOINT.fullmatch(model.joint(j).name or ''):
            b = int(model.jnt_bodyid[j])
            while b:robot.add(b);b = int(model.body_parentid[b])
    free = {int(model.jnt_bodyid[j]) for j in range(model.njnt) if int(model.jnt_type[j]) == int(mujoco.mjtJoint.mjJNT_FREE)}
    round_types = (int(mujoco.mjtGeom.mjGEOM_CYLINDER), int(mujoco.mjtGeom.mjGEOM_SPHERE))
    for g in range(model.ngeom):
        if not model.geom_contype[g] | model.geom_conaffinity[g]:continue
        body, static, on_robot = int(model.geom_bodyid[g]), True, False
        b = body
        while b:
            if b in robot:on_robot = True
            if model.body_jntnum[b]:static = False
            b = int(model.body_parentid[b])
        name = model.geom(g).name or ''
        if on_robot or HOOK.search(name):continue
        model.geom_friction[g] = (1., .005, .0001)
        if MODULE.search(name):
            model.geom_condim[g] = 6;model.geom_friction[g, 2] = .03
        elif static:
            model.geom_condim[g] = max(int(model.geom_condim[g]), 4)
        elif body in free and int(model.geom_type[g]) in round_types:
            model.geom_condim[g] = 6;model.geom_friction[g, 2] = .1*float(model.geom_size[g, 0])
        else:
            model.geom_condim[g] = 4


def attach(world, harness):
    """Apply the run's frozen profile; returns the per-step part, or None."""
    name = harness.get('physics_profile')
    if name is None: return None
    world.physics_profile_active = True
    settings = PROFILES[name][world.task['family']]
    if settings.get('cone') == 'elliptic': world.model.opt.cone = mujoco.mjtCone.mjCONE_ELLIPTIC
    if 'impratio' in settings: world.model.opt.impratio = settings['impratio']
    if 'noslip_tolerance' in settings: world.model.opt.noslip_tolerance = settings['noslip_tolerance']
    if 'noslip_iterations' in settings: world.model.opt.noslip_iterations = settings['noslip_iterations']
    if 'finger_condim' in settings:
        fingers = [g for g in range(world.model.ngeom)
                   if 'finger' in (world.model.body(int(world.model.geom_bodyid[g])).name or '')]
        world.model.geom_priority[fingers] = 1
        world.model.geom_condim[fingers] = settings['finger_condim']
    if settings.get('unify_contacts'): unify_contacts(world.model)
    if 'poll_stability' in settings:
        for arm in world.arms.values(): arm.poll_stability = settings['poll_stability']
    if settings['sleep'] == 'always':
        world.model.opt.enableflags |= SLEEP
        return None
    return IdleSleep(world, settings.get('settle_s', 0.))
