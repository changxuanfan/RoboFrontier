# Experiment evidence: collection, compression and restore

The unified Codex/Claude paths share stopped-evidence collection and archival.
These commands make no model calls, advance no physics and change no score.
Original task/session data remain available. For source-specific earlier checks,
see the [2026-10-30 validation record](../archive/evidence-storage-validation-20261030.md);
new integration evidence is in the [acceptance ledger](../archive/unified-main.md).

## Original, collected and archived data

| Form | Purpose | Writable during a task? |
| --- | --- | --- |
| Original batch and native session home | Native execution, motion capture and original provenance | Yes, by their owning processes |
| `runs/exports/MY_BATCH/` | Portable stopped collection with task/session mappings and file hashes | No active source writers permitted |
| `MY_BATCH.zip` | Deduplicated, compressed, reversible evidence archive | Offline delivery artifact |
| Extracted archive directory | Compressed objects and archive manifest | Not directly usable as native sessions/motion |
| Restored collection | Reconstructed original collection bytes for analysis and replay | A restored dataset, not an automatic resumed experiment |

Copies permit native history to stay intact while a portable package is checked.
A ZIP does not automatically replace or delete its sources. Keeping all forms
uses more total disk than retaining one verified archive plus an independent
backup. Cleanup is a separate, explicitly scoped operation after restore/use
verification; the commands below do not delete originals.

## Collect only after all writers stop

Use the original execution machine/container and the same mounted paths. The
batch supervisor, role hosts and physical owners must be finished. Do not read a
container's active SQLite files from macOS, or archive a live Slurm job. Live WAL
and native Codex state belong on verified node-local storage, not Lustre/NFS.
Monitor atomic supervisor JSON or supported status commands during execution.

```sh
.venv/bin/robofrontier collect runs/policy/MY_BATCH --output runs/exports/MY_BATCH
```

Use the actual Claude engineering batch path for Claude. The shared lower-level
entry is also available:

```sh
.venv/bin/python -m scripts.collect_benchmark_batch runs/policy/MY_BATCH \
  --output runs/exports/MY_BATCH
```

Legacy Luna/multi-topology collection forwards to this same collector. New API
runs resolve each task's `codex-home.json`; batch markers support older shared
homes. Unmarked historical batches fall back to explicit `--codex-home`,
`CODEX_HOME` or the environment default. Only registered role and delegation
snapshot sessions are collected, not the entire native home. Snapshot sessions
appear in `jobs[].snapshot_sessions`; they are not active policy roles. A missing
required snapshot makes collection incomplete.

The collector checks existing supervisor/world writer locks, recorded Codex host
processes and terminal state, then detects source changes during copying.
SQLite inspection uses a disposable copy; original DB/WAL/SHM bytes are retained.
Unresolved physical requests, missing task motion, corrupt chunks or changed
source assets become explicit issues. Manifest checks do not replace full motion
decode/render checks. PID/lock tests cannot reliably establish another machine's
or container's liveness; run the collector in the owning environment.

Claude collection includes native `private/claude-config/projects/*/<session>.jsonl`,
associated auxiliary transcripts, referenced tool results and batch-local
`private/evidence/*.jsonl`. It preserves a convenient `sessions/` index plus the
required relative native layout; identical content is deduplicated at archival.
Other Claude config content, including authentication, is excluded. Restoring
native CLI sessions still needs separate credentials and version/path checks;
collection is not a guarantee of cross-version native resume.

`collection.json` uses `robofrontier.policy-collection.v1` and records file hashes,
models, topology and session/role associations. Roles come from runtime records,
including legacy Coordinator, current Controller, permanent Workers and Adaptive
delegates; names are not hardcoded. Failed or timed-out tasks still have valuable
evidence. `complete: true` means collection checks passed, not task success or
scored eligibility.

Existing destinations are refused. The lower-level collector exits 1 after
publishing a review-required collection; inspect `jobs[].issues`. Live writers,
unsafe paths or changed files fail without publishing a partial destination.
Source symlinks are not silently followed.

## Deliver a ZIP and restore it

The unified default automatically collects and archives stopped policy batches.
For manual offline delivery:

```sh
.venv/bin/robofrontier archive runs/exports/MY_BATCH \
  --output runs/archives/MY_BATCH.zip
.venv/bin/robofrontier extract runs/archives/MY_BATCH.zip \
  --output runs/extracted/MY_BATCH
.venv/bin/python -m scripts.archive_policy_batch restore runs/extracted/MY_BATCH \
  --output runs/restored/MY_BATCH
```

