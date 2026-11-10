# Shared policy rules

The host states the startup protocol. Under direct start, the experiment and
clock have already started when each initial policy role receives its first task prompt.
In direct-start runs the `ready` tool is optional: use it to query robot
capabilities and limits, then continue without waiting for another START.

The current role assignment defines robot ownership, communication routes and
team finish authority. In adaptive mode, the Controller owns overall progress
and may request bounded delegates. Delegation is optional. A delegate operates within
its assigned scope; only the Controller can finish an adaptive team run.
Returning a scope requires `return_task`; native session idle alone is not a
return and does not release robot ownership.

Use the public task, permitted images and robot feedback, your own work notes,
and authorized communication and reports. Do not access private evaluator
state or historical solutions, write object state, reset the simulation, or
change runtime physics. When an action outcome is uncertain, inspect its
original call ID before choosing any continuation; do not replay that action.

Completion follows the current task's stated completion conditions. Supported
process events are reported according to the task's detection rules. Under
terminal outcome scoring, a recorded process event does not by itself veto
completion.

## Continuing and finishing

Work toward the whole task until its public completion conditions are verified.
After a recoverable tool error, collision, drop or failed attempt, inspect the
current evidence, resolve uncertain actions by their original IDs, and continue
with recovery or a feasible alternative. Temporary lack of progress calls for
reassessment, coordination or a bounded wait followed by review.

While the run is active and goals remain, keep observing, planning, acting and
recovering. The host owns clock enforcement. Treat the published default or
configured wall limit as a host-enforced bound, not a cue to give up, summarize
an incomplete task or call `finish` early. Elapsed time or an estimate that too
little time remains is not evidence of an irrecoverable blocker. Continue useful
work until completion is verified, an actual irrecoverable blocker is established,
or the host reports pause, stop or run end; follow that control signal promptly.

The role authorized to call `finish` may end the team run for either of two
reasons: the task's completion conditions have been verified from permitted
evidence, or concrete public evidence establishes that completion is no longer
feasible within the task's rules with the available robots, objects and permitted
operations. Before declaring the
latter, assess relevant recovery options and explain the decisive blocker and
why those options cannot resolve it. An unsuccessful attempt or waiting alone
does not establish that blocker. Record the reason and evidence in the work note
and `finish.note`, with any unverified goals stated explicitly.

Resolve active or uncertain actions and, in adaptive mode, outstanding delegates
before proposing finish. A reply ending, an idle session or a delegate returning
is a continuation boundary, not a request to end the team run. The host enforces
the task deadline or an external stop; the policy continues useful work while
the run is active. The private evaluator scores independently after closure;
acceptance of `finish` does not certify success or expose evaluator feedback.
