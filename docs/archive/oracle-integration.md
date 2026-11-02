# Four-family Oracle integration: historical acceptance

This page is the **2026-10-27 merge acceptance snapshot**, not the current launch
configuration. New operation uses the [unified CLI](../unified-cli.md),
[Oracle supervision](../oracle/README.md), and [Factory workflow](../factory/replay.md). Current
qualification is recorded in the [integration ledger](unified-main.md).
The [repository layout](../repository-layout.md) distinguishes retained recordings
from installed code and assets.

Starting from main `d3e5916`, the integration merged the Mosaic, Transport, Relay,
and Dial continuation branches. Original commits, failures/recovery, frozen
source, trajectories, edits, videos, and assistance labels remained preserved.
At that acceptance point, no worktree had been deleted and no formal policy run
had started. Later cleanup retired four old task worktrees and prepared packages
and introduced native CLI hosts. Those later changes do not rewrite this snapshot.

## Structure at the original integration

The daily entries were the [task catalog](../tasks/README.md),
[Codex guide](../engines/codex.md), and [Factory design](../factory/README.md), backed by
`scripts.tasks` and `scripts.factory`. Public family materials moved into
`configs/task_families/FAMILY/public/` with original hashes preserved.
`current.json` distinguished policy and recorded-Oracle purposes. Historical
scripts/catalogs retained reproduction responsibilities instead of selecting
every future default. Family history, earlier plans, and old Factory handoffs
remained under `docs/history/`; users no longer had to locate another worktree
for ordinary family documentation.

## Data preservation

Receipts are under `runs/engineering/oracle-integration-20261027/`, including
`preservation-final.json`. Original Mosaic/Transport/Relay protection manifests
passed approximately 217,000 file checks. One shared source file had changed;
its original bytes remained in the source branch's Git objects rather than being
claimed byte-identical in the new checkout. Dial independently checked 64
bindings, including reports, selections, source metadata, stream indexes, and
original rendered videos. Generating new timelines decoded all 36 recordings'
original chunks and verified each SHA without altering the streams.

The audit inventoried 640 historical dependencies pointing into worktrees.
592 valid links were redirected to durable archives containing about 648 MiB of
unique content; `runs`, `outputs`, and `vendor` links pointed to the main data
root. Archived content could be reused but did not share inodes with worktree
files scheduled for removal. Another 48 links were already broken before
integration, referring to older Transport, Mosaic R13, and Relay Oracle folders.
Their original paths and broken status remained recorded; missing historical
versions were not fabricated. The selected 36 Oracle sources, assets, and streams
were independently accepted. The 48 broken links were not marked restored.

Ignored scene assets were restored from the state-asset cache by original hash:
33,159 entries reused, 550 restored, zero missing in that scan. This did not mean
Git contained all experiment data. The historical backup scope included `runs`,
`outputs`, `vendor`, state assets, and dependency archives. The original handoff
left worktree deletion to the user; that statement is not a present instruction
to delete any checkout.

## Shared code and policy preparation at that time

Explicit adapters identified different families' edit layouts; matching schema
strings alone were not used to guess structure. `FactoryTimeline` unified
station clocks, source frames, appearance reset, and a single whole-factory FK
update. Independent station looping entered the shared release, while earlier
hold-at-end contracts remained historical.

New policy runs froze family public materials and private release bindings,
then entered evaluation/recording through an independent protocol. Original
source tasks did not have qualification flags rewritten. Complete source
fingerprints recorded the actual bytes. Compatibility receipts needed for
historical Mosaic/Dial review bound both old/new hashes and checked unchanged
AST portions. Exclusions were limited to the explicitly added prepared-START
checks and the Relay class unrelated to those two families. New Relay scoring
was not represented as identical to old Relay scoring, and original evidence
hashes remained unchanged.

All four real frozen scenes passed offline START construction of their evaluator
and 60 Hz recorder with physics stepping prohibited. At this specific snapshot,
the integration host had not supplied actual native Codex session tools; native
round trips, model performance, and genuinely parallel policy execution were
still unaccepted. Batch preparation created independent inputs only, without
model sessions or simulation launch. Later native-engine acceptance must be read
from its own dated evidence rather than inserted into this historical claim.

## Factory and acceptance scope

V7 kept a 55 x 50 m layout and the 36 matching frozen sources. It added facilities
under tables, near walls, and at region edges, and removed wall branding text.
Static batching, mesh/material reuse, and near/far cameras remained. Transport's
half-opening display was an explicit visual edit, without scaling robots or
objects or rerunning physics.

The source-native edit revision retained context around actions, progress,
violations, failures, recovery, and RGBA events. It protected slow progress,
continuous rotation, and directed drift superimposed on oscillation. Classification
ran at 10 Hz while frame selection used original 60 Hz indexes. Both original
family edits and new versions remained available. Classification did not claim
measured forces or a complete causal proof.

Checks across 36 stations covered large forward time jumps, backward seeks,
independent loop boundaries, and pose/appearance resets. Display rigid-position
error was below 1e-13 m. A four-second/120-frame preview and a 15-frame Cycles
animation encoded and decoded successfully. Static Cycles previews and animated
state export were connected; a complete narrated demo, editorial subtitles, and
formal policy runs remained future work at that point.

A historical same-machine Filament static comparison used 1280 x 720 output,
three alternating rounds, and five views. Time increased 9%-22%; RSS changed
about 1,756 to 1,805 MiB. That rendering path was later removed; current simple
observations use the selected MuJoCo OpenGL backend. A single two-view Cycles
comparison at matching settings observed approximately 1.10x and 1.55x runtime.
These were bounded observations, not statistical guarantees, real-time 30 fps
claims, or arbitrary-host cost limits. Original measurements and scope remain
in the Factory documentation.

The final historical offline harness reported **1,008 Python tests**, with zero
failures, errors, or skips; JavaScript and documentation checks also passed in
`harness-release.json`. The 36 inputs under
`runs/policy/prepared-integration-20261027/` had input integrity, unbound sessions,
and unstarted worlds checked in `prepared-batch-verification.json`. Those were
reviewable preparation artifacts; native-host and budget validation was still
required before launch. This historical green result does not describe today's
larger test discovery. Physical engineering, replay without dynamics, and formal
model execution remain separate acceptance scopes.
