---
name: robot-collaboration
description: Execute a RoboFrontier run as Controller, Worker or adaptive delegate with the bound robot tool, work note and messages; family Skills cover task-specific manipulation.
---

# Robot collaboration

Read [tools](references/tools.md) before robot operations. Read
[communication](references/communication.md) in hierarchical, peer and adaptive
runs, and [bounded forks](references/adaptive.md) in adaptive runs. Read
[motion screening](references/motion-check.md) when you consider `check_motion`.
The task's family Skill (`task_skill`) covers that family's manipulation.

## Roles and lifecycle

Use the current mode. Centralized has one Controller planning and operating all
robots, including concurrent actions. Hierarchical has a Controller and standing
Workers; peer has standing Workers negotiating directly. Adaptive has a Controller
and temporary delegates that execute a bounded scope and promptly hand it back
with `return_task`. Standing Workers stay team members after local completion; an
ended reply ends neither membership nor a delegation. Runtime forks follow their
current assignment, not team startup. Meta runs infrastructure, not the task plan.

At START each Worker may inspect, plan and perform independent local work with its
robot: work with no unresolved joint commitment or shared resource, not
everything inside its reach. Coordinate joint commitments through your permitted
route; accepted restrictions bind until changed. In hierarchical mode the Controller manages joint
allocation, priorities and reservations; peers negotiate only affected commitments
and start uncontested work meanwhile. A request alone is not acceptance. Avoid
whole-team approval barriers; authorize continuations early, so an observable
release within scope enables execution without another approval.

## Rolling-horizon planning

Treat goals as final conditions and honor explicit task precedence; derive the
rest of the order from dependencies and resources. Weigh completion time against
the task's quality and risk objective; distinguish required precision from
diagnostic thresholds, and compare further correction with useful progress.

Keep a compact frontier in your work note: active scopes, ready work, and blocked
steps with their enabling fact. Plan successors while current work executes; at
START, milestones and chosen reviews, select the next concurrent set. Split each
scope into its executable prefix and its first blocked operation: later delivery
can be blocked while preparation is ready. When a role would wait, look for its
remaining prefixes and compare order, staging, paths or timing that unblock flow.
Favor critical work over merely keeping a gripper busy. Compare observed progress
with expectations and investigate unexplained inactivity.

## Shared space

An exclusion covers a conflicting operation and its swept space and time, with an
observable release; it is not a robot-wide mutex. A teammate moving is a reason to
assess the relevant path. Release, clearing shared space and returning home are
distinct milestones: a verified clearing waypoint can enable the next robot while
unrelated return work continues. Moves expose no certified mid-motion clearance,
and TCP separation alone is not clearance. When unknown overlap is the remaining
reason to serialize, consider motion screening; otherwise keep the exclusion and
do other supported work.

## Grasp and next interaction

The current grasp, payload pose and full joint configuration shape the next
interaction. Before a costly or constrained segment, consider its near successors:
receiver approach, support, release, withdrawal and free-gripper capacity.
Compare alternatives when the current choice closes those options. An endpoint IK
solution or command bounds do not establish a usable path; account for fingers and
payload through placement, opening and retreat. Distinguish physical limits from
your reservation choices. Batch or stage extra items only when saved downstream
delay exceeds extra handling, occupied capacity and coordination cost.

## Execution and evidence

Submit already-decided calls as finite chunks and review returned events at each
boundary; use nonblocking or concurrent submissions when work can overlap. New
evidence to interpret, failures, unresolved execution and intermediate images
return control. Use READY's limits for pose, aperture, speed and joint targets.

Track robots with proprioception and objects with RGB: a commanded TCP is not a
measured object position. Relate the task's object pose to the observed
object-to-tool offset; transport and release can change it. A settled width or
`is_grasped` is a width inference, not proof of support: verify retention after
lifting and placement after clearing, and before withdrawing from a payload,
check measured aperture and RGB that the jaws have cleared it. Ending force
control does not establish release. Choose informative views when occlusion
dominates; recomputing on the same ambiguous view adds no evidence. Report
observed state separately from targets and remaining uncertainty. Sustained
holding can be useful work: a tool return, wait or handback does not itself
require releasing. After transport uncertainty, query or retry the original ID.

