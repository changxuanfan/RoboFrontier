# Unified main integration

This document tracks implementation gates. It is not a statement that all gates
have passed. The reviewed engineering integration is published on `main`.
Oracle repairs through `0009b40` are published. The native Claude large-prompt
follow-up uses `codex/native-prompt-stdin` until its source-pinned delivery checks
are complete. Existing source worktrees remain retained.

## Product

**RoboFrontier: Benchmarking How LLM Agents Organize, Communicate, and Collaborate
in a Multi-Robot World**

Confirmed first author: **Changxuan Fan**, **Hong Kong University of Science and
Technology**. The full author list, author order beyond first author, copyright
holder, publication status, DOI, and paper URL are not finalized. Do not infer
these fields from Git history or the repository owner.

## Sources and provenance

| Source | Pinned source commit | Integration intent |
| --- | --- | --- |
| Main | `c8b41371fbc49aa014b2d36332c43529b3c6d4f4` | Existing shared benchmark |
| Codex | `b518bc164eb1cdcd5766435a6e49345a7f880557` | Native Codex policy engine and protocol fixes |
| Factory server | `d1e1b3d7e274fb001c1576f9876239601fc72647` | Portable assets, frozen-source replay and Slurm rendering; already contains the pinned Codex source |
| Luna | `907f4807eb43644e9db4621c5305fa3300017830` | CPU rendering, Docker, providers and command-line operation |
| Multi-topology | `c1d05e3426468322fc5e89141e0cb5f49e87a925` | Four topology modes and communication measurement |
| Claude | `3b3fd08e8220d486b004c9dc2d764f5ba0d27d8b` | Native Claude Code sessions, MCP and recovery |
| Oracle | `a0249a6977e8137442a3d1f323be903a64c3f8c9` | Curate validated R14 fixes; do not import R15 experiments as defaults |

## Acceptance gates

- [x] Preserve refs and uncommitted source work outside the integration worktree.
- [x] Fast-forward Codex and Factory server without duplicating their shared history.
- [x] Integrate Luna, multi-topology and Claude with targeted regression checks.
- [x] Provide one validated TOML configuration and CLI; resolve defaults once and freeze the effective configuration per run.
- [x] Launch initial task hosts through one scheduler with a default 0.3-second interval.
- [x] Isolate task runtime state and verify native initialization against synthetic loopback providers.
- [ ] Qualify real-provider/subscription authentication and refresh lifecycles.
- [x] Qualify four native Single cases through real Slurm node-local execution, H800 task observations, normal stage-out and verified restoration using a synthetic HTTPS model.
- [x] Verify shared START, scoring, safe call-ID and stop semantics across native engines with synthetic endpoints and real physical owners; retain separate formal provider gates.
- [x] Keep R14 as the Mosaic default and retain existing physical assets while unqualified candidates remain gated.
- [ ] Qualify physical candidates before publishing changed defaults; no full candidate qualification is inferred from local recovery or a different case.
- [x] Verify automatic pinned policy-asset installation from a fresh checkout.
- [x] Verify supported old/compressed motion, image references, evidence restore and frozen-source Factory replay; preserve the recorded historical-data scope.
- [x] Integrate repaired Oracle semantics without exposing private solutions to policies; qualify the current Transport L1 full reference separately from other cases.
- [x] Publish English-only tracked content, offline task atlas, editable full video project, detailed README and documentation; retain the original published full movie as requested.
- [x] Exercise CPU/native macOS and real Slurm/H800 EGL/minimal-JPEG paths with explicit scope receipts.
- [x] Qualify 36-task Adaptive execution capacity and actual Slurm USR1 stop/stage-out through restored stopped evidence; retain uncertain model accounting, real-provider and formal-scoring gates separately.
- [x] Run offline suites and clean-checkout checks; record any remaining paid/hardware qualification separately.
- [x] Review the engineering integration before publishing or merging it into main; retain the separate qualification gates below.

## Latest scoped acceptance snapshot

At final code `8b273ab`, complete discovery passes on macOS and Linux: 1,544
checks each, zero failures/errors and 17 conditional skips. Eight opt-in native
Claude/real-physics checks also pass on each platform at this source, covering
images, four overlapping worlds, ordinary actions, native delegation/mailbox
continuation, early finish and signal sealing. Model endpoints are synthetic.
The other nine historical conditional assertions retain their separate passing
`a595709` receipts; no newer-source rerun is claimed for them. The original
SQLite SIGSEGV and intermediate timer failure remain retained, separately from
these final passing reports. The original snapshot loop passes 1,000 repetitions
at the final source. Linux uses a fresh source checkout, all 45,141 authenticated
historical fixture files and CPU/Mesa rendering.

Fresh current-scene Transport L1 and L2 references at `f9d532d` each complete all
12 goals in one world. All independent v2 verdicts are true, with no inter-arm
contact, unresolved action, model call or external repair input. Recorded active
wall times are 382.518 and 501.607 seconds. All suite/controller/scoring/scene
bytes are unchanged from that witness source to final code `8bd989a`. These
reports retain their actual source identities and do not qualify other cases or
new physical parameters. Earlier failed attempts remain stopped and retained.

The earlier placement source `c830202` passed 1,536 checks per platform and two
full L1 witnesses. Main `29e1211` is published with its rebuilt source image and
successful atlas validation CI. Seven prerelease fixture/atlas/acceptance assets
have verified uploaded hashes. Final continuation/closure source integration and
its delivery image are recorded separately; their publication is not inferred
from this older main receipt.

Actual Slurm job 428877 at `29e1211` completes four Single native Claude/physics
owners and H800-rendered task observations through production stage/execute/
collect/ZIP/stage-out. All 1,728 returned files verify through restoration without
restarting worlds. Peak started tasks is four; peak overlapping motor actions is
three. It uses a scripted HTTPS model, not a real provider or formal model score.
The earlier job 428862 remains a separately scoped minimal EGL/JPEG probe.

Genuine GPT-6 Luna and Haiku 5.5 API compatibility checks now pass, retaining
their actual `b179598` precheck source and separate budget receipts. Subscription
refresh and Claude formal scoring remain open. Two `8b273ab` Slurm attempts
independently verify 36 overlapping Adaptive owners, 72 bound native sessions,
ordinary actions and handbacks from stopped archive traces. All 18,239 files in
428948's returned archive verify through full restoration without physics;
428931's separate full restoration remains in progress. Interruption accounting
stays uncertain.
Physical candidates must qualify
before any default promotion; existing release assets remain unchanged. The
user's deferred full video rerender and unfinished publication metadata remain
deferred. All 6,572 tracked paths/text files are subject to the English-only
release check; frozen ignored evidence retains its authentic bytes and names.

## Invariants

Task limits are measured from persisted START, normally 86,400 seconds. An
engineering stop is separate and must not silently replace the public task limit.
`ready` queries capability; it does not unlock START. Completion is evaluated by
an independent scorer; process events are reported separately. Dial completion
remains latched on unlock. Adaptive delegation remains optional and dynamic.

New requests receive host-generated IDs. Uncertain physical requests must not be
replayed under new IDs. Collection and archival run only after all writers stop;
source evidence is retained by default. Factory playback uses each recording's
frozen scene and assets, including legacy recordings. A successful restore or
render does not imply that the recorded task succeeded.

## Merge decisions

Luna's offscreen capture and capture timing are retained. Factory server's
array-based diagnostic Factory replay is retained, because it avoids requiring
production Cycles video rendering for pixel/FK comparisons. Luna's additional
call-ID query/uncertain-result tests are retained alongside Codex error tests.

## Initial regression inventory

The first full discovery run executed 1,272 tests in 118 seconds: 25 were
skipped, 179 errored, and one failed. This is a diagnostic inventory, not a
passing release gate. Most errors request historical scene/workstation assets
outside the current 36-case policy bundle. Other findings include missing Oracle
extras and script import paths, two synthetic robot fixtures missing their image
profile, a Factory fixture missing table metadata, and an outdated source
compatibility receipt. Do not update a provenance receipt merely to turn a test
green; verify the claimed equivalence first, or withdraw that claim.

The targeted engine/role/protocol checks are separate from this legacy inventory.
No live model calls were made by these checks. Claude's scored-run qualification
remains closed until its native lifecycle has passed the required real checks.

## Configuration and launch implementation

The first unified CLI stage is implemented in `robofrontier.cli`, with validated
`robofrontier.toml` settings and immutable per-run effective configuration.
`docs/unified-cli.md` documents actual supported options and pending interfaces.
The API path creates one home per task, serially initializes every home, then
launches hosts through one 0.3-second gate. Collection resolves per-task markers
while preserving legacy batch-home behavior. Native subscription refresh remains
an explicit qualification gap; credentials are never cloned automatically.

The native CLI wrapper can plan, bootstrap assets, prepare Codex runs or Claude
engineering drafts, explicitly preflight providers, run, read atomic status,
request stop, collect, ZIP, extract and restore evidence. All four Claude modes
now have native engineering entries; formal scored execution remains closed.
Factory and Oracle commands share the versioned configuration, with their
scoped acceptance evidence recorded below. Slurm staging has
its own settings and entry, with real-cluster qualification still outstanding.

Six real Codex 0.165.0 app-servers were initialized in independent cold homes and
then launched at a 0.3-second interval. All acknowledged initialization and exited
cleanly; no model turn or robot world was started. This verifies local startup,
not subscription refresh, 36-task resource capacity or provider execution. Raw
local evidence is under `runs/engineering/main-integration-codex-offline-20261101`.

The new command independently prepared four minimum-arm Level 1 cases with zero
model calls. All current 36-case asset hashes also passed inspection. The existing
asset lock is unchanged; recommended physics candidates still need final gates.

The source compatibility receipt was reviewed rather than blindly rehashed:
the exact observation-profile initialization and reported camera-size changes
are normalized alongside the service wrapper, and every remaining pipeline AST
node matches the original unaffected digest. The unaffected non-Relay evaluator
AST also matches its original digest. This establishes the limited historical
source claim, not equivalent policy observations, current scoring or new physics.

The completed configuration-stage regression group passed 123 tests. Thirteen
Codex host/transport Node tests also passed. Renderer checks reject a Mesa
software context when NVIDIA is requested and record the actual GL vendor,
renderer and version. The GPU validation still needs real Linux NVIDIA hardware.
The old synthetic ready-capability and Factory fixtures were brought up to date
without reducing their physics/FK assertions. Full historical-asset coverage,
real Slurm hardware acceptance, English migration and product UI/video gates
remain outstanding.

## Slurm staging implementation

The new `slurm-submit` command freezes committed source, the staging launcher,
resolved public settings, pinned assets and the explicit provider receipt before
queue submission. Compute-node staging requires a verified local filesystem.
Runtime, task Codex homes and temporary files remain node-local. A separate
`srun` step contains all execution descendants; the batch shell returns evidence
only after that step exits and owner/supervisor locks are available.

Only atomic supervisor JSON is monitored. Normal stage-out returns one verified
evidence ZIP with payload SHA-256 hashes. A failed collection returns stopped raw
motion/session evidence for review, excluding CLI authentication/config stores.
No source is automatically deleted and no uncertain action is replayed. Node
failure/SIGKILL can still prevent stage-out; this is not checkpoint/resume.

The retired Luna sbatch entry now gives migration instructions instead of
placing active databases in shared storage or making implicit paid preflight
calls. `docs/slurm.md` documents commands, resource requests, assumptions, stop,
stage-out, credentials and recovery limits. The focused staging/collection/
configuration regression group passed 56 tests with no model calls. This does
not validate a site's Slurm process tracker, actual node storage, 36-task memory
capacity, NVIDIA EGL or its cluster network.

## Direct startup for standing teams

New standing-team Codex batches use `direct_team_v3`: all required roles must be
bound to distinct native sessions before one persisted START, followed by an
explicit started prompt to every role. No role must first run a READY model
turn. Single/Adaptive retain their direct Controller startup. Frozen legacy
READY inputs remain supported, without being rewritten.

The Single Controller, standing Controller and Worker role prompts no longer
unconditionally demand READY/yield. The shared policy contract now describes
initial roles rather than assuming every topology starts with a Controller.
The capability reference distinguishes an optional direct-start query from a
legacy readiness registration. Codex bootstrap/recovery text is now English.

Offline checks cover both standing-team topologies, actions before/after START,
distinct-session binding, optional post-START capabilities, unchanged ownership,
one task clock, failed binding/START, STOP during setup and legacy behavior.
The runtime group passed 55 tests; the configuration/compatibility group passed
18 tests; six further profile/bootstrap checks passed. Fourteen native host tests
and all 24 existing dispatcher scenarios passed. These are overlapping groups,
not a count of unique release tests. No model inference was used.

## Unified Docker implementation

The `container` command builds committed source through `git archive`, verifies
the image's source-revision label, creates persistent plain local Docker volumes,
and invokes the same native command-line interface. Image construction installs
both native CLIs, locked dependencies and pinned assets without model inference.
The entry checks runtime filesystem locality. API task homes and native sessions
remain separate from the host's existing authentication directories.

The wrapper reads a prepared batch's frozen renderer before requesting a GPU,
forwards only selected provider credential variable names, monitors JSON, and
requests orderly stop on interruption. A still-live/disconnected container is
retained for review. After closure, automatic evidence ZIPs are copied to the
host and verified against the terminal command's SHA-256. Native session/auth
volumes are never removed automatically. Explicit native authentication commands
are available without cloning the host's Desktop/Keychain credentials.

The focused container/configuration/Slurm group passed 31 offline tests. The
actual `e51fa4b94315` image then built successfully with the pinned assets and
both CLI versions. Its unified plan returned all 36 tasks, Luna high and adaptive
with zero model calls. A real OSMesa context rendered RGB using Mesa llvmpipe.

The actual Codex sandbox failed under Docker Desktop's default seccomp profile
with a user-namespace permission error. The same fixed local probe passed when
the container was explicitly started with `seccomp=unconfined`, without privileged
mode or added capabilities. This establishes only the local sandbox prerequisite;
it does not qualify a complete native model/robot lifecycle.

The CLI now provides an offline `doctor`, checks native prerequisites before a
confirmed paid provider preflight, and checks native prerequisites/rendering
before task launch. A failed probe blocks model calls. The container seccomp
choice is explicit, validated, frozen and documented; its default remains the
Docker default. The focused diagnostics/configuration/container/Slurm group
passed 39 tests. Provider/subscription lifecycle, actual NVIDIA and 36-task
resource qualification remain outstanding; no paid test was started.

The `4210bf575eb5` image also prepared all four minimum-arm Level 1 tasks through
the container command, without models. An engineering-only probe loaded each
frozen world, stepped 0.2 simulation seconds, and called the actual policy capture
implementation for three cameras per case. All 12 JPEGs decoded at 896 x 560;
all states remained finite and all frozen input hashes stayed unchanged. This
is a loading/observation check, not sustained physical stability or task success.

The first actual doctor invocation exposed its own missing temporary Codex-home
directory, before any model call. The directory is now explicitly created for
both native CLIs and the regression test asserts that it exists. The independent
archive command now returns the ZIP SHA-256 as well as its path, matching the
container export verifier. The focused follow-up group passed 23 tests including
byte-exact session/image/motion restoration and terminal receipt verification.

The corrected `9352651995a8` image built and the actual unified container doctor
passed with explicit `unconfined` configuration. With Docker's default seccomp,
the same command returned exit 2, exposing the namespace denial while still
reporting a successful llvmpipe render. Both invocations made zero model calls.

A synthetic stopped collection containing a real 21-frame Transport motion
stream and one synthetic image-bearing session was archived by the native
container command. The wrapper copied a 5,225,812-byte ZIP to the host and
verified SHA-256 `0c6b78cf2ca0ff042f5d9d7eefc843f99d939a70dea69069be050ac3d8d1f367`.
Host extraction and archive verification restored the session byte-for-byte,
loaded the recording's own frozen model, and replayed every frame with finite
forward kinematics. A restored frame rendered at 1920 x 1080 using Apple M5 Pro
OpenGL/Metal, independently of the 896 x 560 policy-image format. This is plain
background reconstruction, not Factory qualification or a native model session.
Local evidence is under `runs/engineering/main-integration-container-20261101`.

The root README is now English and describes the actual unified entries,
authentication boundaries, defaults, data locations and open acceptance gates.
It does not yet make the rest of the repository English or replace the pending
Factory/Oracle/atlas/video documentation and integration work.

## Unified Factory configuration and actual CPU replay

Schema version 2 adds a separate `[factory]` section for data identity, Cycles
device, Blender executable, output dimensions, quality, presentation duration,
import speedup and render-array concurrency. Existing frozen version 1 policy
configurations retain their exact hashed shape. Factory video defaults to
1920 x 1080, independently of 896 x 560 policy observations. The full tour remains
210.5 seconds; an explicit positive duration caps only an engineering preview.

The unified command now supports setup, verify, doctor, recording import,
preparation, local execution, status and explicit Slurm submission. A prepared
plan freezes the effective configuration and code/input hashes. Existing render
plans keep their native legacy entry. CPU queues request no GPU; CUDA/OPTIX
queues require one GPU; Metal is rejected on the Slurm path. Queue submission
remains a dry run unless `--queue` is supplied. See `docs/factory.md`.

The focused Factory/configuration/container/Slurm group passed 53 tests. They
cover frozen settings, version 1 policy compatibility, independent observation
and video sizes, full-tour duration, legacy plans, mismatched bundle rejection
and explicit queueing. These tests made no model calls.

