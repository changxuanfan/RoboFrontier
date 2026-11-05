# Physics profiles

A harness may set `physics_profile`; `configs/harnesses/policy.json` sets
`realtime-v1`. A run that sets none is untouched, and a run freezes its choice with its
other inputs. A profile changes results compared with
full physics, so results of different profiles are not comparable and one batch must
not mix them.

## `realtime-v1`

| Family | Objects sleep | `noslip_tolerance` |
|---|---|---|
| Mosaic | Always | Default |
| Transport | When every arm has been idle for 2 s | 1e-12 |
| Dial | When every arm has been idle for 2 s | 1e-12 |
| Relay | Same, and only 30 s after the world starts | Default |

- Any action restores full physics before its first step.
- The extra forward at the end of each 20 ms step skips noslip. This does not change
  states or scores and saves about 2-7% of the time.
- Forces and contact wake a sleeping object on the same step.
- The default `noslip_tolerance` of 1e-6 lets resting objects drift at 1-2 mm per
  simulated minute with no rotation. This is solver error, so a sleeping object does
  not follow it.
- MuJoCo omits contacts between sleeping bodies from `data.contact`. Scoring that asks
  what supports an object uses `Monitor.scene_contacts`, which recomputes them.

The main loop still follows the wall clock, so a world never runs faster than real
time. Rendering reads recorded poses and does not depend on a profile.