All destinations must be new. `extract` verifies the ZIP and archive objects,
then publishes the compressed object directory. **The final `restore` step is
required** to obtain ordinary JSONL, motion chunks, images and frozen inputs.
Do not point a native session reader or motion renderer at `objects/`.

The unified archive intentionally preserves stopped incomplete collections too,
retaining `collection_complete: false` and every issue. It cannot fill missing
data, reconcile unknown actions or upgrade a score. This differs from the
lower-level directory archive, which defaults to requiring complete collection:

```sh
.venv/bin/python -m scripts.archive_policy_batch create runs/exports/MY_BATCH \
  --output runs/archives/MY_BATCH-directory
.venv/bin/python -m scripts.archive_policy_batch verify runs/archives/MY_BATCH-directory
```

For reviewed stopped incomplete evidence, that lower-level `create` accepts
`--allow-incomplete`; it does not bypass live-writer checks. The directory and ZIP
formats contain the same compressed object archive. ZIP payloads are already
compressed, so the outer evidence ZIP uses stored entries rather than another
expensive compression pass.

The archive stores identical content once by SHA-256 and compresses text/object
payloads with zlib. It reversibly extracts images from data URIs and recognized
MCP/Anthropic Base64 image fields into image objects. **Image bytes are retained**;
this is not deletion of the observations an agent saw. Different JPEG encodings
remain different byte payloads even if visually similar. Unknown, noncanonical
or escaped formats fall back to original bytes rather than a guessed transform.
Sessions, CLI events, evaluation, process logs, motion and frozen inputs remain
in the collection inventory.

Creation validates reconstructed size and SHA-256 for every file. Restore checks
all objects and publishes the destination only after successful validation;
failed temporary restoration is removed. Relative paths, file bytes, ordinary
permissions and modification times are retained. Inodes/hardlink identity,
ownership, access time and extended attributes are not guaranteed. Hashes detect
corruption; they are not third-party signatures or source authentication.

Old `robofrontier.luna-collection.v1` collections and older image-URI archives
remain readable. New `jsonl_images_v2` transforms need this or a newer restoration
tool; old tools cannot restore the new encoding. Distribute the matching source
revision with a dataset rather than an arbitrary older restore script.

## Restored layout

```text
runs/restored/MY_BATCH/
  collection.json                    # Models, roles, sessions and file hashes
  sessions/<profile>/<case>/          # Associated native session JSONL
  batch/<profile>/<case>/
    public/observations/              # Recorded old PNG or new JPEG observations
    private/
      inputs/                         # Frozen scene, assets, source and settings
      evidence/                       # Claude CLI turn events, when present
      claude-config/projects/         # Required native transcript layout, if present
      state/                          # Original runtime DB and related evidence
      outputs/
        motion/                       # stream.json, chunks, events and source/
        codex-host.jsonl              # Codex host events, when present
        suite-process.jsonl           # Evaluator/process evidence, when present
```

Historical batches without a profile use `sessions/<case>/`. Original absolute
paths stay unchanged for audit. Use collection-relative mappings on another
machine; do not silently rewrite native evidence. Restoration does not restart
a world or repeat physical actions.

## Motion, observations and Factory replay

The motion format remains `robofrontier.motion.v1`. Capture's existing
float64-to-float32 conversion is declared numeric quantization. Subsequent XOR
and ZIP compression reconstruct float32 states exactly, without further
quantization. Static frames, timestamps, appearance events and process evidence
are not deleted. Repeated static state compresses well without removing temporal
coverage. `suite-process.jsonl` uses ordinary lossless compression.

New observations default to JPEG 896 x 560, quality 85. Frozen older runs lacking
a profile keep PNG 1280 x 800. New camera calibration uses a derived image-size
copy while retaining the original signed input. The lossless archiver does not
transcode historical PNG or re-encode JPEG. An explicitly requested historical
PNG-to-JPEG migration is lossy and must have its own original-to-derived mapping,
quality setting and acceptance; it must not masquerade as byte-exact archival.
Live native logs are not edited, and archival does not change API input/cache or
billing behavior.