Actual native commands verified all 123,198 files and 36 stations of the pinned
R14 Factory package. Four minimum-arm Level 1 jobs then rendered three frames
each using Blender 5.1.2 CPU Cycles at 320 x 180, one sample and 30 fps. Transport,
Mosaic, Relay and Dial all passed complete video decoding, input/code checks and
result sealing; representative images were inspected. Maximum reported Blender
pose-position error was approximately 1.91 micrometers. This small diagnostic
does not validate full-length videos, new physics, GPU performance or task success.

The previously verified evidence ZIP was restored and its real 21-frame
Transport motion imported through the unified command. Import composed the desk
from that recording's frozen source, produced a distinct verified 1,217-file
bundle and retained `recorded_benchmark_presentation_only` qualification. Every
copied float32 state and timestamp matched the restored source exactly. All
21 frames passed Factory FK checks with physics stepping explicitly forbidden;
maximum positional error was below 5.1e-15 m. A separate three-frame CPU Cycles
render of this imported bundle also passed decoding and sealing. This is a
synthetic collection containing real motion, not a native model result. New
all-family recording import, full videos, GPU and real Slurm qualification remain
open. Local artifacts are under
`runs/engineering/main-integration-factory-20261101`.

## Second full regression inventory

After the source/fixture corrections and added integration checks, full discovery
executed 1,355 tests in 715.670 seconds. There were no assertion failures, 177
errors and 25 skips. Every recorded error was a missing file/scene asset or a
missing historical evidence dependency; none establishes an acceptable release
test result. Historical scene assets, Oracle witnesses and source-preservation
receipts still need explicit installation/Legacy treatment. Current 36-case
asset verification is separate and must not be used to claim that this full
suite passed. Raw diagnostic output remains in local engineering artifacts;
the historical asset/evidence gates remain open.

## Curated R14 Oracle implementation

The integration extracts the R14 endpoint-worker, checkout-binding and
revision-aware runner changes through `a49880f`, plus the archived-executor cache
diagnostic correction from `76d87ed`. It does not merge the Oracle branch's R15
assets/selectors, balanced/direct-nearest source experiments or experimental
review scope refinement. The native Mosaic default is now explicitly R14; a
selected task's own revision must also agree with its catalog before a world is
constructed. Policy release inputs and locks are unchanged by this curation.

The focused group passed 98 tests, including actual serial/parallel endpoint
equivalence on the current R14 scene, frozen imports, source color mismatch,
worker errors, same-owner recovery and uncertain-action handling. Existing
equivalence tests now use the installed R14 scenes rather than missing R13
assets; their physical-array and task-contract assertions are retained.
`docs/oracle.md` documents native execution, assistance, evidence, stop and timing
boundaries. Unified Oracle configuration/supervision and new full physical
witnesses remain pending; these tests are not scored or full-case results.

The committed `9e088cc` executor then ran an actual two-goal R14 commissioning
trial with four planning workers and no internal physics worker pool. It
completed the two selected goals out of 72, with 58 robot actions, no failed
robot actions, no process violations, no unresolved actions and no assistance.
The report correctly keeps full-case `passed=false` and
`commissioning_passed=true`. Wall time including planning was 151.920 seconds;
simulation reached 87.88 seconds. The independent motion audit verified all
5,274 frames, checksums and 141 visual events with a maximum sample gap of
0.018 seconds. Compressed chunks totaled 3,038,141 bytes. This is an actual
partial physical reference, not a full-case success or an LLM run. Evidence is
under `runs/engineering/main-integration-oracle-20261101`.

## Shared runtime language follow-up

The shared scheduler wake notices, native Desktop delegation notice and run-audit
Markdown now use English. Wake triggers, role authority, ID isolation and the
legacy protocol branch are unchanged. This is only part of the repository-wide
English migration; legacy generators, pages and historical documents remain.

Three old Codex RPC assertions still matched Chinese bootstrap/recovery text
after the host had already changed to English. Their failed pre-update run is
retained locally; assertions now check the same process-event, legacy READY and
post-START recovery semantics in English. All 21 focused Codex Node tests, all
24 existing dispatcher scenarios and 23 scheduling/report/direct-start Python
tests passed. An additional opt-in smoke passed using the actual native Claude
CLI against a local synthetic model endpoint and actual MuJoCo. Its early-finish
path produced an incomplete evaluation, sealed evidence and the English
unqualified-engineering report. This does not qualify a real provider, adaptive
delegation or formal Claude scoring. None of these checks used paid inference.

## Unified native Oracle workflow

The CLI now exposes `oracle plan`, `prepare`, `run`, `status` and `stop` for the
existing Transport full-order, Mosaic R14, Relay live-pipeline and blind Dial
entries. It selects current released task scenes rather than the historical
`oracle` recording inventory, and pins source, harness/catalog, scene assets,
effective settings and dependency versions before one single-use launch.
Fresh Dial puzzles are evaluator-only; an optional explicit codebook remains
private and never becomes a solver input. Native typed recovery, evaluator
gates, intervention records and full-versus-commissioning scope are retained.

Schema version 3 adds a separate Oracle section. Frozen version 1/2 settings
remain exact and are validated without adding fields or changing their hashes.
The Oracle engineering elapsed limit includes launch/planning/review pauses and
is separate from the policy START clock. STOP and the deadline signal the
existing owner, followed by bounded process-group cleanup. Input mutation,
single-use replay, unknown actions, child writers and partial commissioning
cannot silently qualify as a clean full success. Monitoring uses atomic JSON,
not another process's SQLite database.

The focused checks passed 41 tests in 18.706 seconds, including actual
subprocess stop/deadline and leftover-writer tests, the four native command
bindings, current R14 selection, configuration/Factory regressions, source
snapshot/manifest integrity tests and direct standing-team START. No model was
called. Actual native physical smoke runs are the next qualification step;
this entry alone is not a full physical witness.

The first actual CLI smoke launched each current minimum-arm Level 1 native
Oracle with a 15-second engineering elapsed limit and 10-second cleanup grace.
Transport, Mosaic and Dial produced stopped native reports without forced
termination. Transport and Mosaic retained unresolved in-flight actions rather
than pretending to have sealed them. None is a task success. Relay exposed a
native stop/recovery bug: its recoverable-error catch intercepted
`ReferenceStopped`, entered live repair and continued stepping until the
supervisor killed it. The original forced-stop directory is retained without a
fabricated report under `runs/engineering/main-integration-oracle-cli-20261101`.

The Relay entry now latches an owner stop and propagates terminal stop and
commissioning-boundary exceptions past recoverable repair. Ordinary forward
repair and process-violation rejection are unchanged. The focused stop/recovery,
Relay batch and unified Oracle group passed 37 tests in 14.800 seconds. A new
physical attempt is required to verify native shutdown; the first trial is
never resumed or rewritten.

The new Relay attempt from committed source `496f83a` stopped at the same
15-second limit without forced termination and wrote its native report. Its
36 actions and four unresolved arms are retained; it is interrupted, not a
success or a fully reconciled physical stop. All four current native entries
now have real CLI load/action/stop/report evidence. The retained stream audits
decoded 1,707 Transport, 2,065 Mosaic, 2,123 Relay and 1,765 Dial frames, including
three Dial appearance events. Every committed chunk checksum and timestamp
decoded correctly. As interrupted streams, none passed the complete-recording
gate; Transport/Mosaic/Relay also exposed a final event after the last cadence
pose. Original files were not rewritten.

Controlled Oracle shutdown now captures the actual final live pose without
another physics step, retaining `interrupted` status. Invalid final state keeps
its verified prefix and an explicit capture-error field. The closing regression
checks exact float32 pose retention, unchanged controls/physics state, event time
coverage and invalid-state handling. All 17 motion/process/monitoring/stop tests
passed in 2.428 seconds. Six initially missing-asset errors came from the motion
test fixture selecting the obsolete generated v2 scene; that format-generic
fixture now resolves the current released scene, with all codec/source/corruption
assertions intact. New physical recordings still need to verify the revised
closing path; an old interrupted recording cannot retroactively gain a frame.

An actual new five-second Transport execution from `24a4b41` verified the revised
shutdown path. It returned a native stopped report without forced termination;
all 759 motion frames, checksums and 70 events decoded, with 0.018-second maximum
sample spacing. No event extended beyond the final recorded pose. The complete-
recording audit still correctly rejects its `interrupted` status. Its original
source-scene hash is unchanged. Evidence and the separate read-only motion audit
are retained beside the earlier four-family smoke outputs.

## Manager prompts and remaining English migration

Both outer-manager prompts now use English. The Codex prompt uses the unified
one-profile configuration/CLI, explicit paid-stage authorization, frozen launch
settings, direct role startup and stopped collection. It explains combined
concurrency for separate profiles rather than implying one supervisor controls
all of them. The Claude prompt retains the native multi-profile engineering
entry, optional cost limits, explicit precheck estimates, unqualified status and
separate subscription qualification. Neither outer manager injects robot
strategies or claims its own model is the measured policy.

Legacy Transport startup text and Dial design display titles also use English;
physics, geometry and installed asset fingerprints were not regenerated.
The active `robofrontier/` and `prompts/` trees now have no Han characters.
This does not complete the repository-wide language gate: historical docs,
scripts, generated pages and some metadata still require migration.

The presentation/legacy Dial contract group passed all 22 tests in 2.766 seconds.
Its first run exposed missing legacy `facing-04` assets, not a new runtime error.
The synthetic policy group now builds its own isolated legacy XML/textures and
initial keyframe using the real generator and compiled model. Its preview and
runtime measurements remain explicitly synthetic; no physical qualification is
claimed. Tests retain every existing privacy, symbol mapping, role/fork return,
sampling and success-latch assertion, without installing/overwriting a published
scene or loosening production scene-path checks.

A combined regression run after these changes passed all 100 selected tests in
25.125 seconds, including the generated legacy Dial fixture followed by current
motion/Oracle tests in the same process. The temporary fixture roots were
restored correctly. This is the focused integration group, not the still-open
full historical discovery gate. Its log is
`/tmp/robofrontier-unified-oracle-final-regressions.log`. The policy/Factory asset
locks and scene files were unchanged, `main` remains at `c8b4137`, and none of
these integration commits has been pushed or merged into main.


## All-family current compressed-motion Factory acceptance

Four actual new native engineering recordings were imported through the unified
Factory CLI, using their own frozen inputs. A read-only all-frame audit checked
5,274 Mosaic, 759 Transport, 1,765 Dial and 1,716 Relay frames (9,514 total).
Imported float32 states and timestamps were bit-exact; original chunks, events
and assets were unchanged. Factory playback had zero dynamic/control dimensions
and performed no physics steps. Every mapped geometry's pose matched within
5.1e-15 metres, and all three Dial appearance events were retained and applied.

Each imported case also produced a three-frame, 320 x 180, one-sample Cycles CPU
preview. All four MP4 files were fully decoded and inspected. This validates
new compressed-motion background import, all-frame pose/appearance replay and
small CPU renders; it does not qualify complete videos, NVIDIA, Slurm or task
success. Mosaic is a two-goal partial commissioning recording; the other three
recordings retain their failed/interrupted status. Evidence is under
`runs/engineering/main-integration-factory-new-motion-20261101/`.

The first import exposed a CLI presentation defect: exporter progress and the
final result both went to stdout. The completed first import was retained.
The unified Factory entry now routes exporter progress to stderr and emits one
JSON result on stdout. A regression reproduced the previous parse failure;
subsequent native imports parsed successfully without regenerating Mosaic.

## Isolated operational physics and final failed-state retention

The committed `scripts.commission_transport_contacts` entry compares compiled
models before running a selected reference operation. Only declared contact-cone
and selected cylinder rolling changes are permitted. Candidate fingerprints
include the cone; old metadata and qualification are not silently inherited.
The released source and all declared asset hashes remain unchanged.

Actual side-cylinder pickup/lift, full-route handovers and socket operations
were compared for released, elliptic/30 mm and elliptic/1 mm variants. The 1 mm
candidate and released control both completed a local direct socket placement.
The maintained candidate command additionally verified post-release settling
and retained goal acceptance. Long multi-handover operations failed at different
finite planning/contact gates in all three variants; none qualifies a complete
Transport task or proves the candidate universally better. No candidate was
published as the new default. See [physics commissioning](../physics.md).

A five-second maintained trial retained a typed `ReferenceStopped` and its last
measured pose. A separate ordinary finite planning failure exposed an older
recording gap: its last event could follow the last cadence sample. Oracle
closure now captures the measured final state on an ordinary error as well as
an interruption, without stepping physics or replaying an action. Failed status
remains failed. The regression checks exact float32 final pose, event coverage
and unchanged live controls/state. A new actual failed trial retained all 1,126
frames and covered all 21 event timestamps. Original failed recordings were
never rewritten. Evidence is under
`runs/engineering/main-integration-physics-20261101/`.

The final focused integration group passed 106 tests in 28.045 seconds, including
motion, stop/recovery, all four Oracle entries, direct standing-team START,
configuration, Factory, snapshots and contact commissioning. These overlapping
regression groups are not a passing full historical discovery run.

## Fresh checkout and automatic asset repair

A new shallow local clone of committed integration source `caa341b` installed
with `uv sync --locked --extra oracle`, without copying the original environment,
authentication or assets. Bootstrap restored 3,467 files with zero reused files
from the pinned archive, whose SHA-256 was verified. Every expected scene/Panda
asset hash was then checked.

One ignored Relay label was deliberately moved out of this fresh fixture.
The ordinary unified `prepare` command restored it automatically and prepared
all 36 tasks. Every frozen input verified; defaults were Codex/Luna/high,
Adaptive, 36 concurrent slots, a 0.3-second initial launch interval and 86,400
seconds per task. On this Mac the explicit renderer was `native`. No environment
file, model calls or native model session transcripts were created. The actual
native doctor also passed CLI/sandbox, a 64 x 64 RGB render and a CPU physics
step. The clone remained clean.

The detailed receipt is
`runs/engineering/main-integration-fresh-clone-20261101/verification.json`.
This is local clean-checkout/bootstrap/preparation evidence, not GitHub branch
publication, provider compatibility, concurrent subscription refresh, 36-task
resource capacity, Linux NVIDIA or Slurm qualification. The policy and Factory
release locks remain unchanged, and integration has not been merged into main.


## Tracked English public atlas

The current public task atlas is now reproducible, tracked under
`docs/task-atlas/`, with editable templates under `web/task-atlas/` and the
`scripts.build_task_atlas` build/verify/ZIP entry. It regenerated all 72 top/front
JPEG views from the actual current 36 scenes at their initial keyframes, without
physics stepping or model calls. The package binds each file and generator to
release `b432892f`; it uses the same reviewed public contracts and terminal
scoring overlays as new policy runs. Raw private puzzles, Oracle solutions,
local paths and live runtime databases are excluded.

Eight artifact/public-contract tests passed in 2.710 seconds. They cover exact
current contract selection, private-field rejection, corrupted images/unlisted
files, stale completion semantics even with a rewritten payload hash, refusal to
overwrite an existing artifact, and deterministic ZIP creation/restoration with
byte-exact file checks. The generated site is 4,367,839 bytes and its ZIP is
2,998,888 bytes (SHA-256
`fdb1da0519f76ace7da90398128b7c2e385e1ce35c3d6009929fca88a43504df`).

Actual browser checks exercised combined family/level/arm/ID filters, empty
results, reset, front-camera switching and family-card navigation. A real
initial navigation bug, caused by a reset-button ID masking `form.reset`, was
found and fixed before delivery. The corrected 390 x 844 layout has one-column
task cards with no horizontal overflow; desktop layout and loaded images were
also inspected. Direct `file:` navigation is blocked by this browser tool's
protocol policy, so it is not claimed as an executed browser check. Structural
relative-link checks, self-contained JavaScript/CSS and actual ZIP restore are
verified separately. Evidence is under
`runs/engineering/main-integration-task-atlas-20261101/`.

The Pages workflow validates relevant pull requests and supports an explicit
manual publication, disabled by default. It uploads only the verified atlas;
there is no push-triggered deployment. Neither this workflow nor the current
integration branch has been published. The repository layout guide is now
English and distinguishes tracked code/atlas from ignored original recordings,
collections and historical local delivery layouts. Repository-wide English,
full editable promo and the other outstanding gates remain open.


The committed atlas source `c68becf` also passed all eight artifact checks in a
network-disabled Linux container (1.990 seconds), using an extracted Git source
archive and the previously installed pinned dependency environment. This is
Linux artifact/contract verification, not a newly built current policy image or
a provider/Slurm/GPU run. The first check allocated only 512 MiB to its temporary
source filesystem and failed while extracting the 654 MiB source archive; it
never reached tests. A new attempt with an explicit 1 GiB temporary filesystem
passed. Both logs are retained with the atlas evidence.


## English native-engine and evidence handoff

The Claude handoff, Codex/Claude component map, harness-alignment guide and
evidence-storage guide are now English. They preserve dated native CLI/provider
observations, costs, source commits and qualification limits, while separating
current direct START from historical READY. The stale first-Haiku preflight
paragraph no longer contradicts the later separately authorized Opus checks.
Budget defaults remain unset, structured recovery remains bounded, and no new
model/provider capability is asserted by translation.

The evidence guide now leads with the unified ZIP path and explicitly separates
ZIP extraction (compressed objects) from restoration (ordinary motion/session
files). It distinguishes the unified retention of stopped incomplete evidence
from the lower-level directory archiver's complete-by-default mode, and explains
that reversible image extraction retains image bytes. Historical PNG transcoding
is not silently described as lossless. Local links and English-only content
passed inspection; the documented offline Claude plan selected four tasks with
zero model calls. Current Claude discovery passed 164 tests in 31.704 seconds,
with seven opt-in checks skipped. This is not full repository or real-provider
physical qualification.

