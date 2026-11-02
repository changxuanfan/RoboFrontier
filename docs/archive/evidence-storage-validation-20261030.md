# Evidence archive synchronization: 2026-10-30

This dated acceptance snapshot covers the Codex, Claude, Luna CPU and Luna
multi-topology worktrees. Shared collection, archival, restoration, replay checks,
tests and operating documentation had matching per-file hashes. The multi-topology
branch also received JPEG profiles, public calibration and host MIME handling,
while retaining its CPU rendering, performance capture and communication logic.
For the current integration, use the [acceptance ledger](unified-main.md).

No new model calls or paid benchmarks were launched. Task releases, physics,
scoring, START and collaboration prompts were unchanged. Original experimental
data was retained; the checks below used existing recordings offline.

## Code checks

| Environment/branch | Coverage | Result |
| --- | --- | --- |
| macOS Codex | Collection, archives, image profiles, Motion | 24 passed |
| macOS Claude | Same, plus Claude runner and tool-error handling | 38 passed |
| macOS Luna | Shared features, Luna command compatibility, images, Motion | 34 passed |
| macOS multi-topology | Shared features, original Luna entries, images, Motion | 34 passed |
| Linux Docker, Luna CPU image | Collection, archives, images, Motion | 24 passed |
| Final archive/collector core revision | Shared core checks on macOS and Linux | 15 passed on each |
| Codex/multi-topology JavaScript | JPEG/PNG, action-result retention, call-ID conflicts | 4 passed on each |
| Final pre-publication check, macOS/Linux | Collection, archives and replay entries | 21 passed on each |
| Clean source snapshots of four branches | Standard-library collection/archive tests without `.env`, `runs/` or `vendor/` | 18 passed on each |

Publication checks additionally rejected source mutation after initial validation,
refused to omit native Claude auxiliary records added during copying, and rejected
empty, missing-Motion or incompletely covered replay inputs. A historical PID
reused by an unrelated process did not block collection; a live owner did.
Readable but corrupt engineering records could only be retained as explicitly
incomplete evidence.

Shared checks covered task/model directory separation in synthetic 36-case
batches; Controller/Worker/Coordinator/delegate collection; native Claude paths
and auxiliary records; authentication exclusion; writer locks and live PIDs;
mutation during copying; explicit incomplete archival; changing inventories;
restoration of three known image structures and fallback for unknown structures;
corruption detection; and streaming restoration of highly compressed files.
The 36-case fixtures were offline constructed data, not 36 new model trials.

Missing ignored assets in historical Motion fixtures were restored from local
byte-identical assets against their existing SHA-256 manifests. No approximate
replacement was generated or expected value changed. This did not add historical
test assets to the current release. Core collection/archive checks require only
the Python standard library; image, Motion and replay checks require the relevant
scene assets and rendering dependencies.

## Restoration of actual recordings

| Existing recording | Files | Original collection | Archive | Reduction | All-frame comparison |
| --- | ---: | ---: | ---: | ---: | ---: |
| Luna, four families, Level 1, minimum arms, 10-minute batch | 3,215 | 510,111,516 B (486.5 MiB) | 76,910,307 B (73.3 MiB) | 84.9% | 139,749 frames |
| Claude Haiku Transport engineering recording | 632 | 107,246,157 B (102.3 MiB) | 13,974,660 B (13.3 MiB) | 87.0% | 18,389 frames |

Every restored file matched the pre-archive collection by SHA-256. All float32
Motion states, timestamps and appearance events were identical. Both batches
passed the final collector again with inventories matching their verified
archives. The Claude recording remained interrupted/timed-out engineering data;
its task result was not changed.

The final tools recreated temporary archives from both collections before
publication, restored and verified them again: 3,215/632 files and
139,749/18,389 frames, with identical sampled simple-scene pixels. Receipts are
`luna-publish-check.json` and `claude-publish-check.json` in the respective
verification directories.

First/middle/last simple-scene images matched pixel-for-pixel for all four Luna
families. Separate local Factory candidate scenes matching R14 and the recorded
physics passed geometry mapping for three states per family. Original/restored
Factory first/last images matched pixel-for-pixel and short previews decoded.
The three simple-background Claude Transport samples also matched.

Factory checks replayed recorded MuJoCo poses. They did not create new full
Blender Cycles videos or render every frame. The candidate Factory scenes/assets
were separate verification inputs, not automatically included in policy archives
or this four-branch synchronization. Matching sampled images do not establish
model task success.

The new restorer also verified the older 4,599-file Luna archive. Existing PNGs,
Motion formats and frozen inputs were not rewritten.

## Local evidence and limits

The Luna worktree's ignored `runs/engineering/compression-sync-20261030/` contains
`luna-collection/`, `luna-archive/`, `luna-restored/`, `luna-replay-check/report.json`
and `luna-final-collector-check.json`. The corresponding Claude worktree directory
contains the matching `claude-*` artifacts. These include private experimental
data and are not published as repository source.

See [collection, archival and restoration](../running/evidence-storage.md) for operation and
current boundaries. This acceptance covers offline archival after writers stop.
It does not automatically reduce active-run storage or remove multiple retained
source copies. Cross-host paths, native CLI resume, different CLI versions and
uncovered models require their own verification.

At this snapshot, the host's fixed deadline was not yet corrected; later timing
changes must be assessed from their own code/tests. Slurm node-local staging and
stage-out had not been verified by these archive checks. Active SQLite WAL
belongs outside Lustre/NFS and must not be opened across Docker filesystem
boundaries. These results did not qualify formal 36-case, 24-hour execution.