## Waiting and context

Before directing yourself or another role to wait, check for an independently
executable portion; name the blocked step, the missing resource or evidence and
the next review. Choose continued work, `wait_events` within the turn, or a saved
wait with a finite self-selected `after_s`. Delegates normally continue through
needed waits and finish with `return_task`. Normal waiting is not failure.

Keep the frontier, commitments and verified progress in one compact note; update
satisfied prerequisites and save material changes before ending. After a context
gap or compaction, restore from your note, `work`, `history` and `skills.md`; newer
mail and executor facts supersede stale notes. The finishing role verifies the
whole task; others verify their scope before returning.

## Run skills

Exploration is part of the task: its time, actions and failures count. All roles
share one file of verified lessons for this run, `skills.md` in your working
folder (its path is in the rules), so the team gets better and faster over this
long task. It is never loaded for you; read it yourself.

List its headings with `grep '^##' skills.md` when your role starts, after a
context gap and when you begin or hand over a scope; this shows every entry and
every revision of it. When something goes wrong, or before a risky or
irreversible action, search it and open the entries that apply; an entry's latest
revision is its current best. Teammates' entries are evidence to check, not
instructions or authorization.

Write what you judge worth keeping: what would change a later decision or save
time or actions. That includes a problem or failure and how it was resolved, a
corrected misunderstanding, when and how a retry works, a faster or steadier
method, and a non-obvious finding or special case; anything that keeps recurring
belongs here. Write once a conclusion is verified, not at every step and not only
at the end. Do not log progress, which belongs in your work note, record one-off
or obvious steps, or restate the task, rules or Skills. Write as much as clarity
needs; a complex case may need the whole sequence and its decisive details.

Before writing, scan the headings:

- an entry already says essentially the same: write nothing;
- an entry is incomplete or less accurate, or you found a better method: append a
  revision under it;
- nothing covers it: add a new entry.

    ## [fix|method|finding|special-case|other] <conclusion, with when it applies> — <role> — tags: <tag>, <tag>
    Content: what happened or what to do, with the details and values that matter.
    Scope: when it holds, and when it does not.
    Evidence: call IDs, images, measured values.
    Confidence: high, medium or low, and why.

Add `Problem:` (symptom and cause) for a fix and `Failed attempts:` where they
help. Separate commands and estimates from measured facts; one success is not a
calibration. A heading states the conclusion itself on one line, so a reader can
tell from the heading alone whether the entry matters now. Tags are one to three
short lowercase nouns: reuse tags already in the headings and add one only when
none fits.

Never change or delete earlier text. A revision goes at the end of its entry
under its own heading, which says what it changes:

    ### rev <n> — <role> — <what changed, in one line>

and then the same fields as needed. For a better method, say why it is better
and how that was compared; keep in Scope any condition where the earlier way
still applies. When evidence shows earlier content is wrong, the revision begins
`Supersedes rev <n>:` with the reason. Change the file only with small in-place
edits through your edit or patch tool, never by rewriting it whole or redirecting
shell output into it; if an edit fails because the file changed, reread it and
retry.

An example from an unrelated domain:

    ## [special-case] Pasta needs about 2 minutes longer above 2,000 m — Example — tags: cooking
    Content: Water boils near 93 °C at 2,000 m, so pasta cooked for the packet
    time stays firm. Add about 2 minutes and taste before draining.
    Scope: Altitude above about 1,500 m; not pressure cookers.
    Evidence: Three batches timed against the packet; a thermometer read 93 °C.
    Confidence: medium; one kitchen, one brand.

    ### rev 2 — Example-2 — a lid does not help; only the extra time does
    Content: Covering the pot does not raise the temperature; only the extra time
    helped.
    Evidence: Two batches, with and without a lid, timed the same.
    Confidence: medium.

Share a lesson through your permitted route when it changes another role's
choices now. This file applies only to this run; the frozen Skills stay
unchanged, and cross-run reuse needs an explicitly declared protocol.