## Native Claude physical lifecycle and stopped-evidence recovery

On committed integration source `430d390`, five explicitly enabled native checks
passed in 53.429 seconds. They used the real Claude CLI 2.1.312 and real MuJoCo
worlds with a synthetic loopback model service, not a paid provider. Coverage
included an Adaptive observe/move/delegate-return operation, four simultaneous
physical owners for the four minimum-arm Level 1 cases, an unfinished Controller
finish followed by independent unsuccessful scoring, and SIGTERM finalization
of one and four actual owners. All tested physical owners exited, seals reported
no unresolved physical actions, and the world-stop assertions passed.

The opt-in command was:

```sh
ROBOFRONTIER_PHYSICS_SMOKE=1 ROBOFRONTIER_PHYSICS_BATCH=1 \
ROBOFRONTIER_PHYSICS_FINISH=1 ROBOFRONTIER_PHYSICS_SIGNAL=1 \
PYTHONPATH=tests:scripts .venv/bin/python -m unittest \
  test_claude_physics_smoke test_claude_parallel_physics_smoke \
  test_claude_finish_physics_smoke test_claude_signal_physics_smoke
```

The three retained stopped batches were then collected, archived to ZIP and
verified using the production collection/archive entries. This inspection did
not restart a native owner or call a model. All issues remain in their collection
manifests. Each batch is incomplete because interrupted native turns left
reported costs uncertain under these tests' explicitly configured budgets.
The four-owner signal batch also contains two delegates stopped before a valid
native session ID was bound. Their missing-session findings remain visible;
this evidence is not a claim that all delegates completed or that these are
cleanly accounted benchmark results.

| Retained test batch | Collection bytes | ZIP bytes | Recorded policy sessions |
| --- | ---: | ---: | ---: |
| Four-family Adaptive operation | 303,697,498 | 10,511,344 | 8 |
| Single-owner SIGTERM | 73,466,937 | 6,413,736 | 2 |
| Four-owner SIGTERM | 294,465,627 | 8,582,069 | 6 |

The four-family ZIP was extracted and restored into a new ordinary collection.
All 1,829 file payloads were byte-exact. All 4,928 recorded float32 states and
timestamps and all motion/appearance events were exact. First/middle/last
simple-background render samples matched pixel-for-pixel for all four cases.
No physics was stepped during replay. Original stopped batches and collections
were retained. The 96.5% storage reduction in this synthetic short-run fixture is
measured archive behavior, not an estimate for a long real-model batch.

The first local verification helper failed before collecting anything because
it imported a nonexistent `restore` symbol. It was corrected to the archiver's
actual atomic `verify(..., output=...)` restore API. No production code or source
evidence was changed to bypass verification. Logs, ZIPs and the detailed receipt
are under `runs/engineering/main-integration-task-atlas-20261101/`, including
`claude-native-physics.log` and `claude-evidence-verification.json`.

## English Factory handoff and historical boundaries

The Factory design/rendering guide, native Linux/Slurm handoff and dated server
acceptance are now English. All local Markdown links resolve. The current guide
leads to the unified configuration; historical V9/V10 sampling, cleanup policies,
performance, paths and scope remain dated rather than becoming new defaults.
The server guide separates policy execution from render-array execution and
explains that cloning remote main before integration publication does not obtain
these changes. No source scenes, release fingerprints, historical acceptance
receipts or published data locks were regenerated by this documentation change.

## Native Claude standing-team engineering implementation

The earlier permanent-Worker implementation gap is now resolved for engineering
execution. `StandingTeamPolicyHost` creates one independent native session per
frozen initial role, confirms every binding, persists one `direct_team_v3` START,
and then sends public role/task prompts. Controller + Worker preserves the
coordinating Controller's lack of arm authority and hierarchical message routes.
Worker-Worker has no Controller role and preserves direct peer communication.
Standing roles do not use Adaptive fork setup. The shared runtime, mailbox,
permission checks, safe action IDs and private evaluator are unchanged.

Unified preparation and the native engineering batch/run now accept both modes.
All roles share one run-local optional budget ledger. Unknown binds are not
repeated; uncertain wake dispatch pauses rather than resends. Team-wide
observation checks precede recovery or new wake dispatch, so a known unavailable
teammate cannot be hidden behind another role's capacity recovery. Stop cancels
all role turns and uses the existing physical seal. Existing Single/Adaptive
hosts and frozen READY-barrier inputs retain their paths.

Six new runtime-level tests exercise direct startup, independent identities,
authorized/forbidden routes, wakes, lost bind/send acknowledgements and recovery
with unknown teammates. The final selected configuration/engineering/direct-START
group passed 49 tests in 10.218 seconds. Full current Claude discovery then
passed 174 tests in 36.932 seconds, with eight opt-in checks skipped. These
counts overlap and do not replace the open full-repository historical discovery.

An actual Claude CLI/MCP loopback check exercised both modes with a synthetic
world, independent transcripts, a Worker action, messages and resumed wakes.
The first fixture incorrectly assumed that a coalesced user message's last
block identified the tool boundary, causing its scripted endpoint to loop on
inbox. It was replaced with a bounded per-role script. A second assertion
incorrectly required a wake to remain `sent` after its receipt had already
advanced it to `observed`; it now accepts both actual lifecycle states. Failed
logs remain retained. The corrected two-mode native check passed in 4.759
seconds and also passed inside the final full Claude regression run.

The explicitly enabled `test_claude_standing_physics_smoke` then exercised real
MuJoCo Transport A04-D1 under each mode for 20 seconds from START. Both obtained
an RGB image through MCP, completed one Worker A gripper action, exchanged
messages and continued bound sessions. Every role saved its work; none needed
READY. Both tasks reached their engineering stop, had sealed worlds with no
unresolved actions, and exited their physical owners. Both reported finished
engineering lifecycle with the shared ledger still tracking. This one test with
two topology subcases passed in 45.593 seconds. The model endpoint was synthetic;
there were no genuine provider calls and no task-solving qualification.

Both stopped batches were collected using the production collector. Collections
were complete, with all five Controller + Worker sessions and all four peer
sessions. Their ZIPs restored every file byte exactly; each recording's 1,230
states/timestamps and events were exact, and three simple-scene render samples
matched pixel-for-pixel without physics integration.

| Mode | Verified files | Collection bytes | ZIP bytes |
| --- | ---: | ---: | ---: |
| Controller + Worker | 524 | 76,810,027 | 7,082,657 |
| Worker-Worker | 516 | 76,470,926 | 7,018,607 |

Reading the restored host evidence through the common metrics exporter recovered
all five/four role keys, 14 tools and six completed CLI turns per test, with
complete synthetic usage fields. No synthetic token/cost value is a real
provider bill or caching measurement. Original batches and collections remain
retained. Receipts, failures, native logs, ZIPs, restores and replay reports are
under `runs/engineering/main-integration-task-atlas-20261101/` with the
`claude-standing-` prefix. These runs freeze the actual implementation inputs;
they were conducted before committing this implementation.

