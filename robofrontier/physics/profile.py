"""The physics settings a scene file cannot hold, applied when a policy world starts.

Contacts and solver options are written in each released scene.xml (scripts/build_release.py,
docs/physics.md). What stays here is how a world steps:

- Sleep. Mosaic objects never creep, and Mosaic's large scenes stay below real time
  without sleep, so its objects may always sleep. In the other families objects sleep
  only after every arm has been idle for two seconds; any action wakes them.
- Relay settles for 30 s before anything may sleep, so its hanging weights come to rest.
- After each 20 ms control step the world runs a forward pass without noslip
  (forward_after_step): the next step solves its own constraints, so states and scores
  are identical and the step takes less time.
"""
import mujoco

SLEEP = int(mujoco.mjtEnableBit.mjENBL_SLEEP)
FAMILIES = {
    'mosaic': {'sleep': 'always'},
    'transport': {'sleep': 'idle'},
    'dial': {'sleep': 'idle'},
    'relay': {'sleep': 'idle', 'settle_s': 30.},
}
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
    """The end-of-step forward without noslip: identical states and scores, less time."""
    options = world.model.opt
    iterations = options.noslip_iterations
    options.noslip_iterations = 0
    try: mujoco.mj_forward(world.model, world.data)
    finally: options.noslip_iterations = iterations


def settings(family):
    return dict(FAMILIES[family])


def attach(world):
    """Apply the family's step settings; returns the per-step part, or None."""
    family = settings(world.task['family'])
    if family['sleep'] == 'always':
        world.model.opt.enableflags |= SLEEP
        return None
    return IdleSleep(world, family.get('settle_s', 0.))