Native session JSONL records the engine's history; a large provider input-token
counter is not by itself proof that every full request was stored repeatedly.
Forked transcripts and CLI/host evidence can contain overlapping information.
The archiver preserves their semantics and exact restore rather than removing
apparently repeated messages. Reversible image extraction and identical-file
object deduplication address the major duplication without guessing which
messages are unimportant.

Replay uses the recording's own `motion/source/`. Factory needs a matching
Factory scene/manifest and its textures/meshes, or a newly imported bundle built
from that recording's frozen source. Different release colors, R14/R13 scenes
and appearance events are checked rather than bypassed. Archive restore does not
generate a Factory or include unrelated assets outside the collection.
Observation JPEG resolution does not cap later video: offline render settings
independently default to 1920 x 1080.

For additional original-versus-restored replay checks:

```sh
.venv/bin/python -m scripts.verify_evidence_replay runs/exports/MY_BATCH \
  runs/restored/MY_BATCH --output runs/engineering/MY_BATCH-replay-check
```

Optional `--factory /path/to/matching-factory/scene.xml` adds diagnostic Factory
checks. The verifier compares every file hash, all motion states/timestamps and
appearance events, then simple-scene first/middle/last rendered samples. Factory
checks compare mapped geometry and sampled images and decode a short preview.
Distributed samples do not constitute a complete continuous video or task
success. Read `report.json` for actual task/frame coverage. Current all-family
Factory acceptance additionally audited all 9,514 frames of four specific new
engineering recordings; that is source-specific evidence, not all future data.

## Space, environment and privacy

Reserve space for original data, collection, archive and temporary files.
Restoration requires the full uncompressed size. File compression streams data,
but JSONL image processing depends on the largest line/image; validation scratch
space depends on the largest file. Collect a 36-task batch once, then archive
sequentially instead of launching 36 archive workers.

Use supported offline commands inside the original owning container/node before
stage-out. The unified [Docker](docker.md) and [Slurm](slurm.md) paths handle their
own stopped collection and ZIP export. A host-side read of an active container
SQLite database is not a monitoring method. These offline tools do not need API
keys; do not pass provider credentials merely to archive data.

Evidence contains model trajectories, private task inputs and runtime connection
information. Keep it private and review before sharing. Excluding authentication
stores does not anonymize a dataset. Retain an independent backup and verify
restoration/use before considering source cleanup. Automatic evidence processing
keeps sources by default and never converts an uncertain action into a replay.

## Storage settings for new policy runs

`configs/harnesses/policy.json` freezes two settings into each run's
`harness.json`; runs prepared without them keep the original behaviour.

- `motion_hz: 30`: motion is recorded at 30 states per simulated second
  (float32, XOR deltas and NPZ chunks are unchanged). Colour changes are still
  written on the physics clock to `motion/events.jsonl`. The default is 60.
- `process_log: "events-1s"`: the first line of `suite-process.jsonl` is the
  header `robofrontier.suite-process.v2`. The scorer still samples every 0.02
  simulated seconds; whenever a non-continuous result field changes it writes a
  `type: event` line, and every second and at the end it writes a
  `type: snapshot` line with object poses. Continuous fields (accumulated `*_s`
  seconds, `samples`, raw Dial angles, speeds and clearances, Relay
  `timber_inside_fraction`) appear only in snapshots, also inside nested lists.
  The default `full` keeps a complete snapshot every 0.1 s, which Oracle tooling
  reads. Converting finished Dial, Mosaic, Relay and Transport logs offline gave
  about 11% of the original size, with every event field recoverable at every
  original sample time.

## Session transcripts

A Claude run keeps its transcripts in its own `private/engine/config/projects/`.
Codex writes them into its shared home; at the end of every segment the Codex
host copies each thread of the run (roles, delegates and snapshot anchors) into
`private/engine/transcripts/`, verified by SHA-256 and listed in `index.json`.
The host never deletes the home originals, because a continued segment resumes
those threads. Reports and collection read the run's copies first.

Once a run is final and idle, archive it:

```sh
.venv/bin/python -m robofrontier.session_archive archive RUN_DIR
```

Each transcript becomes `.jsonl.xz` in place, and for Codex the home originals
are removed. Every compressed copy must decompress to the original SHA-256 and
be recorded in `private/outputs/session-archive.json` before its original goes;
a home original goes only while it still equals the run's verified copy. An
interrupted run that could still be continued is refused unless `--final` says
it will not be. Readers accept both forms, and an archive that stops part way
resumes on the next call.