The README, unified CLI, component map and handoff now describe four native
engineering modes and link the new [standing-team guide](../engines/claude-code.md#standing-teams).
It explains task versus role concurrency, initial role counts, native names,
resource implications, clock semantics, recovery, evidence and reproducible test
commands. Formal scored Claude execution, genuine provider lifecycle/ability,
all-family/all-scale standing physical checks and cluster/subscription
qualification remain open; no release lock or production physics changed.

## Linux image and publication-boundary checks

The committed `849b5c1ea10502baebbc85d4265fc59a9e932440` source built successfully
through the unified container command. Image `robofrontier:849b5c1ea105` carries
that exact revision label; its image ID is
`sha256:51d42e40eab7bc0fbd4111103f2bd1cf1e2c8f62097319bc1d5530e5696a242b`.
The build used no model calls. A network-disabled Linux aarch64 container passed
native Claude CLI and actual RGB doctor checks with Mesa llvmpipe. This does not
qualify NVIDIA, x86_64, a real provider, Slurm or 36-task execution capacity.

Actual unified `prepare` commands in that image prepared four minimum-arm Level 1
cases for each engine/topology combination: 32 independent frozen runs across
Codex/Claude and Single/Adaptive/Controller + Worker/Worker-Worker. Every input
manifest verified; CPU rendering, JPEG observations, 24-hour public task limits,
0.3-second startup spacing and the corresponding direct-start protocols matched.
No model or physical world was started by these preparations.

The first Linux selected group exposed a process-loss test race: the fake worker
had entered before the supervisor's `starting` JSON publication. Killing the
supervisor then legitimately retained `queued` in its last published snapshot.
The test now controls the actual publication seam and exercises both sides of
it. Both cases preserve run/batch claims, report the lost supervisor, support
STOP, and refuse replay. All 18 engineering-batch tests passed on macOS and
Linux after this change. Production supervision was not altered.

The initial Linux full Claude discovery ran 175 tests with one failure and eight
skips. Its standalone native-fork test attempted resume immediately after an MCP
HTTP handler was entered, before the native parent history was guaranteed to be
written. Production delegation already waits for its recorded pending-tool
boundary in `fork_setup._pending_history`. The standalone test now also requires
its actual observe tool-use row in the native transcript before creating a fork.
The corrected native test passed on macOS (1.465 seconds) and Linux (1.340 seconds).
The initial failing logs remain retained; a complete post-fix discovery is still
required before claiming that whole Linux group passes.

The engineering index and Linux policy guide are now English and lead to the
unified CLI, pinned bootstrap, explicit render backends, node-local execution,
credential isolation and stopped evidence collection. Stale permanent-Worker
unavailability statements in the current architecture, Docker, Slurm and manager
guides were updated to the implemented engineering capability, retaining the
formal qualification boundary. Historical interfaces are explicitly Legacy.

Local evidence uses the `linux-`, `supervisor-publication-` and `fork-boundary-`
prefixes under `runs/engineering/main-integration-task-atlas-20261101/`. Linux
post-fix tests used the committed image with only the identified test files
replaced inside disposable containers; no production image file or original
run evidence was overwritten. Source changes will need a new committed image
for exact-revision final acceptance.

## Exact-revision Linux native standing acceptance

After the test-boundary corrections, source
`b0129eb665918c9353dfa6e52ccf31941ee55a87` was committed and built through the
unified container command. Image `robofrontier:b0129eb66591` has that exact source
label and image ID
`sha256:ead76e49acd4898218dabaa075642d806a3d83491ec2767d709b01075d4515fb`.
Full Claude discovery ran 175 tests, with zero failures/errors and eight skips,
on both macOS (41.540 seconds) and the network-disabled Linux image (31.715
seconds). These are 167 executed passing checks per platform, not 175 independent
provider or physics qualifications. The corrected Linux run used the committed
image unchanged, without the earlier test-file overlays. One preceding command
used a mistyped image tag and failed before container creation; its separate log
is retained and does not count as a test run.

The opt-in standing-team physical smoke also passed in that exact Linux image:
one test/two topology subcases, 45.552 seconds. Each used real MuJoCo Transport
A04-D1 with OSMesa/llvmpipe, the native Claude CLI/MCP, and a synthetic loopback
model. Both bound distinct sessions before START, delivered an actual image,
completed Worker A's gripper action, exchanged messages, resumed bound roles,
and stopped after 20 seconds from START with sealed worlds, no unresolved action
IDs, and exited physical owners. The test container exited zero without OOM.
There were no genuine provider calls and no claim of task-solving success.

After that container was authoritatively stopped, its test data was copied as a
23,674,591-byte gzip transport tar. A separate network-disabled container restored
the unchanged original absolute paths onto local storage, then ran the production
collector, ZIP archiver, atomic restore, and replay verifier. No live database
was read across a container boundary. Both collections were complete:

| Mode | Native role sessions | Verified files | Motion frames | ZIP bytes |
| --- | ---: | ---: | ---: | ---: |
| Controller + Worker | 5 | 527 | 1,179 | 7,076,133 |
| Worker-Worker | 4 | 516 | 1,235 | 7,019,079 |

Every collected file restored byte-for-byte. All states/timestamps and appearance
events matched exactly; three sampled simple-scene images per recording matched
pixel-for-pixel without physics integration. The exported sample JPEGs were also
visually inspected. Both stopped containers and the transport copy remain
retained. The verified ZIPs, hashes, replay samples/reports, and receipt were
copied out only after the verification container exited zero. They are under
`runs/engineering/main-integration-task-atlas-20261101/linux-standing-verified-b0129eb/`.
Logs use the `linux-claude-regressions-b0129eb-exact`,
`linux-standing-physics-b0129eb`, and `linux-standing-evidence-b0129eb` prefixes.
These checks do not establish Factory replay of these particular new streams,
NVIDIA rendering, subscription refresh, Slurm, x86_64, or real-model capacity.

## English task and native execution guides

Transport, Mosaic, and BEST5 Dial specifications are now English. They preserve
geometry, numerical tolerances, historical qualification counts, edit/video
provenance, and native script identities while distinguishing new policy
terminal scoring from unchanged strict historical Oracle reports. Mosaic clearly
selects R14/81 mm for new policy and unified Oracle runs; original R13 recordings
keep their colors/source. Dial explicitly retains unlock-once completion and
separates the device's READY indicator from harness startup. Historical
Unicode-named artifact basenames are represented with exact JSON escapes rather
than renaming original recordings or dropping their location information.

The native Codex guide now leads to the unified Luna/high API defaults while
labeling the retained native entry's Astra/parallel-9 defaults separately. It
explains task-isolated homes, optional capability READY, safe request identities,
JPEG observations, compressed motion, explicit render selection, API versus
subscription qualification, and independent offline video quality. Its provider
catalog table remains an explicitly dated 2026-10-28 snapshot, not a new ranking
or availability assertion. The official OpenAI configuration and app-server
references were fetched to confirm Responses-only provider configuration and
source-kind filtering; canonical links are retained in the guide.

The original four-family Oracle integration guide is now an explicitly dated
English acceptance snapshot. Its 1,008-test result, asset scan, 48 pre-existing
broken links, 36 source recordings, timing observations, and unfinished work
remain historical facts rather than claims about the current larger suite.
These documentation changes do not modify the asset lock, physics, public
policy templates, evaluators, source motion, or archived compatibility hashes.

## Full-length Factory movie audit and remaining editorial work

The preserved `factory-promo-r14.mp4` under the original Factory worktree's
`outputs/robo-factory/promo-r14-427210/` was inspected without modification. Its
134,315,571 bytes have SHA-256
`9c83e1d0ad17c3f6d4a7ed4b7d806322160f5d61d1e58e2471f0d3b300b86f96`.
ffprobe confirms H.264, 1920 x 1080, 30 fps, 6,315 frames, and 210.500 seconds.
Four derived inspection JPEGs at 0, 16, 66, and 162 seconds are retained in
`runs/engineering/main-integration-task-atlas-20261101/promo-audit/`, with the
media receipt. Opening and Dial samples were visually inspected.

That delivery folder contains the full movie and a preview, not a complete
editable editorial project with title/subtitle sources and a source-bound camera
plan. A filename containing R14 does not establish that every source scene or
contact parameter matches the current release. The existing full movie remains
historical evidence; it has not been relabeled as a newly rendered current
release. Native promo generation already exports camera plans, pose frames,
source clock traces, reset events, and hashes. The remaining work is to expose
editable English titles/subtitles and camera controls through a reproducible
source-bound project and verify the full-length deliverable. This audit is not
that implementation or final-video acceptance.

## Editable English Factory project and media verification

The source-bound full-tour project is now tracked at
`assets/robo_factory/tour-project.json`, with 73 camera waypoints, five English
title cues, 34 subtitle cues, and the existing licensed Barlow font. It spans
210.5 seconds/6,315 frames at 30 fps. Task subtitles use the actual inspection
camera/task metadata. Camera positions, targets, FOV, timing, SRT text and style
are editable; camera edits do not implicitly retime existing subtitle tracks.
The [editorial guide](../factory/editorial.md) documents the complete workflow.

Unified and native commands now expose `factory project`, `prepare --project`,
and `edit-video`. New promo plans generate or copy the complete project into a
frozen plan. Preparation publishes atomically; incomplete 36-station inputs or
invalid edits cannot publish a partial plan. Native pose export consumes the
frozen camera plan. Cycles retains its raw movie; the compositor retains the
editable project and generates a captioned movie, source/project/output hashes
and a full-decode report. Completion requires both raw and captioned media,
matching project bytes, original source movie identity, dimensions, rate and
frame count. A changed camera/subtitle during rendering, changed retained
project, missing editorial result, or compositor failure prevents successful
completion. Legacy plans without editorial inputs retain their raw-media
contract; they are not implicitly upgraded.

The final Factory regression suite discovered 60 tests on each platform:
55 executed and passed, five historical generated-data tests skipped. macOS
took 9.495 seconds; Linux aarch64 took 4.674 seconds. The Linux run used the
existing `robofrontier:b0129eb66591` dependency image with the current checkout
mounted read-only at `/work`, a writable temporary filesystem, and networking
disabled. This is not a claim that that older image contains the new source.
Checks include the actual FFmpeg/libass CLI path, source immutability, pixel
changes in title and subtitle regions, portable font/project retention,
preparation rollback, attempt failure/no-seal behavior, changed-during-render
rejection and both new and legacy completion paths. The first fixture attempt
failed because its new synthetic Mosaic task omitted R14 scale metadata; that
fixture was corrected without weakening production bundle validation.

The checked-in project also completed an actual unified `prepare`/`run`/`status`
round trip against the pinned 36-station R14 bundle, using CPU Cycles at
320 x 180, one sample and an explicit 0.1-second preview. All three raw and
captioned frames were decoded, sealed and input/code hashes verified. Status
returns both final `video` and original `source_video`. This verifies a small
current-source render, not full-length current-source GPU/Slurm rendering.

The preserved historical full movie was separately composited without another
Cycles render: 1,920 x 1,080, 30 fps and all 6,315 frames. Output is 133,064,566
bytes, SHA-256
`86f0111abf2c94c7d508f223d841ffdf2541a955882dd341f133798d0e84a876`.
Full decoding passed, and inspection frames at 0, 16, 66 and 162 seconds were
viewed. The original SHA-256 remains
`9c83e1d0ad17c3f6d4a7ed4b7d806322160f5d61d1e58e2471f0d3b300b86f96`.
The full video's report explicitly qualifies text/media processing only; it
does not establish that this historical movie depicts current physics or its
project's declared scene. It is not given a current-source render-plan seal.
The complete new-source full-length delivery gate therefore remains open.

Logs, projects, raw/final preview media, full edited historical movie, inspection
JPEGs and `factory-editorial-acceptance.json` are retained under
`runs/engineering/main-integration-task-atlas-20261101/`, using the
`factory-editorial-` prefix. No model calls or physics steps were performed.

## English compatibility dashboards and configuration index

Three compatibility dashboards now use English labels, status/error text and
locale formatting. The shared-world view displays Controller while retaining
the historical `Coordinator` role ID for routing/sorting. The two-session pilot
is explicitly labeled Legacy and keeps its original READY/START experiment gate;
it is not documentation of the new direct-START benchmark protocol. Existing
message/event payloads and archived snapshots are not rewritten.

All three inline JavaScript programs parse with Node. The existing four mailbox
pilot lifecycle/snapshot tests passed in 0.207 seconds. An initial text scan
caught one untranslated camera filter label, which was corrected before the
final parse/English check. These checks do not claim new browser visual or
native-engine qualification. The configuration index is now English and clearly
separates the unified TOML, engine catalogs, asset locks, native baseline JSON,
frozen Factory inputs and editable video project. These changes do not modify
physics, asset fingerprints, task selection or startup behavior.

The remaining tracked-text English inventory is 133 files/126,853 Han characters,
recorded in `english-inventory-after-editorial.json`. Repository-wide English
migration remains unfinished.

## Luna/Slurm handoff migration and remaining legacy entry closure

The Luna CPU and multi-model handoff guides are now English and lead to current
unified commands. They distinguish the unpublished integration from the original
Codex/Luna branches, task-isolated API state from the native Luna batch home,
unified parallel-36 defaults from native parallel-9 defaults, START task time
from allocation time, explicit paid preflight from model-free preparation, and
stopped evidence from unsafe cross-filesystem live SQLite inspection. Historical
source commit, CLI pin, archive name/hash, offline bundle behavior, multi-profile
Dial comparison, native compatibility entries, and worktree/PR instructions are
retained with clear scope. They do not claim current provider prices or model
compatibility from the dated research tables.

Review found that `scripts/slurm_luna_l3_max_test.sh`, unlike the already retired
general Luna sbatch entry, still created `runs/tmp` in the shared checkout and
automatically ran paid preflight/execution. That remaining unsafe legacy path
now exits with migration instructions before writing runtime state. Both retired
scripts are regression-tested by executing them with synthetic Slurm variables
in an empty directory: they exit 2, describe the node-local replacement, start
no model/simulator, and leave the directory empty.

The equivalent new explicit selection is
[`configs/examples/luna-l3-cpu.toml`](../../configs/examples/luna-l3-cpu.toml):
Luna/high/adaptive, CPU rendering, parallel 4, four maximum-arm Level 3 cases,
3,600 seconds per task and a 7,200-second Slurm allocation ceiling. The actual
unified plan confirmed Transport 12, Mosaic 8, Relay 16 and Dial 16 arms, with
zero model calls and no simulator. The sample retains the existing scene
qualification labels and does not change the 36-task/24-hour root defaults.
Operators must review inherited CPU/memory/site resource requests before queueing.

The combined Slurm/Luna group passed all 26 tests on macOS (0.736 seconds) and
Linux aarch64 (0.286 seconds). Linux used the existing dependency image and the
current checkout mounted read-only, with networking disabled. Both shell scripts
and all shell blocks in the rewritten guides parse. Local Markdown links resolve;
the Level 2 minimum-arm values were independently checked against current task
metadata. Logs and the four-task plan are retained under the existing engineering
evidence root with `luna-slurm-migration-` and `luna-l3-unified-` prefixes.
This remains offline submission/staging acceptance, not real Slurm allocation,
provider capacity or NVIDIA qualification.

## Historical loop plan and editorial guide alignment

The three-arm 2026-10-20/21 work-loop plan is now English and explicitly Legacy.
It retains all trial outcomes, retired evidence locations, stock/origin rules,
19-operation/38-phase/16-slot resource result, bottleneck assumptions, authority
boundaries, deferred features and acceptance stages. Its READY/START gate is
clearly historical and superseded for new direct-START runs. Old coordinating
role IDs are not renamed in evidence. The root README, native Factory guide,
Factory overview and unified configuration guide now distinguish the implemented
editable project from the still-open full newly rendered current-source movie.
They also distinguish raw-frame cleanup after successful Cycles encoding from
a subsequent subtitle failure, which retains the raw movie and failed attempt.

English scans and local Markdown link checks passed for these edited guides.
No execution semantics, asset fingerprints or archived evidence changed. The
remaining tracked-text migration is 130 files/119,355 Han characters, captured
in `english-inventory-after-slurm-guides.json`; this remains an open release gate.

## Dated provider research translation

The four-profile pricing and eight-provider compatibility research snapshots are
now English. Both retain the original 2026-10-28 review date, distinguish recorded
figures from current account access/pricing, and point to current handoff commands.
The compatibility guide distinguishes the raw Codex catalog seed's lite/code-mode
fields from the native launcher's effective Responses/function-tool overrides.
It does not claim that offline configuration proves real-provider image/tool,
compaction or fork compatibility.

The verification receipt `english-provider-snapshot-verification.json` under the
existing engineering evidence root compares the edits against their HEAD source:
all 14 and 41 distinct source URLs are preserved, as are numeric cells in the
price, quota and funding-tier tables. Both documents are free of Han text, local
Markdown links resolve, and `git diff --check` passes. This is a translation of
historical research, not a fresh vendor-price audit or a paid preflight. No model
profile, asset fingerprint or experiment was changed.

## Legacy transport catalogs and generated startup guides

All three retired Cube Transport series (v2 spheres, v3 cones, v4 cylinders)
now have English guides, seed-0 catalogs and 30 English startup guides. They are
explicitly separate from the current 36-case suite. Review found that the old
v2/v3 reproduction instructions misleadingly described commands as generating
those old shapes, although the maintained generator now targets v4 cylinders.
The guides now identify that boundary, original generator archives, ignored
run-report locations and the difference between historical recorded claims and
new qualification. The generator's catalog text and startup title are English
so regeneration preserves the language and Legacy designation.

The source comparison verified all 30 displayed orders, 255 semantic/numeric
table rows, 30 demand histograms, and every startup guide's station stock,
numeric fields and adjacency. An independent output directory generated all
ten sizes (3-12 arms) and 30 seed tasks. Every task JSON equals the existing
source task; all actual MuJoCo load/support/spacing/endpoint-IK/initial-contact/
one-second-settling checks passed. Generated cylinder startup/catalog sections
match the translated checked-in guides. No previews were rendered, and none
of the 5,169 checked source files under configs/benchmarks/vendor changed during
generation. Original historical manifests and current release fingerprints were
not rewritten.

The original checkout's ten-test Cube Transport group produced eight passes
and two errors because ignored historical `assets/label_A.png` files are absent.
The same ten tests passed without skips against the newly generated isolated
scene fixture, using original preview JSON metadata for its camera/label tests;
this does not claim new preview-image rendering. Neither outcome qualifies old
cone/sphere transport, multi-arm dynamics or current-suite physical candidates.
Receipts, raw failure log, generated fixture and successful derived-fixture log
are retained with the `legacy-transport-` prefix under the existing engineering
evidence root. No model calls were made.

The remaining tracked-text migration is 91 files /
97,564 Han characters, recorded in
`english-inventory-after-legacy-transport.json`. This remains an open release gate.

## Full released-case preparation matrix

At source `abd700e`, the actual unified CLI prepared all 36 released cases for
each combination of two engines (Codex/Luna and Claude/Haiku) and four topologies
(Single, Adaptive, Controller + Worker, Worker-Worker): eight batches / 288 runs.
Every run passed frozen input verification and the complete frozen policy-release
projection check. Per-family counts are nine and per-level counts twelve in
every batch. Role counts/arm authority match each topology, including maximum
arm counts; Single/Adaptive use direct_controller_v2 and both standing modes
use direct_team_v3. Each effective config retains parallel 36, startup interval
0.3 seconds, START task limit 86,400 seconds, startup timeout 600 seconds, high
effort and task-scoped API runtime settings. Observation settings are
jpeg_896x560_q85 with realtime video disabled. Public textual inputs across all
288 prepared runs contain no Han text.

These checks ran on macOS with CPU observation settings, without starting a
simulator, model process, API request or runtime rendering backend. They prove
preparation coverage, not 288-task execution, API quota, GPU readiness or
physical completion. Claude batches deliberately remain prepared_not_qualified
with execution_available false; Codex batches remain prepared_not_started.
An initial verifier wrongly expected the Codex batch status for Claude. Its
assertion stopped after preparation, not during a trial. The corrected verifier
reused and verified existing frozen batches, then prepared the remaining ones;
no worlds or model sessions were restarted. Both logs and the complete final
`full-preparation-matrix.json` are retained under the engineering evidence root.

## Historical Claude migration proposal

The 2026-10-28 native-harness proposal is now English and clearly historical,
with links to current implementation/qualification guides. It preserves all
23 original source URLs, model IDs, baseline commit, recorded CLI versions,
stages A-I, eight implementation progression conditions and original section
numbering (including its missing section 13). It distinguishes proposed paths,
recorded third-party integration claims and obsolete READY gating from current
commands/direct START. It does not relaunch the old proposal, assert current
provider access, or make a new paid preflight. Local Markdown links resolve;
`english-claude-plan-verification.json` records the source comparison.

Remaining English migration: 90 files / 91,957 Han
characters, recorded in `english-inventory-after-claude-plan.json`.

## Container help must not execute work

While building the current committed delivery image, the command
`container build --help` unexpectedly performed the build. The resulting image
`robofrontier:aad3cf2691ce` is a successful source-frozen build of
`aad3cf2691cef90f41512b28b515deae1fb660c7`, image ID
`sha256:462afc173c44b0eb51ce1e61a92ec0913853fe24a8337442e06a6e1759085629`.
It restored all 3,467 policy asset files against the pinned archive/release;
no model calls occurred. This image predates the help fix described below.

A deterministic regression reproduced the bug in 0.025 seconds: nested help
reached the Docker subprocess boundary. Differential probes showed that top-level
container help stayed local while nested build help and unknown build flags
were forwarded. Root cause: REMAINDER parsing passed those tokens unchanged,
and the wrapper's parse_known_args settings extraction ignored them before
unconditional build dispatch. The existing native argument-parser construction
is now reusable; nested native commands are validated with that same parser.
Build accepts no arguments, and auth has local wrapper help plus early action
validation. Both the CLI boundary and direct Python wrapper validate before
Docker operations; the CLI does so before configuration loading. Authentication
options still reach their native CLI unchanged, and no policy protocol changes.

The regression now covers build/native/auth help, nonexistent config with help,
misspelled options, missing arguments and direct wrapper invocation without
Docker execution. The actual installed CLI also returned only help for a missing
config path. The combined container/configuration suite passed 26 tests on
macOS (5.588 seconds) and Linux aarch64 (12.249 seconds). Linux used the
aad3cf image's dependencies with current source mounted read-only, no network,
and tmpfs test fixtures; this is not yet a new-source image build. Before/after
logs, differential receipt and actual help output use the `container-help-`
prefix under the engineering evidence root.

## Current-source Docker and Linux preparation acceptance

The committed help fix was built using the production git-archive wrapper as
`robofrontier:8b47962499c1`, source
`8b47962499c169921f890dd931566a925882ba1f`, image ID
`sha256:bc87fe3e1e63fdbe9d527a1d02e84e9d18672f100dc19078d06111afd7d4261d`.
Unlike a dependency image with host code mounted, the subsequent Linux checks
ran the code contained in this image. All eight fresh combinations of engine
and topology prepared/verified all 36 cases: another 288 preparations, with
no model calls, no simulation and no public Han-text findings. Source identity,
per-case release projection, role allocation, 24-hour START clocks, JPEG settings
and defaults passed. The arm64 container exited zero without OOM. Its verified
receipt and state were copied after it stopped; the disposable model-free
preparation container was then removed. Existing benchmark containers and real
session evidence were not touched. No x86/NVIDIA/provider qualification is
implied. The additional CLI consumer suite passed 33 tests on macOS (10.210 s)
and 33 inside the new image (4.231 s), covering evidence ZIP, Factory/editorial,
portable benchmark and diagnostics. The initial Mac invocation lacked the tests
fixture import path; its two import errors are retained, followed by the
correct PYTHONPATH invocation and passing results.

## Factory Metal preview and user-deferred full render

A fresh complete check verified all 123,198 files of the pinned 36-station R14
Factory bundle and identified Blender 5.1.2 / Apple M5 Pro, 16-core Metal GPU.
The actual unified 1920×1080, 64-sample, three-frame Metal preview completed
with the checked-in English project, full raw/captioned decode and complete
sealing. The inspection JPEG was viewed: opening title and subtitles are legible.
Cycles took 28.442 seconds including setup/encoding; warm frames averaged
6.673 seconds. That opening-view measurement is not a reliable whole-tour ETA.

The full 6,315-frame plan was prepared and launched at lower CPU priority.
The user then explicitly requested stopping new rendering and publishing the
original movie instead. Only the verified owner of that exact plan received
SIGTERM; it stopped its child, retained the attempt and exited 2. The attempt
is interrupted with signal 15, no running receipt and no complete seal. It is
not counted as a completed new movie. New full rendering is now deferred by
user instruction, while the overall integration continues.

The original full movie was rehashed, fully decoded and published unchanged at
[Original Factory tour](https://github.com/changxuanfan/RoboFrontier/releases/tag/factory-tour-media-20261102).
It is 134,315,571 bytes, 1920×1080, 30 fps, 6,315 frames / 210.5 seconds; SHA-256
`9c83e1d0ad17c3f6d4a7ed4b7d806322160f5d61d1e58e2471f0d3b300b86f96`.
The release includes the original MP4, extracted JPEG poster, media receipt and
checksums. All four GitHub asset digests/sizes were checked against local files.
The media release does not replace the latest Factory data release or change
asset locks. It is explicitly historical and does not establish current-scene
equivalence, model success or physics qualification. README has a linked poster;
its integration-branch edit has not been merged into main. Evidence prefixes are
`factory-metal-`, `factory-editorial-metal1080p-`,
`factory-editorial-current-full-` and `factory-video-`.

## English engineering notes and remaining checker findings

The MuJoCo/Panda interface notes, harness-coverage guide and communication
research notes are now English. The interface review retains all 16 source
URLs, seven numeric joint-range rows and six section numbers, and distinguishes
interactive reset advice from prohibited policy-world restart. The harness guide
labels coverage rather than claiming a green release and distinguishes legacy
READY tests from current direct START. The communication review retains all five
paper links and explicitly labels protocol suggestions as hypotheses. These are
local translations, not fresh upstream/vendor research. Source comparisons and
local Markdown links passed; no motion, asset fingerprint or policy protocol was
changed.

A broader protocol-only checker ran with MuJoCo entrypoints explicitly blocked.
It is **not green**: 187 Python tests had two errors, and link checking found one
retired historical output link. Zero assertion failures were reported; details
remain in `protocol-acceptance-after-container-help.json/.log` for diagnosis.
Its dispatcher scenario count is still a hardcoded historical 23, while the
actual JavaScript suite reports 24; do not treat that metadata as a fresh count.
No failures are hidden or waived by the narrower passing CLI suites.

Remaining English migration: 87 files / 87,491 Han
characters (`english-inventory-after-engineering-notes.json`).

## Portable protocol acceptance and English operations cleanup

The protocol-only checker initially failed for two reproducible fixture reasons:
legacy Beam freezing required missing ignored textures, and the spring-Dial
fixture compiled a model despite the no-physics guard. Those groups now use
self-contained synthetic XML/previews and FakeWorld measurements. They retain
all task validation, input freezing, role routing, scoring and privacy assertions;
no real Panda/contact qualification is inferred from their primitive fixtures.

The original dispatcher program actually invoked 28 top-level scenarios while
its console label claimed 24 and the checker hardcoded 23. The runner now counts
its executed scenario list, and the checker requires/parses that result. No
scenario was removed. Three historical absolute Mac links also appeared valid
only because those artifacts existed on the developer's machine. They are now
explicit retired local references. Link validation rejects absolute paths,
outside-checkout traversal and symlink escapes even when those targets exist.
Two regression tests cover portable encoded/anchor/external links and those
machine-dependent false positives.

Current Mac and Linux runs both passed 199 Python protocol tests with zero
failures, errors or skips, all 28 dispatcher scenarios, the remaining JavaScript
checks, syntax checks and portable documentation links. Linux used the pinned
8b47962499c1 dependency image with this checkout mounted read-only, network
blocked, and writable temporary test directories; it is a mounted-source check,
not a newly built image qualification. Bypassing the normal image entry initially
left its TMPDIR uncreated, then a noexec tmpfs prevented a synthetic Python helper
from executing. Both failed invocation logs are retained. Setting TMPDIR to the
existing executable test tmpfs resolved that test-launch configuration without
changing production code or omitting tests.

Evidence is in `runs/engineering/main-integration-task-atlas-20261101/`:
`protocol-fixture-reproduction.log`, `protocol-portable-final-mac.json`, and
`protocol-portable-final-linux-exec-tmp.log`. The full historical discovery suite
and real native/provider/physics/cluster acceptance are separate gates.

OpenLux operations, Relay task/replay guides, the historical README and selected
archive redirects are now English. The OpenLux guide uses the actual unified
TOML/CLI, explicit paid preflight, task-local homes and maintained Docker/Slurm
flows rather than the old batch-shared and privileged-container examples. The
Relay guide distinguishes terminal completion from stricter historical process
and Oracle requirements. Historical frame rates, source-time mapping, exact
track schemas and all Relay media command blocks were retained. Original
external URLs in the ten translated documents were checked for preservation.

Five Unicode test fixtures now spell their non-ASCII samples with Unicode
escapes; parsed Python ASTs are identical to their predecessors. Their 62-test
regression group passed. The literal-Han inventory dropped from 87 files/87,491
characters to 72 files/81,751 characters. This is progress toward the English-only
repository, not a claim that the remaining history, scripts and asset UI are done.
No model calls, new scene renders, release physics edits or asset-pin changes
were made for this work. The original Factory video remains the published media;
its deferred replacement was not restarted.

## Atlas presentation refresh with preserved capture evidence

The static atlas now describes all four native Claude engineering entries while
keeping scored qualification closed. No scene rendering was used to update it.
The new `build_task_atlas refresh` command accepts an existing publication, a new
output path and its full source commit. Before writing, it compares the exact
incoming manifest and original generator/templates with immutable Git objects,
then validates every existing payload, JPEG and current public contract.

A refreshed v2 manifest binds the new browser presentation to current sources and
retains the first v1 capture manifest, its SHA-256 and source commit. Its images,
per-case JSON, aggregate task JSON, release, backend and capture metadata must
remain identical. Verification and ZIP delivery do not need historical Git
objects or an OpenGL context; creating a refresh does need the source history.
The Pages validation checkout now fetches that history for regression fixtures.
There is no Pages deployment or automatic publication change.

All 72 original JPEGs and 37 task JSON records remained byte-identical. The
original publication was verified at commit
`5c33ea3f14a3e833535e9f88f4db00a10a888267` before template edits. Only its HTML and
manifest changed in the tracked artifact. Total artifact size changed from
4,367,839 to 4,381,495 bytes, retaining the original capture proof. The offline
ZIP is 2,999,909 bytes, SHA-256
`89e7b3c6a7b28871befd034e6d7ce14054ebf77d61efd9109083189722d452ae`.

All 12 atlas tests passed on Mac (7.057 s) and Linux (6.779 s), including actual
committed-publication refresh, explicit no-model/no-renderer guards, original
input retention, overwrite/nesting rejection, tampered/rehashed image rejection,
private-field exclusion, current contracts and deterministic ZIP restoration.
Linux used read-only current source and only the Git objects/refs/HEAD required
for the immutable publication fixture; it copied no credentials and made no
network calls. The normal current-source artifact verifier also passed.

Evidence is under `runs/engineering/main-integration-task-atlas-20261101/`:
`atlas-refresh-before.log` records the missing-interface reproduction;
`atlas-refresh-regression-mac.log`, `atlas-refresh-regression-linux.log`,
`atlas-refresh-publication-verification.json`, and
`task-atlas-refreshed-offline.zip` record the completed checks and delivery.
This is presentation/provenance acceptance, not new task physics or provider
qualification. The complete Factory render remains user-deferred.

## Saved-run viewer and legacy display language

The optional local policy batch viewer now reads only existing batch JSON, saved
runtime snapshots and recorded images/video. The previous implementation could
instantiate RuntimeStore and create a SQLite database just by opening the page;
an actual HTTP fixture reproduced that behavior before the change. The new
viewer opens no SQLite database, performs no writes and starts no model or world.
It supports both engine metadata layouts, repeated cases across profiles, stale
or absent snapshots, JPEG MIME types and existing-video Range requests. Its UI
labels the batch state as saved metadata, not proof of a live process. Usage and
namespace limits are documented in `docs/local-viewer.md`.

Seven legacy analysis/generation/viewer scripts also have English display text.
Their non-text Python ASTs are unchanged; no generator or renderer was executed.
The literal-Han inventory is now 64 tracked files / 80,990 characters. The
English-only release gate therefore remains open.

Seven HTTP/viewer regressions and four mailbox regressions passed after the
final UI wording change. Earlier full protocol runs with the viewer module
included passed 206 Python checks on both Mac and Linux, plus 28 dispatcher
checks. Evidence is under
`runs/engineering/main-integration-task-atlas-20261101/`; these are offline
protocol checks, not new model or task qualification.

## Oracle terminal recovery and final local regression

New schema-4 Oracle preparations freeze an explicit execution protocol with
`task-reference` terminal semantics; `strict-process` remains available. Old
schema-1/2/3 configurations and frozen executions keep their original shape and
rules. Source scenes, score tolerances, asset locks and historical reports are
unchanged. Reports expose task completion, process cleanliness, resolved
execution, valid physics and strategy completion separately. Privileged Oracle
work remains distinct from a scored model trajectory.

The recovery audit removes historical-process vetoes from task-reference
Mosaic/Relay paths, distinguishes current support from old drop/custody flags,
and uses measured separation instead of preferred aperture as a release fact.
Transport retains force-off release phases across rejected exits. Its empty-hand
screen requires real upward board support, compares identical geometry-distance
queries, bounds finger contact across the whole phase and rejects new/worsened
penetration without falling back to insertion tolerance. Final scoring and normal
arm/world guards are preserved. See [recovery boundaries](../oracle/recovery.md).

The previously failing Linux Dial pressure-requalification test was reproduced
unchanged. Nominal 20 mm regrasp failed at a measured 26.709 mm aperture. At that
boundary the tilted stem's projection on the fingers' closing axis was 21.906 mm.
Changing only the requested grasp width to the measured projection made the
original physical test pass on macOS and Linux. The 5 mm actuator tolerances and
actual bilateral airborne-support checks remain unchanged. Invalid projections
still require geometry review. This fixes a reference geometry assumption, not
the task evaluator or the physical drive's acceptance thresholds.

The audit also reproduced a permanent historical-uncertainty veto after original
terminal feedback was known. Resolution now matches the original call ID and
robot without editing the uncertain history. Adapter acknowledgement fences need
explicit execution-owner review of the adapter's own terminal result; no pending
sequence is replayed. Legacy/strict behavior is retained. A separate regression
reproduced partial-start acknowledgement loss escaping the action log; attempted
IDs are now recorded as uncertain and unissued calls as `not_started` before
another batch ID can be allocated. Invalid physics blocks new actions.

The final selected group passed 391 tests on macOS (73.111 seconds) and Linux
aarch64 (88.236 seconds), with no failures, errors or skips. It covers the four
Oracle families, original physical Dial fault injection, real Panda owner-review
and stop feedback, archived-pose socket screening, configuration versions,
workflow supervision, Factory and source snapshots. These are overlapping
engineering checks, not full task or real-provider qualification. Linux used
the existing `8b47962499c1` dependency image with current source mounted read-only,
network disabled and local temporary fixtures; it was not a newly built image.
The first concurrent Linux run had two source-asset read-permission errors;
that failed log is retained, followed by the complete passing isolated run.
Both platforms additionally passed 235 protocol-only Python tests and 28
dispatcher scenarios, with physics entrypoints blocked. Linux's first protocol
invocation lacked writable fixture/bytecode directories and failed before a
complete report. A new invocation used local executable temporary directories for
the legacy fixture and Python cache while retaining read-only source; it passed
without changing tests or production code. Both invocation logs remain retained.

An independent new controlled Transport probe, `archived-pose-exit-v9`, completed
three withdrawal actions and 8.040 simulation seconds, established separation
and retained original acceptance of the selected material. Execution was resolved,
physics valid and the scene hash unchanged. It explicitly reports the full
24-goal task incomplete. Initialization used archived state 73 and new holding
references; this is neither exact episode continuation nor a new physics-release
qualification. Earlier attempts remain unchanged.

Evidence is in `runs/engineering/main-integration-oracle-final-20261102/` and
`runs/engineering/oracle-terminal-recovery-20261102/`. No paid model calls or new
video rendering were performed. Full repository, real hardware/provider and
publication gates remain open.

## English archival and robot-interface notes

The 2026-10-30 evidence synchronization receipt, 2026-10-19 VLA action-space
review and 2026-10-22 robot-interface audit are now English. Their dates, every
source URL and numeric value remain preserved. The force-interface audit keeps
the pre-grasp-v2 findings separate from the later implementation update; the
archive receipt keeps its historical test counts, interrupted Claude status,
pixel/float32 scope and then-unverified deadline/Slurm boundaries. No vendor
research was refreshed and no historical trial was relabeled.

Local links resolve and the three files contain no Han characters. The current
tracked-text inventory is 61 files / 75,375 Han characters, so the English-only
gate remains open. Verification is in
`runs/engineering/main-integration-oracle-final-20261102/english-operations-verification.json`.

## Committed native Oracle protocol smoke and English historical entries

Committed source `87cf155` prepared and ran the four current minimum-arm Level 1
native Oracle entries through the unified CLI, each with a 15-second engineering
limit and 20-second cleanup allowance. All four native owners exited without
forced kill or descendant cleanup and released their owner locks. Every entry
wrote `robofrontier.oracle-report.v2`, with valid physics and incomplete tasks.
Transport/Mosaic/Relay retained their unresolved in-flight actions; Dial resolved
its stop. No interrupted run was promoted to full success.

Read-only stream audits decoded 1,405 Transport, 1,601 Mosaic, 1,909 Relay and
1,493 Dial frames (6,408 total), checking every chunk, timestamp and visual event.
Maximum sample gap was 0.018 seconds, and all events fit within retained final
poses. Each complete-recording gate correctly rejected only the interrupted
status. These checks did not solve full tasks, call a model or render new videos.
Native status/report and motion receipts remain under
`runs/engineering/main-integration-oracle-final-20261102/`.

The current Dial/environment entries, dated Oracle integration plan, Transport
R11/R12/R13 history, early RGB/NoSlip records and three historical redirect
headers now use English. Historical commands, numerical results and source URLs
are retained, with old demo defaults and preview-only checks labeled by date.
All edited local links resolve. The tracked-text inventory is now 50 files /
72,002 Han characters; the English-only gate is still open. Translation source
comparisons are in `english-history-verification.json` beside the Oracle evidence.

## Historical fixture closure and full local discovery

Full discovery first ran 1,495 tests with no assertion failures, 41 errors and
26 skips. Most errors were absent ignored historical data; a hardware-capability
test also constructed World without its current observation-image profile.
That fixture now initializes the same declared profile without changing either
hardware-width assertion or production World behavior.

The preserved primary checkout supplied 3,643 absent assets from identical-XML
scenes, 1,295 original previews and 87 files from the unchanged source-preservation
receipt. Workstation checksums were required wherever declared. Independent
copied objects were shared only inside the new fixture store, with no links to
the originals. Pinned closed Dial/Transport reports, streams and original harness
files were copied byte-exactly; all 36 historical Oracle-presentation sources
were restored against their existing metadata/asset hashes. No approximate
regeneration, source-scene edit, raw-report rewrite or new rendering occurred.

The Dial family review had additional actual compatibility defects after these
files were present: absolute selection paths did not relocate; the legacy
builder incorrectly required the current explicitly unqualified physics
candidate to equal its older successful witness; and it compared the historical
report with the changed current scorer. It now selects only the pinned local
report with the exact logical suffix and SHA-256. Current metadata is separately
bound to the release and registered hashes. A source mismatch requires both the
existing explicit historical-evidence caveat and the unqualified-candidate
release label. Public geometry uses the current source, and images use verified
existing reviewed public files. Formal readiness remains false and all original
qualification/assistance labels are preserved.

The old report's evaluator is verified from its own frozen bytes. No equivalence
is claimed for current terminal scoring. The only newly admitted controller
compatibility change is the exact role-label/engine/direct-START validation in
load_harness: removing those reviewed checks yields the identical AST from
pinned commit `d3e5916`, including every control and timing function. Its raw
historical hash is unchanged. Mutation tests reject changed control/timing,
unreviewed source, invalid report relocation/hashes, missing candidate caveats
and changed historical evaluator bytes.

The focused handoff/source group passed 32 checks on network-disabled Linux
aarch64 using read-only current source and the existing dependency image. Full
macOS discovery then ran 1,501 tests in 329.983 seconds: 1,475 passed, 26 skipped,
zero failures/errors. All 28 dispatcher scenarios, other JavaScript checks,
syntax checks and portable links also passed. The first failed full run remains
retained. This passing discovery used the restored local historical fixtures;
it is not automatic fresh-clone fixture delivery or Linux/NVIDIA/Slurm qualification.
The full group includes native CLI tests with synthetic loopback endpoints;
the checker's descriptive scope now states that explicitly. The raw earlier
report is retained. Protocol-only validation with source-compatibility guards
also passed 239 tests and 28 dispatcher scenarios on macOS.

See [testing](../development/testing.md). Logs, data restoration receipts, exact control-AST
comparison and passing/failing reports remain in
`runs/engineering/main-integration-oracle-final-20261102/`. No paid inference
or new full video was started. Remaining fixture packaging, English migration,
hardware/provider qualification and final publication gates stay open.

## English historical display generators

Eight historical collection, contact-sheet, video-index, concept-preview and
Dial/Relay/Mosaic display generators now emit English captions. Original status
labels still distinguish selected success, incomplete/user-paused runs and older
scene revisions. Concept sketches remain explicitly labeled as concepts.

Each edited Python file parses, and its AST is identical after replacing string
constants only. Numeric drawing coordinates, execution paths, input/output paths,
record selection and physics are unchanged. No generator, renderer, world or
model was executed for this text migration, so no newly rendered layout is
claimed. The comparison receipt is `english-display-verification.json` under the
2026-11-02 Oracle engineering directory. Tracked text now contains 42 files /
70,259 Han characters; the repository-wide English gate remains open.

## Optional historical fixture installer

The preserved test inputs now have a separate local delivery archive and
per-file manifest: 43,678 files, 757,780,223 compressed bytes. Both delivery hashes
are recorded in the testing guide; individual file identities remain unchanged.
The standard-library installer requires the independent manifest pin, validates
all members before installation, rejects source overwrites, traversal and
unverified links, reuses only exact existing files and supports retry after an
interrupted install. Hardlinks share only newly staged copies. Ten focused
macOS tests pass, including late corruption with no partial installation.

An initial isolated Linux staging driver was stopped before running tests:
its random-access extraction repeatedly decompressed hardlink targets. Its
original log and staging volume are retained. The maintained installer instead
reads sequentially and resolves hardlinks only to already verified staged files.
Independent Linux full-discovery and actual large-bundle installation results
are still pending at this commit. This local bundle does not add a public
historical-fixture download or change the ordinary policy bootstrap.

## English early communication pilots and slip diagnosis

The early shared-world trial, two-session mailbox pilot and 2026-10-19 slip
diagnosis now have English archival text. The desktop driver's controlled role,
actual idle versus self-report, original permission limitations, protocol-only
scope and separation of offline truth-assisted diagnosis from model results are
retained. Obsolete commands are labeled historical. All numeric tokens and
source URLs match the originals, and local links resolve; the comparison is
`english-pilot-verification.json` in the Oracle engineering evidence directory.
The English migration remains open, with 39 tracked files / 67,326 Han characters.

## English historical Factory viewer and V7 record

The legacy empty-building viewer and V7 rendering record now use English. The
viewer still identifies its reserved zones as an empty-building preview; it
cannot be mistaken for the later populated Factory delivery. HTML structure,
non-text JavaScript, template expressions and numeric values are unchanged, and
the inline script parses. No renderer was started. The V7 record retains all
numeric values, commands, historical limitations and local links. Verification
is in `english-factory-legacy-verification.json` in the Oracle evidence root.
The remaining English inventory is 37 files / 66,203 Han characters.

## English original environment notes and Transport math

The early eight-arm beam-handoff and four-arm Mosaic environment notes now use
English, retaining geometry, contact/IK boundaries, measured results and the
legacy READY/topology protocol. The latter is explicitly separate from current
direct START. Missing original beam-run reports remain identified by their exact
historical paths instead of unusable links. No historical reference is promoted
to current qualification. The Transport nine-task mathematical baseline retains
every schedule value and all eight unpassed categories, including unresolved
execution. Numeric tokens, source URLs and local links were checked in
`english-early-environments-verification.json`. The remaining tracked English
inventory is 34 files / 63,299 Han characters.

## Independent Linux discovery exposed a fixture packaging omission

Source `53db653` was cloned from its Git bundle into a Linux-local Docker volume,
without the live worktree, active databases, credentials or network. The v2
fixture installer verified and installed 43,678 files in 10.744 seconds. Full
discovery ran 1,511 tests in 232.246 seconds: zero assertion failures, one error
and 26 conditional skips; all JavaScript and documentation-link checks passed.
The error was a missing registered Relay Oracle source under `outputs/oracle`,
which the original export's `configs/environments` / `runs/oracle` roots omitted.
This failed full-discovery report is retained in `linux-isolated-results-v2/`.

The v3 optional bundle adds all nine registered dated Relay source directories:
858 original metadata/asset files, verified against unchanged release source
pins and workstation asset checksums. It now holds 44,536 files / 759,710,326
compressed bytes. The installer admits only those dated source metadata/assets
under outputs, with unrelated paths rejected. Eleven focused macOS checks pass.
The testing guide contains the new independent manifest and archive pins. The
v2 bundle/report remain retained; neither is silently relabeled complete.
An independent v3 installation and complete Linux discovery are pending.

## English palette labels and legacy task prose

Five pattern/task JSON sources now use English display labels, descriptions,
objectives and execution-context prose. Parsed values outside those text fields
are identical: palette IDs/hex values, every lattice cell, object/goal constraints,
control limits, friction and scoring thresholds remain unchanged. The original
frozen scene pattern copies and recorded run inputs were not rewritten; only
future generation/preparation reads the translated source text and its new raw
hash. Original/translated hashes are in `english-pattern-task-verification.json`.
Existing inventory/schedule and petal-symmetry/round-crank checks pass (three
checks). The remaining tracked inventory is 29 files / 63,012 Han characters.

## English historical report output

The original trial exporter, Mosaic local-color preview and deterministic
Transport program summary now produce English text. Their original limitations
remain explicit: a single pilot does not compare architectures; sampled geometry
does not qualify parallel paths; truth-assisted program execution is not an RGB
policy baseline; unpassed physical references cannot attribute failure to model
intelligence. All three Python files parse and retain identical non-text ASTs.
No exporter, renderer or simulation was run. The source comparison is retained
in `english-legacy-report-verification.json`. English migration remains open at
26 tracked files / 61,812 Han characters.

## Independent Linux full discovery passed with v3 fixtures

The independent Git-bundle clone of `4f9cd85` installed all 44,536 v3 historical
fixture files in 10.446 seconds on its Linux-local volume. Full discovery ran
1,512 checks in 227.561 seconds: 1,486 passed, 26 conditionally skipped, zero
failures/errors. All 28 dispatcher scenarios, other JavaScript checks, syntax
checks and documentation links passed. Stopped-container receipts and logs were
copied to `linux-isolated-results-v3/`; the original v2 failure stays retained.
No source assertions, physics thresholds or original evidence hashes were
weakened. Network was disabled; no credentials or active host database were
mounted. Native loopback test sessions are engineering checks without real
provider inference. The existing arm64 dependency image and pinned Panda assets
were reused, so this is independent current-code Linux CPU discovery, not a new
image build, x86/NVIDIA qualification or automatic public fixture distribution.

Slurm was discoverable after loading the site's `slurm/slurm/23.02.6` module.
Read-only queries reported debug and llm partitions with GPU resources; several
SSH attempts failed before a later successful query. No allocation, provider
trial or unified stage-out qualification is claimed by this discovery receipt.

## English historical suite previews and policy-batch report

The early Frontier v2 preview, five-valid-setting Dial preview and historical
minimum-scale policy-batch report now emit English. Preview text retains static
initial-state and non-qualification caveats. The policy report explicitly labels
its original 20-minute budget and process-compliance requirement as historical,
rather than changing the current 24-hour/terminal-outcome protocol. Numeric tokens
and non-text Python ASTs are identical; no previews, models or worlds were run.
The comparison is in `english-preview-batch-verification.json`. Remaining tracked
English migration: 23 files / 60,692 Han characters.

## English Mosaic review and color-design history

The original Mosaic review-package and supply-color design records now use
English. They retain numerical values, source bindings and local specification
links, with the explanatory document described in prose rather than retaining a
Chinese display filename. Original scorer/hold-final requirements remain dated
history and explicitly defer to later terminal-outcome/looping rules. Design
geometry, private matching evidence and sampled reachability remain distinct
from full paths, parallel safety, model scores and revised Oracle qualification.
No source assets or evidence were changed. The comparison receipt is
`english-mosaic-design-verification.json`. Remaining English migration is
21 tracked files / 57,911 Han characters.

## English family integration handoffs

The Transport, Relay and Mosaic branch handoffs now use English. Their original
C1–C5/shared integration plans, source/data preservation, assistance labels,
qualification boundaries, edit adapters, cleanup evidence and every numeric token
remain intact. They explicitly identify their dated stage and defer to this
ledger for subsequently completed work. Original hold-final/end-after-all plans
are preserved as superseded history, not reintroduced as current looping policy.
Local links resolve; `english-family-handoff-verification.json` records the source
comparison. No task, scene, control source or frozen record was edited.
Remaining English migration is 18 tracked files / 53,061 Han characters.

## English concept-illustration source

The old candidate-task illustration generator now has concise English labels
and explicitly describes concepts rather than implemented simulations. Its
bridge, gear, balance, packing and domino concepts remain historical proposals.
Python syntax and every non-text AST node are unchanged; no image or world was
rendered. Source comparisons are in `english-task-concept-verification.json`.
Remaining tracked English migration: 17 files / 52,497 Han characters.

## English discrete Dial research-report generators

Both Dial feedback/alphabet report generators now emit English descriptions,
HTML labels and historical rule drafts. They retain all numerical tokens and
identical non-text Python ASTs, including sampling, table construction and output
selection. Their text keeps exhaustive versus sampled counts, uncertainty,
logical-trial versus mechanical-time boundaries, candidate-information limits,
record-event attribution and historical non-deployment explicit. No report was
regenerated, no hidden task answer read and no dynamics/model started. Receipts
are `english-dial-alphabet-verification.json` and
`english-dial-feedback-verification.json`. No tracked Python or HTML display
source remains in the Han inventory; the remaining migration is 15 files /
49,907 Han characters, all historical documents and preserved path references.

## English Transport execution/planning history

The original dedicated-worktree Oracle plan, minimum-unit review and subsequent
grasp/forward-recovery/independent-progress record now use English. They preserve
single-thread physics ownership, original request IDs, in-world versus fresh
attempt boundaries, private geometry, assistance labels, fixture versus order
identity and local-segment versus whole-task scope. The two historical parallel
comparisons retain all measured values without becoming model-performance or
global-optimality claims. All numeric tokens, URLs and local links match; the
receipt is `english-transport-planning-verification.json`. No recorded input,
physics, source snapshot or trial was changed. Remaining English migration:
12 tracked files / 44,195 Han characters.

## English prototype plan and first-suite progress snapshot

The original keyboard-prototype plan and first-suite engineering snapshot now
use English. They explicitly describe their historical implementation stage,
keeping proposed takeover/step/reset behavior separate from the current unified
policy contract and old development counts separate from current acceptance.
Every numerical token and original URL remains, with local links resolving.
Private Oracle experience, fresh-policy contexts, counterfactuals, qualified
holding versus airborne retention and no cross-version PASS transfer remain
explicit. No old run or source snapshot was rewritten. Verification is in
`english-initial-suite-verification.json`. Remaining migration is 10 tracked
files / 39,322 Han characters.

## English initial Dial recovery handoff

The 2026-10-26 pre-compaction handoff now uses English. Its original pause,
worktree and Oracle-only authorization are explicitly historical, not new
instructions to pause authorized integration. First-round six-pass/three-failure
results, rejected shoulder geometry, unknown-request fencing, recovery metadata,
assistance and goal-versus-clean-success boundaries remain. Numerical tokens,
original URLs and local links were checked in
`english-dial-recovery-handoff-verification.json`; no source, private code or
original report was edited. Remaining English migration: nine tracked files /
36,659 Han characters.

## Restored Mosaic review gates and explicit historical provenance

Reviewing the 26 full-discovery skips found available original Mosaic packages
and design files in the preserved primary checkout. Independent copies restored
211 missing closed-report/control/evaluator/package files, then 391 protected
media/metadata and coverage certificates. Every supplied source/asset/certificate
pin was checked; originals stayed untouched. Eight package tests and the actual
color-plan test no longer need to skip locally.

The actual registry check first failed on the canonical harness's Coordinator
→ Controller label change. It now authenticates every original frozen harness,
admits only that exact parsed-label change and rejects altered control limits.
Each trial's five frozen control files also matches the narrowly reviewed shared
control identity. The task_config receipt adds Mosaic only because its archived
bytes equal the same already-reviewed historical source; control/timing AST
checks remain unchanged. Historical evaluation is authenticated against each
record's frozen evaluator bytes, report provenance and aggregate digest. It is
not normalized into a claim that current terminal scoring is the old scorer.

The unchanged old review package also correctly exposed its old builder hash.
Pinned commit `c63652e` contains exactly builder `aad77b43...`; its public
projection functions and forbidden-field guard have the identical AST today.
Only that static projection is admitted for the known old builder. Unknown
builders and altered public guards fail. The R14 preview caption change has a
separate exact-current-byte/non-text-AST receipt from immutable `c4b49d0`; no
control source receives a blanket string exemption.

Private design references are relocated only from the known legacy root to six
registered local filenames, preserving original JSON bytes/hashes and rejecting
traversal/external symlinks. A new test caught macOS's /var versus /private/var
root aliases; both local spellings now map to the same confined evidence store.
Coverage reports are checked against the design's original scene and certificate
hashes, not just confirmed booleans. Old failure logs remain retained.

All 34 focused package/provenance/source checks passed. Protocol-only checks
passed 248 Python tests and all 28 dispatcher scenarios, with physical creation/
stepping blocked and no skips. Both actual R13/R14 packages passed with physical
stepping prohibited: nine cases each, all 496 protected files unchanged and
policy_launch_ready=false. No new Oracle or model trial occurred.

A separate read-only check authenticated every original Mosaic motion chunk:
72,141 chunks / 8,656,459 frames across nine registered recordings, in 24.747
seconds. This used managed links to closed primary-checkout data, not a claim
that all raw chunks were independently relocated into the development bundle.
The v3 development bundle predates these additional Mosaic fixtures; updated
bundle/fresh-checkout and complete-discovery checks remain to be delivered.
Receipts and all prior failures remain under the Oracle engineering evidence
root, including `mosaic-review-validation.json`, `mosaic-original-motion-checks.json`
and `protocol-after-mosaic-mac.json`. Existing raw reports, media and fingerprints
were not rewritten; formal readiness and assistance labels remain unchanged.

## Mosaic development fixture closure v4

The v4 local development archive now contains 45,141 files / 1,436,933,424
compressed bytes, adding 605 files to v3. It includes the restored Mosaic review
and protected-media/coverage closure plus separate exact frozen-builder sources
extracted from immutable Git. Those sources live in a new engineering namespace,
without adding files to a sealed original trial. Current source remains English;
original archived evidence bytes/names remain unchanged.

The installer accepts only the added dated Mosaic fixture roots and still rejects
unrelated paths, source overwrites and unverified links. Twelve focused installer
checks pass. Both independent bundle pins and raw-Mosaic-chunk limits are now in
the testing guide. The v3 bundle/receipts remain retained. New-source independent
v4 Linux discovery and public fixture distribution remain pending at this commit.

## English Relay cleanup-planning archive

The 2026-10-27 read-only Relay cleanup plan now uses English. Its inventory,
proposed removals, shared-link cautions, evidence/dependency boundaries and
future main-session responsibilities remain historical, without performing
cleanup or reopening old instructions. All numeric tokens and local links were
checked in `english-relay-cleanup-verification.json`. Remaining English migration:
eight tracked files / 33,097 Han characters.

## Native idle-mail continuation and independent discovery v4

The independent Linux clone at `89ddc46` installed all 45,141 pinned v4 fixture
files, then ran 1,522 Python checks: one failure, zero errors and 17 conditional
skips. JavaScript and documentation checks passed. Both actual Mosaic review
packages also passed with physical stepping prohibited. The original full-run
failure remains in `linux-isolated-results-v4`; it is not a passing receipt.

The sole failure required an idle-session wake after bootstrap, although all
bootstrap messages can legitimately arrive while the native recipients are
already active. Repeated diagnostics captured exactly that condition: zero
bootstrap wakes and no pending mail or signals. The test now waits for idle,
sends a distinct message through the actual native sender and MCP transport,
and requires the idle recipient to acknowledge it, start a new turn and retain
its original session. Existing routing, gripper execution and session-file
assertions remain. Production dispatch code is unchanged.

Both hierarchical and peer topologies passed once on macOS and Linux, then
three additional iterations per platform. Every post-idle message reached an
idle recipient, produced a new wake on the same session and was acknowledged.
Receipts are in `claude-standing-post-idle-{mac,linux}-v{1,2}.log`. These tests
use real native CLIs and MCP with synthetic loopback model/world endpoints;
they make no real-provider inference and do not open Claude scored execution.
Complete discovery of the committed test correction remains required.

## Real Slurm/H800 observation context check

Slurm job `428862` completed with exit `0:0` on `dgx-097`, using one H800,
two CPUs and a five-minute limit. The compute step verified five source modules
frozen at `86d043b`, created the production NVIDIA rendering probe, then rendered
a minimal sphere/plane scene after ten CPU physics steps. The backend reported
NVIDIA Corporation / NVIDIA H800 / driver 580.159.03. The 896×560 JPEG used
quality 85, decoded completely and had nonzero image variation. Model calls: zero.

Returned JSON, JPEG and batch log are retained under
`slurm-egl-86d043b/returned`. Independent local verification checked their hashes,
the JPEG dimensions/format/size and every tested module's bytes against current
`9bba6fe`. The image SHA-256 is
`c313a54b45fcca2fd7d3ca58a6606493d61f12d96b9b799620c9fbac6210f007`.
`returned-verification.json` and the original allocation logs preserve scope.

This is real Slurm allocation plus hardware EGL/JPEG evidence. It does not
qualify complete task observations, the unified policy launcher, node-local
SQLite/stage-out, provider execution, 36-task capacity or Factory video.
The probe used `/tmp`, but did not certify its filesystem type. No other user's
job was modified and no model/provider or video render was launched.

## Independent Linux discovery v5 passed

A new Git-bundle clone of `9bba6fe` on a separate Docker-local volume installed
all 45,141 pinned v4 historical fixtures in 13.236 seconds. Full discovery passed
1,522 Python checks with zero failures/errors and 17 conditional skips. All
JavaScript/dispatcher and documentation-link checks passed. Both actual Mosaic
packages passed separately with physical stepping prohibited, preserving
`policy_launch_ready=false`. The native idle-mail correction is included.

The stopped container's results were copied only after exit 0 to
`linux-isolated-results-v5`. The earlier v4 failure remains unchanged. This uses
the existing dependency image and independently cloned source, not a final-source
image rebuild. Endpoints are synthetic; no real provider inference occurred.

## English family readiness and replay-planning archives

The dated Dial, Mosaic, Transport and Relay readiness/replay plans now use
English. Original rules, geometric values, assistance labels, implementation
checkpoints and independent-clock/hold-final requirements remain. Old planning
restrictions are explicitly historical rather than current instructions.
Numerical-token inventories, original links and URLs were checked against
preserved source in `english-final-family-planning-verification.json`.
No Oracle, model call, replay generator or video render was started by these
documentation changes. Two historical prose documents and two original-evidence
path references remain in the English migration.

## Remaining historical prose translated

The original Relay compaction handoff and first-suite specification now use
English. Successive old frontiers, process observations, accepted user rules,
failed requests, exact source hashes and superseding completion updates remain
historical. They do not authorize reopening completed worlds or replacing
current physical defaults with initial design proposals. Every numerical token,
original URL and existing Markdown link across all six final historical documents
matches the preserved baseline; `english-final-historical-verification.json`
records source and translated hashes.

Tracked source/content now has no Han text except ten immutable-evidence path
references in two configuration files. The underlying original filenames and
evidence bytes remain protected. No source recording or video was regenerated.

## English configuration with unchanged historical timeline names

The final ten path strings now use the original ASCII-named video index and its
SHA-256, rather than renaming protected historical files or hiding their names
with Unicode escapes. Mosaic delivery metadata explicitly advances to v2 with
`timeline_index`; current release historical edits use typed `mosaic_video_index`
references. The presentation-preparation consumer authenticates the index, selects
exactly one case timeline, confines legacy-root relocation to the local registered
video directory and authenticates original edit bytes. Direct legacy paths remain
supported; conflicting views, wrong cases/hashes, traversal and external symlinks
are rejected.

Seventeen focused reference/delivery tests passed. Read-only checks resolved all
nine actual entries to exactly the same original paths/hashes and authenticated
all 496 package-preserved files. `historical-edit-index-validation.json` records
this. The broader optional cleanup snapshot is absent from the local development
fixtures and was not claimed checked; its unavailable-check receipt is separate.
Tracked source/content now contains no Han text. Original ignored evidence names,
reports and recordings remain unchanged. Complete discovery and a new committed-
source image remain required after this consumer change.

## Fresh image exposed the asset release's metadata binding

The first actual image rebuild at `8ddea22` failed before downloading assets:
the original archive pins the complete release JSON, whose bytes changed with
the nine historical edit references. Comparison against immutable `696000c`
confirmed that every other parsed field is identical, including GPT cases,
scene/source hashes, qualification labels and all original edit hashes. The
old archive URL, archive SHA-256 and Panda source pin remain unchanged.

The asset lock now carries one explicit metadata compatibility receipt. The
installer authenticates the exact revised release, all nine expected typed
references and the canonical digest of every remaining field. Only then can it
use the original archive's release identity. All manifest contents and individual
asset hashes are still checked. Updating a raw release hash alone cannot admit
an unrelated scene/rule/control change. New runs still freeze the actual revised
release identity, rather than claiming its old hash.

The minimal regression reproduced the image error before the fix. Sixteen
asset/reference checks now pass, including missing-receipt, changed unrelated
fields and substituted-index rejection. Original red/build logs remain retained;
`asset-index-release-compatibility.json` records the independent old/new comparison.
The image rebuild and complete-discovery results will be recorded separately.

## Original atlas capture identity retained across metadata-only release change

The complete macOS discovery started at `8ddea22` recorded 1,529 checks with
two failures, 22 errors and 17 skips. Nineteen errors were the already-reproduced
asset-lock mismatch; the remaining atlas failures/errors correctly rejected its
old release identity after the metadata change. This diagnostic run remains
retained, not counted as a passing final-source receipt.

Atlas verification now admits the original capture identity only through the
same exact-release/unchanged-fields asset receipt, while still comparing every
public task field. Unknown capture releases, changed rules, rehashed images and
extra payloads remain rejected. A presentation-only refresh pins the new verifier
and labels the original capture release explicitly. All 72 JPEGs, individual task
JSON files and aggregate task payload remain byte-identical; their original
capture manifest/provenance is retained. No image rendering, world creation or
model inference occurred. Twenty-nine atlas/asset/reference checks passed.

The rebuilt `86d0d9b` source image passed automatic policy bootstrap after the
metadata fix. A separate disk-exhaustion attempt is retained. Recovery archived
the logs/results and reproducibility information of three stopped, disposable
development volumes before retiring their source/fixture copies, and evicted one
temporary build-context cache. Original experiments and the recent passing v5/
failed v4 volumes remain. See `retired-development-volumes-20261102` and
`atlas-index-metadata-refresh-verification.json`. A final image/discovery of the
atlas correction is still required.

## Final engineering acceptance at a595709

Both complete discoveries pass 1,534 checks, with zero failures/errors and 17
conditional skips. The independent Linux checkout installed all 45,141 pinned
fixtures in 20.409 seconds after recovering from a staging-only disk exhaustion;
the failed attempt had not started tests. It used newly built image
`robofrontier:a595709fb4c5`, image ID
`sha256:037ac4f98a813c7f155b9f6c9094672cfaa7deba616c31c1849f997ceb22b9ee`.
This is arm64 Linux CPU/Mesa, not x86 or a full NVIDIA benchmark.

All 17 default Mac skips have separate passing assertions: eight opt-in native
Claude/real-physics checks, five Factory replay checks, three original Transport
source-edit checks and the original Dial published-schedule check. The physical
group passed eight checks on each platform, including real image transport,
four overlapping worlds, actual robot action, native mailbox continuation and
signal/finish sealing. Linux's driver supplies explicit CPU renderer/preparation
and launcher environment; assertions, native CLIs and physical owners are real.
Model endpoints are scripted loopback services. Synthetic billing uncertainty
retains needs_review evidence, without false task or provider qualification.

Original replay checks use read-only closed data and temporary managed links/
scene selection, prohibit `mj_step` and render no new video. They do not claim
every optional recording was relocated into the development bundle. The original
Factory movie remains published and the user's deferred full rerender remains
deferred. All 6,569 tracked paths and text files have no Han characters; the 602
binary files were not treated as text. Archived ignored evidence is unchanged.

The new image also prepared 32 fresh packets covering both engines/four modes/
four minimum-arm families. After an output-directory error in the receipt driver,
all existing packets were verified without regenerating them: frozen inventories,
actual release projections, role allocation, 24-hour limits and observation
settings match. Earlier 288-case preparation evidence remains separately scoped.
There were no model calls or simulation starts in preparation.

Raw failures and passing reports remain separate under the engineering root.
`final-engineering-acceptance-a595709.json`, `final-conditional-check-coverage.json`,
`linux-isolated-results-v7`, native physics logs and original-replay receipts
identify tested source and precise data/configuration scope.

## Final integration review and remaining qualification

The review comparison is pinned main `c8b4137` to the engineering integration.
Source inspection and regression evidence cover explicit launch/spend boundaries,
frozen input identities, independent scoring versus process history, original
call-ID fencing, stopped-writer archival, credential exclusion, native session
isolation, historical source compatibility and public projection allowlists.
The historical-index metadata change has both whole-release and unchanged-field
proofs; physical assets, old reports and capture bytes were not repinned casually.
The complete diff passes whitespace checks. No blocking engineering-code finding
remains from this review. This is not real-provider or research qualification.

Real-provider/API and subscription refresh, 36-task execution capacity, full
unified Slurm policy execution/stage-out, physical-candidate promotion and Claude
formal scoring remain explicitly gated. The H800 allocation qualifies only the
recorded EGL/minimal-JPEG scope. No paid preflight or full video rerender is
silently authorized by these passing tests. Copyright/full author/publication
metadata remain pending as the user requested.

## Delivery artifacts

The `development-fixtures-20261102` prerelease separates optional historical test
dependencies from ordinary policy bootstrap. Its original v4 archive/manifest
retain their independently pinned hashes and all historical qualification labels.
The same release supplies a small verified offline task-atlas ZIP: unzip/open
the page without GitHub's HTML source view, a local server or model access.
Only allowlisted public atlas files enter that ZIP. Main integration/publication
must verify these release assets; no existing release attachment is overwritten.

## Published main and fresh full-reference follow-up

Main `d433f91` is published and clean locally/remotely. All five prerelease
assets match the uploaded hashes; an unauthenticated atlas download also matches
the pinned ZIP digest. The atlas validation workflow completed successfully at
that exact main commit: GitHub Actions run `41366582393`, with publishing disabled.
These receipts cover engineering delivery, not the remaining physical/model gates.

A fresh current-scene Transport L1 full reference at `d433f91` completed 4/12
goals before reaching retained-load planning handbacks. The 300-second engineering
cap stopped the owner cleanly: physics_valid, execution_resolved and process_clean
are true; task_goal_met, task_completed and strategy_completed are false. Its
world, failed jobs and recordings remain retained and are not resumed or relabeled.

A read-only reproduction at its archived event state 289 isolates one placement
search defect. All four current-seed IK endpoints collide with another arm, but
the home-seed branch reaches the same target and passes the unchanged endpoint
and sampled transit checks. Placement previously stopped considering seeds as
soon as IK converged, before clearance was checked. Clearance now participates
in seed selection, so a colliding branch stays rejected while the next declared
seed is tried. Geometry, 6 mm inter-arm planning reserve, goal tolerance, actuators
and physics are unchanged. Existing contact diagnostics may include permitted
finger contacts; the exact rejecting pair here is an inter-arm pair.

The captured FK fixture reproduces the failure before the change in under one
second. Afterward the real planner reaches its first ordinary actuator command
without stepping physics or changing live qpos/control/model margins. All 18
Transport coverage and physical Oracle contact checks pass, including unchanged
Transport seating and Mosaic contact regressions. This local result does not
complete the full 12-goal reference; a fresh source-pinned full run is required.
Evidence is under `runs/engineering/main-integration-oracle-final-20261102`,
including the original full attempt, static probes and red/focused test logs.

The fresh `9b5511e` run advances through the formerly blocked A_slot3 and reaches
9/12 goals while still running; its final result is not yet claimed. It also
reproduces a separate `matmul` exception after a finite transit search fails.
A second sub-second regression reproduces that exact exception at Trial.place:
the raised-transit loop reused `offset`, replacing the grasp-offset vector with
a scalar height before the next object rotation. Naming the height separately
preserves the vector and ordinary PlacementPlanningError for exhausted routes.
The injected route rejection models actual cooperative admission failure; real
IK/collision checks still run and no rejected route executes. All 19 combined
Transport coverage/physical Oracle checks pass after both changes. Full-task,
Linux and broader follow-up receipts remain separate from these local results.

## Final placement follow-up acceptance at c830202

Both complete discoveries pass 1,536 checks, zero failures/errors and 17
conditional skips. The final current-scene Transport L1 reference completes
12/12 goals, with all independent v2 verdicts true and no inter-robot contact
or process violation. Physics advances 466.38 simulated seconds through ordinary
actuator commands; the owner stops with no unresolved action. No LLM or external
engineering repair input is used and no live object state is written after
initialization. Earlier failed/intermediate runs and their source identities
remain retained. This source has both IK-seed fallback and preserved vector
offset fixes. Its full-reference result is separate from the passing `9b5511e`
run and the incomplete `d433f91` attempt.

Source inspection confirms the production delta from delivered main is confined
to those two finite placement searches. Collision/support checks, physics, goals,
public policy projections and native engine lifecycles are unchanged. The two
regressions went red before their respective fixes. The archived FK diagnostic
never executes a robot or resumes the old episode. There is no blocking finding
from the follow-up source review; broader physical/provider gates above remain.

Receipts include `full-{mac,linux}-placement-c830202.json`, the final trial's
`report.json`/closed motion recording, `placement-followup-local-receipt.json`
and `final-engineering-acceptance-c830202.json` under the engineering root.
The public acceptance artifact summarizes the same scoped assertions; its source
identity does not cover later documentation-only commits automatically.

## Current Transport L2 continuation follow-up

A fresh `29e1211` current-scene Transport L2 reference reached 11/12 goals before
its explicit 600-second engineering stop. Physics remained valid, every action
resolved and the process clean, with zero inter-robot contacts. The final job
retained B/B_item1 after receiver D's contact approach failed with
`No clear free-arm IK D/regrasp-contact`. This is incomplete evidence, not a
physical impossibility or model failure; its stopped world is not resumed.

A sub-second read-only reproduction reconstructs the original candidate exactly
(zero maximum donor-joint difference), then its target from recorded donor state
865 and receiver state 869. A single direct IK solve misses the native angular
limit: 0.021115 rad versus 0.020. Two/four shorter continuation solves pass every
ordinary native endpoint check. The candidate planner had screened four short
continuation segments; execution instead requested one full 150 mm displacement.
The follow-up executes those same four waypoints through ordinary moves, retains
the final precise approach and leaves controller, collision/support and task
thresholds unchanged. Its real-controller FK regression went red on the original
call chain and now passes. Related planning checks pass 46/46; combined Transport
coverage/physical Oracle checks pass 20/20.

A separate controlled forward phase initializes archived pose 869 and the recorded
50 N donor pressure-hold mode before its first step. This is a new engineering
fixture, not exact checkpoint restoration. It executes ordinary guarded commands,
obtains actual bilateral support from B and D, and finishes with clean process,
resolved execution and valid physics in 5.535 seconds. The initial fixture setup
failures remain retained. Its inherited 11-goal arrangement is not a full-task
witness and is not stitched into another result. A new source-pinned complete run
is required before closing this follow-up. Evidence remains under the engineering
root with `l2-` and `transport-current-l2-` prefixes.

## Fresh continuation witnesses and native SQLite close race

At `f9d532d`, fresh current-scene Transport L1 and L2 references each complete
12/12 goals in one world. All independent v2 verdicts are true, with no unresolved
actions or inter-robot contacts. Their recorded active wall times are 382.518 and
501.607 seconds. Each uses ordinary guarded actuator commands and no model or
external repair input. Earlier failed worlds remain stopped and retained.
These receipts qualify the two cases, not all Transport sizes or difficulty levels.

Mac complete discovery passes 1,537 checks, zero failures/errors and 17 conditional
skips at that source. Linux passes 65 related checks, but its subsequent complete
discovery exits with native SIGSEGV. A discovery-prefix loop reproduces on attempt
two; the single adaptive snapshot test repeated 100 times crashes in 0.66 seconds.
The worker stack is BudgetLedger COMMIT while teardown closes shared databases.
Both failed runs and their unchanged source checkout remain retained.

Two deterministic regressions show that BudgetLedger and RuntimeStore close can
enter the native connection while another thread holds their transaction lock.
They fail before the repair and pass after close acquires the existing RLock.
No SQL transaction body or uncertain reservation is replayed. Linux SQLite reports
THREADSAFE=1 and Python threadsafety=3. With only the close-lock repair mounted
over the original source, the original snapshot/teardown loop passes 1,000 times
in 42.843 seconds. The adaptive fixture now also joins its child turns before
closing stores and verifies the expected settled total. Production session state
becomes idle only after settlement and evidence writing under its session lock;
policy closure checks that state before closing the runtime store. Forty-two
related checks pass. Complete discovery of this final repair is still pending.

Separately, actual Slurm job 428877 at main `29e1211` completes four Single native
Claude/physics owners on dgx-061 with NVIDIA H800 observations. The unchanged
production stage/execute/collect/ZIP/stage-out path returns 1,728 files, all verified
through extraction and restoration without restarting the source worlds. Every
case completes an A +5 mm action, seals without unresolved IDs and retains its
86,400-second public task limit. Four distinct native sessions and 896x560 JPEGs
are recorded; peak started tasks is four, peak overlapping motor actions is three.
The HTTPS model is scripted, with zero real-provider calls and no formal model
score claim. This closes that four-case normal lifecycle scope only: 36-task
capacity, abnormal Slurm stop and genuine provider/subscription qualification
remain open. Raw task/session evidence remains private under the engineering root.

## Final closure boundary follow-up

At `799eed8`, Mac complete discovery passes 1,539 checks with 17 conditional
skips. Linux completes the same 1,539 checks without the native crash, but records
one failure in the integrity timer boundary assertion. The original child cleanup
loop also passes another 1,000 repetitions with the complete fixture repair.
Neither the failed Linux discovery nor preliminary driver errors are counted as
a passing final-source run.

The timer failure reproduces deterministically in 0.123 seconds with last-check
time 1000.1 and a 30-second interval. The computed deadline is 1030.1, but subtracting
timestamps yields 29.999999999999886. Periodic verification now compares the clock
directly with its absolute deadline; the interval and check frequency are unchanged.
The existing regression pins that red-capable timestamp and checks both sides of
the boundary as well as suppression of a duplicate check.

An independent launch-boundary regression also shows that a configured third-party
profile with an absent/empty endpoint reaches CLI process creation. The process is
intercepted in both red cases; no real credential is used or request sent. The
native runner now requires an explicit endpoint for declared non-Anthropic
providers before CLI launch. Offline catalog inspection remains available without
an endpoint, and Anthropic may still use its native default endpoint. Configured
third-party and synthetic loopback profiles retain their existing behavior.
Seventy-two relevant checks pass, including actual native synthetic integrations.
Fresh complete discoveries of the combined final source remain required.

## Final closure acceptance at 8bd989a

Both complete discoveries pass 1,541 checks with zero failures/errors and 17
conditional skips. The eight opt-in native/physical checks also pass on macOS
and Linux, without skips, in 99.362 and 97.186 seconds. Linux explicitly supplies
CPU preparation/OSMesa launcher settings while retaining the real native CLI,
physical owners and unchanged assertions. The original snapshot regression
passes 1,000 iterations at this exact source. No real-provider calls occur.

Manual review against delivered main `29e1211` confirms the production delta:
execute the four screened regrasp approach segments; serialize shared SQLite
close with ongoing transactions; compare the integrity clock to its deadline;
and reject a declared third-party native runner without an endpoint before
process creation. The existing batch preflight endpoint check remains in place;
the new runner guard also covers direct entry. Controller/physics/goal thresholds,
unknown-action fencing, budget uncertainty and scene assets are unchanged. There
is no blocking finding from this scoped source review. The failed native runs,
incorrect preliminary driver arguments/module names and intermediate timing
failure remain retained, not included among passing receipts.

The README's old pre-merge banner and Slurm's minimal-probe-only description are
updated to the actual delivered/scoped state. `final-closure-acceptance-8bd989a.json`
and full/native reports under the engineering root bind the source and evidence.
Main publication, image and release-attachment receipts remain separate actions.

## Published closure and 36-task native prompt boundary

Reviewed closure main `0009b40` is published and clean, with production code
identical to tested `8bd989a`. Its source image passes read-only, network-disabled
bootstrap (3,467 files), default 36-case planning and changed-module byte checks.
Atlas validation CI run 41384291459 succeeds at that main commit with publishing
disabled. Nine prerelease assets verify; the original seven attachments remain
unchanged. A disk-exhausted build is retained. Recovery evicts only ten specifically
identified disposable build-context cache entries; source images, containers,
volumes and experimental data are retained.

A fresh 36-case Adaptive Slurm attempt at `8bd989a`, job 428903 on dgx-061, reveals
a native launch boundary: 32 Controllers reach the synthetic HTTPS rendezvous,
but four harder Dial sessions become unknown before sending a model request.
The attempt is stopped using an actual Slurm batch USR1 request, never resumed.
Job, batch and execution step finish 0:0 after 6:37, returning an unqualified
needs_review evidence ZIP (156,724,159 bytes, SHA-256
`26f043baac7c7cedb797ae81b4ffaa6e3916b5b4b2fc1df76abeafc565dabdd6`).
Step peak RSS is 19,746,824 KiB. This is not a passing 36-task or model result;
restoration and per-case stop audit remain separate pending checks.

A 0.504-second Linux reproduction reaches the actual runner process-creation
boundary with /bin/true and no network/physics. The 95,083-byte minimum Dial
prompt launches, while the 241,504-byte larger prompt raises E2BIG before process
creation. Native CLI invocation placed the entire public bootstrap in one argv
element. The follow-up streams the complete prompt through stdin, retaining
explicit session/resume/fork arguments, tools, cancellation and cost handling.
Partial-input communicate retries never send the prompt twice; terminal input
pipes close even after cancellation. A full-prompt checksum regression fails
before the change and passes afterward, as do unread-large-input timeout and
cancellation checks. Nineteen related/native checks pass, including actual
native session resume and fork/tool boundaries. A real native CLI also transmits
the complete large prompt to a synthetic endpoint. Complete discovery and a fresh
36-case witness are still required before this follow-up can be delivered.

The user authorizes real API checks for GPT-6 Luna and Haiku 5.5 with a combined
US$1 budget. Existing provider variables are available in the retained Luna/Claude
worktrees. No credential values enter tracked code, public receipts or Slurm jobs.
Budget authorization is not a passing provider receipt; usage and source scope
must be recorded after actual checks.

## Full-prompt stdin polling follow-up and genuine provider checks

Complete discovery at initial pipe implementation `b179598` does not pass:
Mac records six failures/two errors, Linux five failures/two errors. A fake
precheck CLI still assumes positional input; its fixture now supports both native
text stdin and explicit positional use. The native standing-role failures expose
a separate production issue. A two-second regression delays stdin consumption
until after cancellation polling begins. The first communicate call only sends
part of the prompt; retrying with input=None does not finish writing that input,
so native sessions can wait forever for EOF. The original failed full discoveries
and retained per-role native evidence remain available.

The runner now writes the complete UTF-8 prompt into a private unlinked temporary
file before process creation and supplies its descriptor as stdin. The child
owns its descriptor after launch. This avoids both argv limits and partial pipe
write retries, without changing session IDs, tools, budgets or stop semantics.
Thirty-three related/fake/native checks pass, including delayed input consumption,
timeout/cancellation, image/session resume, native fork boundaries and both
standing topologies. Complete discovery and fresh capacity qualification remain
required. No failed run is resumed or relabeled.

The user-authorized genuine Haiku 5.5 API precheck at `b179598` passes text,
random-image/tool interpretation, same-session continuation and verified native
fork history using Claude Code 2.1.312. CLI-reported cost totals US$0.000913.
This precheck used Python 3.13.5 from the invoking local environment, not the
locked Python 3.12 suite environment; it starts no physical world. Its native
CLI/profile/source receipts retain that scope.

The genuine GPT-6 Luna high official-API precheck passes image/function tools,
manual compaction and forked history with Codex 0.165.0 under locked Python 3.12.
It does not claim automatic compaction, long-context stress or an independently
verified backend alias. A failed local observer initialization precedes the
passing run and makes zero model turns. The corrected observer counts 34,967
reported tokens conservatively, including inherited fork totals, at US$2/M for
all token types: US$0.069934 estimated exposure, below its US$0.25 stop threshold.
With Haiku's reported total this is below the combined US$1 authorization; these
estimates are not provider invoices. Credentials come from existing local
provider environment files and are excluded from public/source/Slurm payloads.
These are provider compatibility checks, not scored robot trials. Receipts live
under `real-haiku-precheck-v1`, `real-luna-preflight-v2*` and the standard Luna
model-compatibility directory; no older result is overwritten.

## Native prompt spool acceptance at 8b273ab

Final complete discovery passes 1,544 checks on each of macOS and Linux, with
zero failures/errors and 17 conditional skips. The eight opt-in native/physical
checks pass without skips on each platform in 101.493 and 101.104 seconds.
Linux uses a fresh Git checkout with all 45,141 authenticated historical fixture
files and explicitly selected CPU/Mesa settings. Its original snapshot fixture
also passes 1,000 repetitions. These checks use scripted loopback models and
retain the original failed pipe/full-discovery evidence separately.

Manual review against main `0009b40` finds only the intended production change:
keep legacy direct command construction, but supply native turns with their
complete UTF-8 prompt through a private unlinked temporary-file descriptor.
The parent closes its descriptor after process creation; the child owns its
inherited descriptor. Existing timeout/cancellation polling and uncertainty
accounting remain in force. Three regressions cover full large-prompt hashes,
an unread prompt during timeout/cancellation, and delayed consumption after a
poll interval. The precheck fake also accepts native stdin. No source review
finding blocks this scoped repair. Thresholds, task goals, physical assets,
model profiles, explicit native IDs and unknown-action fencing are unchanged.

The failed 36-case attempt 428903 is fully restored and audited: all 18,523
files verify without physics, and all 36 owners are sealed. No physical action
was issued. Its four original launch errors correlate exactly with the four
Dial bootstrap prompts exceeding Linux's single-argument limit. Those failures
remain failures, and none of their stopped worlds is resumed.

Fresh Slurm jobs 428931 (dgx-061) and 428948 (dgx-081) at `8b273ab` each complete
36 Adaptive owners with 72 distinct bound Controller/Delegate native sessions.
Their stopped, hash-verified SQLite copies independently show exactly one
completed A +5 mm action and a finished delegation per case, with ownership
returned to the Controller. Peak overlapping motor actions are 16 and seven;
peak overlapping started tasks is 36 in both runs. Actual Slurm batch USR1
requests seal all owners with no unresolved action. Job, batch and execution
step all finish 0:0. Full restoration of 428948 verifies all 18,239 files with
physics entrypoints prohibited and all restored runtime database hashes
unchanged. The separate 428931 full restoration remains in progress; its
targeted trace audit is already complete.

Both returns correctly retain needs_review and incomplete-collection status:
interruption cancels active native model turns and leaves cost accounting
uncertain. This is independent of resolved motor actions and must not be
cleared using the scripted producer's known zero real-provider spend. Native
logs retain cancelled/unknown turns. The acknowledgement producer for 428948
reduces repeated waiting requests, but is not a production runtime change and
does not turn interruption accounting into a clean task/model result. Neither
attempt qualifies full-task success or model ability. The model service receives
only public task/tool inputs; no genuine provider credential reaches Slurm.

The two returned ZIP hashes are respectively
`58348d3f5dbee34da579df41e6d12c1ab95a53b6dd5bbd0d9b194750f86dc344`
and `e5289b99a5f5098390d269e58c3ee6308e48ed396418efa6764cd3a180bc036e`.
Targeted trace audits verify 288 selected files per return. Safe metadata,
producer/source fingerprints and stop receipts are retained under
`slurm-capacity-8b273ab-safe-metadata-v1`; raw task observations, sessions and
private puzzle data are not public release attachments.

A further genuine Haiku 5.5 compatibility check at `8b273ab` passes all ten
blocked-tool fork assertions with Claude Code 2.1.312 under locked Python 3.12.
The parent remains blocked while the child forks with an unchanged native
history prefix; after release the parent interprets its random observation image
and ends normally. The new receipt reports US$0.000531 against its US$0.10
allowance. Matching basic/blocked profile hashes, current CLI version, session
identities and cost completeness all verify. Combined conservative exposure for
the authorized API checks is US$0.071378 of US$1; no provider invoice is inferred.
This uses a local synthetic robot tool, with no physical world or scored trial.
Subscription refresh and the real-task/formal-scoring conditions in
`docs/claude-codex-parity.md` remain independent qualification requirements.

The user separately authorizes a real Haiku Adaptive Transport L1 task trial,
allocating US$0.25 from the same US$1 aggregate budget and a five-minute engineering
stop. Its frozen public task limit remains 86,400 seconds, with unchanged prompts
and scoring. The trial ends after 250.290 seconds at the native per-turn budget
boundary, before the timer's stop request: four ordinary physical actions complete,
two top-view image results return through MCP and ten native tool calls are
recorded. No delegate is created. The native CLI reports `error_max_budget_usd`
and US$0.05135674 against a US$0.05 per-turn estimate allowance; shared task
accounting remains uncertain. The independent interruption evaluation reports
false task success. The owner is sealed and exited, with no unresolved action.
The world is never resumed and its engineering result is not relabeled scored.

Closed evidence is collected and losslessly archived separately. Known CLI and
conservative API estimates total US$0.12273474; retaining the entire task's
US$0.25 allowance instead gives US$0.321378 exposure against US$1. Neither is a
provider invoice, and uncertain accounting is not automatically released for
another paid trial. These real observations/actions are useful compatibility
evidence, but they do not complete real delegation, handback, normal finish or
formal scored qualification. No extra paid task is launched after this outcome.

## Managed subscription login follow-up

Main `8b75325` is published and clean. Its delivery image matches all 6,572
tracked source files byte-for-byte in a read-only, network-disabled check;
bootstrap verifies 3,467 assets. Atlas CI 41394281114 passes with publication
disabled. Eleven prerelease attachments verify, with the original nine unchanged.
Slurm 428948's 18,239 files also fully restore on the Mac. The separate 428931
restore now completes all 20,487 files on Lustre, retaining 36 overlapping owners,
72 bound native sessions and 16 overlapping motor actions. Its original
needs_review/incomplete accounting status remains unchanged.

The user explicitly extends the work to both local subscriptions and authorizes
native login. Codex 0.165.0 is already signed in with ChatGPT Pro; its account
catalog includes GPT-6 Luna. A zero-model-turn probe requests managed token
refresh, verifies authenticated account access afterward, observes the native
cache update, and verifies the same account in a fresh app-server process.
No credentials are copied or returned in receipts. This is a local single-account
refresh/persistence witness, not concurrent cluster or all-expiry qualification.

Claude Code 2.1.312 initially has no native login. Its official subscription
browser grant is explicitly approved by the user, and the unmodified CLI reports
successful login with a Max account. A new native Haiku 5.5 text-only process
reuses that login and reports a US$0.0008046 list-price estimate. No provider API
key is supplied. The first login driver used unsuitable stdin; it is cancelled.
A /dev/tty retry fails locally with Bun EINVAL; direct native CLI execution then
completes the normal browser callback. Neither failed driver is a passing login
or model check, and raw credentials are never extracted into the harness.

Follow-up branch `codex/native-subscription-auth` adds distinct
`luna_subscription` and `haiku_subscription` profiles. Native Claude login freezes
an explicitly selected configuration directory, while API and explicit-token
profiles retain their task-private directories. Launch, provenance and collection
use the same selected native history. Stopped exports contain only bound sessions
and a collection marker, so restored history remains readable without access to
the account. Authentication homes inside evidence batches are rejected before
collection. Formal Claude scoring remains closed.

The new native-mode regressions first fail at unsupported mode/credential
validation. Focused checks then pass, including a sentinel credential store left
unchanged, exclusion of unrelated shared-home sessions, and account-independent
archive restoration. Additional red cases reproduce an auth home inside a batch
being collected and a runtime fork verifier reading the old private directory;
both are repaired without changing native history assertions or original IDs.
The source freeze automatically includes the new Python module.

The authorized shared Codex home has configured MCP servers. A native zero-turn
probe demonstrates that an empty-table override leaves them enabled. Preparation
now supplies scoped disable overrides, and native subscription preflight/hosts
verify the effective configuration before inference. A quoted-key experiment
fails locally at CLI configuration parsing; the supported override syntax passes
against the actual CLI and isolated layered configuration. User configuration
files are unchanged. These are scope checks, not model turns or physical trials.
Source-pinned genuine subscription prechecks and complete regression discovery
remain required before this follow-up is published.

At checkpoint `5b58f3f`, complete Mac discovery passes 1,554 checks with zero
failures/errors and 17 conditional skips. Genuine subscription checks uncover
limits that offline checks do not qualify. The first native Haiku precheck ends
locally as not logged in, with zero tokens and zero API duration. The CLI reports
different cached login states when CLAUDE_CONFIG_DIR is unset versus explicitly
set to the same default path. A 0.001-second regression reproduces the namespace
selection error. Default and directory login scopes are now explicit profile
fields; default scope preserves the native unset-variable behavior and verifies
HOME against the frozen directory. A credential-free auth-status probe then
identifies the already-authorized Max login. Old profiles without this field
retain directory scope. No credential is copied between namespaces.

The first genuine Luna subscription image/compaction/fork check is stopped by its
conservative observer and remains failed. Its reported counters include inherited
parent usage in the child: summing the two counters gives 167,846 tokens and a
US$0.335692 proxy at US$2/M, beyond the observer's US$0.25 stop threshold. The
observer closes the native app-server; the preflight subsequently records its
bounded deadline failure. This is not a passing compatibility receipt or a
provider invoice. There is no robot world or physical action. Native token
counters, fork identities and original failed reports remain retained for
accounting and a correctly bounded fresh check.

## Managed subscription source-pinned acceptance at c1c7abb

Complete discovery passes 1,556 checks on each of macOS and Linux, with zero
failures/errors and 17 conditional skips. Linux uses an independent committed
checkout and verifies all 45,141 pinned fixture files before discovery; the
snapshot boundary stress test also passes 1,000 repetitions. Eight opt-in native
Claude/real-physics checks pass on each platform without skips in 98.478 and
98.904 seconds. Their model endpoints remain synthetic loopback services. These
results do not qualify subscription concurrency, every physical interruption
boundary, or real-model task-solving ability.

Genuine Haiku 5.5 native Max subscription prechecks at this source pass all four
basic checks and all ten blocked-parent fork assertions. Profile fingerprints,
CLI version, explicit native identities, cost completeness and both receipts
match current configuration. Their list-price estimates are US$0.005948 and
US$0.001311. No provider API key is supplied and no physical world is involved.
The earlier namespace failure remains separate and failed.

The fresh GPT-6 Luna high native Pro subscription check passes image/function
round trip, manual compaction, verified parent identity and inherited image/tool
history in the child. Effective native MCP configuration is checked before the
first model turn. Automatic compaction, long-context stress and independent
backend alias verification remain unclaimed. A native counter observer counts
142,120 tokens, conservatively estimated at US$0.284240 using US$2/M for every
token type. It subtracts inherited fork totals only when native cumulative and
last-turn counters prove inheritance; the separate compaction counter is added.
The observer was replayed against the original recorded failure before this
fresh invocation. It changes no requests, model selection or tool results.
The failed first check is moved with identical per-file hashes to a dedicated
failure directory, never overwritten or relabeled passing.

Including the entire uncertain physical trial allowance, the old failed Luna
proxy and all native Haiku estimates, reserved exposure is US$0.9493736 against
the user's unchanged US$1 aggregate authorization. US$0.0506264 remains. These
are conservative proxies and native CLI list-price estimates, not invoices.
No uncertain reservation is released and no further physical/model trial is
implicitly authorized by a compatibility receipt.

Review against main 8b75325 covers all changed production paths: native home
selection, default/directory credential namespaces, no credential environment
inheritance, prelaunch endpoint validation, history provenance and stopped
collection, including collection rejection when the auth home is inside the
batch. Only bound session histories and sidecars enter stopped exports; the
original account store remains native-owned. Missing live auth is not replaced
by an exported history directory. The known-server disable overrides and the
effective-config admission check keep unrelated Codex MCP servers out of policy
tools. No blocking engineering-code finding remains in this scoped review.

A separate zero-provider experiment evaluates Claude's official safe mode.
That mode also removes the explicitly assigned robot MCP, so it is not promoted
into the benchmark launcher. Its failed tool check and earlier relative-path
driver failures remain separate from genuine subscription receipts. The
production settings-source and strict-MCP options remain unchanged.

The local single-account Codex forced-refresh/persistence witness passes.
Claude login and cached-login compatibility pass, but actual expired-token
refresh is still unverified: the documented CLI offers login/status/logout and
no force-refresh action. Credentials and the system clock are not altered to
manufacture expiry. Claude formal scored execution remains closed; the earlier
real physical trial does not establish delegation, handback or normal finish.
Docker/Slurm subscription authentication and concurrent account refresh also
remain outside these local receipts. Candidate defaults are not promoted and
the user's full-video rerender deferral remains in effect.

## Subscription evidence collection follow-up

Review finds that shared native Claude homes need their bound Adaptive snapshot
anchors collected as well as policy-role sessions. The prior collector handled
snapshot anchors only for Codex; an account-independent archive regression fails
in 0.015 seconds with an empty snapshot inventory despite a recorded anchor and
an existing native transcript. Collection now copies the recorded Claude anchor
and its session sidecars, records it separately from actors, and includes its ID
in a new stopped-history marker. Unrelated sessions and credentials remain
excluded. Restoring the archive with the original native home unavailable retains
both the snapshot history and its image-reference sidecar. The original failed
regression and a separate test-driver module-name error remain preserved.

A second, newly authorized physical engineering trial uses Haiku's native Max
subscription at cb8d013 with unchanged Adaptive Transport L1 public inputs. Its
allowance is US$0.04 from the same aggregate budget, US$0.01 per turn, with an
external three-minute stop and the original public 24-hour task limit. A local
driver argument error occurs before the batch is claimed or a world/model is
started; the corrected driver uses that still-unclaimed preparation once. The
trial performs two robot calls including a real observation and ends its native
turn normally, reporting US$0.0095626 as a list-price estimate. It issues no
physical action, delegation, handback or normal task finish before the external
stop. The independent interruption evaluation reports false task success. Its
owner is sealed and exited with no unresolved action; accounting is tracking
without a budget-review requirement. This remains an unsuccessful qualification
attempt, not a formal scored result or proof of model task-solving ability.

Keeping even this trial's full US$0.04 allowance reserved gives US$0.9893736
aggregate exposure and US$0.0106264 remaining. The original uncertain API trial
allowance and failed Luna proxy remain fully reserved. No further model trial
is launched automatically. Actual Claude expired-token refresh and formal scored
qualification are still open gates; no passing source test clears them.
