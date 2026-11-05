"""Frozen physics settings that let a large world keep real time, off by default.

A run names a profile in its harness (`physics_profile`); a run that names none is
untouched. A profile changes results compared with full physics, so one batch must not
mix profiles. See docs/running/physics-profiles.md.
"""
import mujoco

SLEEP = int(mujoco.mjtEnableBit.mjENBL_SLEEP)
# Mosaic objects do not creep, and its motion is below real time without sleep. Elsewhere
# motion stays full physics. Tighter noslip stops the solver's slow drift of resting objects;
# Relay keeps the default because it does not help there, and settles before it may sleep.
PROFILES = {'realtime-v1': {
    'mosaic': {'sleep': 'always'},
    'transport': {'sleep': 'idle', 'noslip_tolerance': 1e-12},
    'dial': {'sleep': 'idle', 'noslip_tolerance': 1e-12},
    'relay': {'sleep': 'idle', 'settle_s': 30.},
}}
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


def attach(world, harness):
    """Apply the run's frozen profile; returns the per-step part, or None."""
    name = harness.get('physics_profile')
    if name is None: return None
    world.physics_profile_active = True
    settings = PROFILES[name][world.task['family']]
    if 'noslip_tolerance' in settings: world.model.opt.noslip_tolerance = settings['noslip_tolerance']
    if settings['sleep'] == 'always':
        world.model.opt.enableflags |= SLEEP
        return None
    return IdleSleep(world, settings.get('settle_s', 0.))
