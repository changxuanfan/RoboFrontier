# Time: the 24-hour limit and pauses

Every run gets 24 hours and is scored at that cutoff, or earlier when the team's `finish` is
accepted. The 24 hours are **active time**: the time the trial is running. This page says how
active time is counted, what stops a run that is held forever, and when a run pauses in place
and resumes by itself.

A pause is not a [continuation](continuation.md). During a pause the same world waits; a
continuation builds a new world for the same trial.

| Event | What the run does | Counts as active time |
| --- | --- | --- |
| The model API cannot be reached | [Pauses in place](#network-outage-pause), resumes when it answers | No |
| A subscription's usage limit is used up | [Pauses in place](#usage-limit-pause) until the limit resets | No |
| A short rate limit or an overloaded provider | The host [retries the turn](#capacity-retries); the world keeps running | Yes |
| The host sleeps or freezes | The gap is left out when the host wakes | No |
| The run stops and continues in a new segment | The time between the segments is left out | No |

The limit is `batch.task_wall_limit_s` (86,400 s). A prepared run freezes it as
`run_protocol.total_wall_limit_s` in its private task. The public task states no limit, and the
rules ask the agents to plan as if time were unlimited.

## Active time

Every policy run counts active time (`run_protocol.clock` is `active_time_v1`). The world owner,
the process that steps the physics, adds it up tick by tick (`BudgetGuard` in
`roboteam/runtime/time/clock.py`). An interval counts only while the run's lifecycle is
`running`, physics is `running` and dispatch is not paused (`clock.counting`). It does not
count:

- a pause by the experiment manager, the cutoff itself, or a network review hold;
- a network-outage pause, a usage-limit pause, or a Slurm route pause (below);
- a stall: when the owner's previous tick is more than 5 s ago (`clock.STALL_S`), the gap adds
  nothing and is recorded as an `ACTIVE_TIME_STALL` event. Ticks normally come every few
  milliseconds, so this catches a frozen or suspended host and a machine that slept;
- the time between segments, when no owner runs.

The total is saved as `active_s` in the runtime database at least every second, at the cutoff
and when the owner closes. A continued segment or a restarted owner starts from the saved
value. It never recomputes the deadline from wall time, so a sleep or a crash is never counted
again. The cutoff fires when `active_s` reaches the limit. `budget-cutoff.json` and
`evaluation.json` record `active_s` / `budget_active_s` and the clock. A continuation by
itself needs at least 60 s of active time left (`segments.remaining_s`).

`downtime_s` (segment gaps and pauses) is recorded for reports. It does not enter the limit.

The Claude supervisor leaves the end to the world: it ends a run on its own only 60 s of active
time past the limit, and it waits through a pause instead of closing the paused run. The Codex
host has no limit of its own.

## Wall backstop

Active time does not advance while a world is paused or its host is frozen, so it alone would
never end a run that is held forever. Policy runs therefore also freeze a second, longer limit
on wall time: `run_protocol.wall_backstop_s`, 172,800 s (48 h; `WALL_BACKSTOP_S` in
`roboteam/tasks/task_types.py`). It is private, like the limit.

The backstop counts wall time since START (`clock.backstop_elapsed`) **less every outage, route
and usage-limit pause** (`pause_wall_s` and the current `pause_since_wall` in the runtime
database), because such a wait is not the run's fault. If that much counted wall time has passed
and the active-time cutoff has not fired, the world owner stops the run as at a cutoff: dispatch
pauses, the arms brake, and the run closes. This happens even during an operator pause or a
review hold. The records differ, so the stop is not read as a normal end:

- a `POLICY_WALL_BACKSTOP` event (not `POLICY_WALL_LIMIT`) and `POLICY_BACKSTOP_CLOSED` (not
  `POLICY_BUDGET_CLOSED`), and `wall_backstop` in the runtime database;
- `budget-cutoff.json` with `wall_backstop: true` and `needs_review: true`;
- `evaluation.json` with `termination_reason: wall_backstop`, `wall_backstop: true`,
  `needs_review: true` and `budget_exhausted: false`.

The result needs review and is not counted. The Claude supervisor reports
`ended_by: wall_backstop`, or reason `wall_backstop` when it had to end a world that did not
close itself 150 s after the backstop. Both batches mark the run `needs_review` with reason
`wall_backstop`. Run analysis sets `excluded: wall_backstop`, and its `compute` command lists
such runs as `EXCLUDED`.

A backstopped run never continues by itself. `roboteam continue` continues it by hand: the
continuation moves the backstop's `budget-cutoff.json` and `evaluation.json` aside (with
`-wall-backstop-N` in their names), records `WALL_BACKSTOP_WAIVED`, and the backstop counts
again from that moment.

## Network-outage pause

The world owner checks that the model API can be reached (`roboteam/runtime/time/outage.py`).
It probes the host of the run's model `base_url` when the model has one, and otherwise the
harness's own hosts: `api.anthropic.com` for Claude Code, `chatgpt.com` and `auth.openai.com`
for Codex. Every host must answer.

| Property | Value |
| --- | --- |
| Probe | A verified TLS handshake on port 443, then an HTTP `HEAD /` that must get an answer (any status) |
| Interval and timeout | Every 5 s, 5 s timeout |
| Pause | After three failed probes in a row |
| Resume | At the first probe that succeeds |

A bare TCP connection is not enough: a local VPN tunnel accepts it even when its route to the
API is gone.

When the world pauses, physics stops stepping (the arms hold where they are), dispatch pauses,
new requests from the agents wait with their original call IDs, and an `OUTAGE_PAUSED` event is
written. The time since the first failed probe of that streak is taken back from `active_s`
(`retracted_active_s` in the event). The resume (`OUTAGE_RESUMED`) continues the same world
with the same ownership and integrity checks and replays nothing. An operator pause made
meanwhile is kept (`OUTAGE_HELD_FOR_REVIEW`).

A model turn that failed on the network during the pause is sent again once per role and
pause, in the same session: Codex when its app-server reports a transport failure, Claude Code
when the CLI's structured API error names a lost connection or does not say what failed
([Claude Code recovery](../harness/claude-code.md#recovery)). The resent turn replays nothing.
A second failure in the same pause, or a failure for another reason within it, holds the run
for review.

The probe pauses only a running trial, not before START or after the cutoff. A pause has no
time limit of its own; the wall backstop does not count it. A probe that never succeeds because
the world process has no direct route out never pauses: after 12 failures it stops and records
`OUTAGE_PROBE_UNAVAILABLE`. `ROBOTEAM_OUTAGE_PROBE=off` turns the probe off; the test suite
sets it.

A Slurm job that reaches the model API through a Mac (`slurm.egress_mode = "mac-ssh"`,
[Slurm](../hosts/slurm.md#10-the-mac-route-mac-ssh)) does not use the probe. Its route watcher
pauses the world the same way when the route is lost, for at most `slurm.egress_pause_s`.

## Usage-limit pause

A subscription's 5-hour or weekly limit lasts until its reset, so it is not retried like a
short rate limit. When a model turn fails on it, the host reads the reset time from the error
and asks the world to pause (`roboteam/runtime/time/quota.py`; `QUOTA_PAUSE_REQUESTED`). The
errors recognized are Claude Code's "You've hit your … limit · resets …" and
"usage limit reached|<time>", and Codex's `usageLimitExceeded` and "try again at/in …".

The world pauses as in an outage (`QUOTA_PAUSED`): physics and dispatch are held, original
calls are kept, and the time counts neither as active time nor toward the wall backstop. A
second role's request joins the first, and the later reset wins. The world resumes by itself a
minute after the reset, or 30 minutes after pausing when no reset time could be read
(`QUOTA_RESUMED`). An operator pause made meanwhile is kept (`QUOTA_HELD_FOR_REVIEW`).

Each role whose turn failed on the limit then continues once in the same session with the
frozen `quota-resume.md` message. A limit hit again pauses again. It is the same segment: no
continuation is used.

The operator is told at the pause and at the resume: a line in
`private/outputs/notifications.jsonl` and, on macOS, a desktop notification
(`ROBOTEAM_NO_NOTIFY=1` turns that off).

## Capacity retries

A short capacity or rate limit (HTTP 429, overloaded) does not pause the world. The host
retries the turn in the same session, at most 3 times in a row per role
(`MAX_CAPACITY_RETRIES` in `roboteam/runtime/run/bootstrap.py`), after 10, 20 and 40 s plus a
jitter, with the frozen `capacity-resume.md` message. Both harnesses do the same
([capacity recovery](../harness/README.md#capacity-recovery)). When the retries are used up,
the host pauses dispatch (`DISPATCH_PAUSED`, "Model capacity recovery attempts exhausted"). The
run then ends as an unexpected stop and continues by itself once
([when a run continues](continuation.md#when-a-run-continues)).
