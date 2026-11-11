# Experiment evidence: collection, compression and restore

Collection and archiving work the same for both engines. They make no model calls, advance no
physics and change no score, and they never delete the original batch.

| Form | Purpose | Written during a run? |
| --- | --- | --- |
| Batch folder and native session homes | Execution, motion capture, provenance | Yes, by their owning processes |
| Collection (`<runs root>/exports/<batch>-<hash>/`) | Portable stopped copy with task/session mappings and file hashes | No; refused while a writer lives |
| Evidence ZIP (beside the collection) | Deduplicated, compressed, reversible archive | No |
| Extracted archive | Compressed objects and the archive manifest | Not usable as sessions or motion |
| Restored collection | The collection's original bytes, for analysis and replay | No; not a resumed experiment |

`robofrontier run` collects and archives a batch when it ends (`evidence.auto_collect`,
`evidence.auto_archive`, both on by default). Docker and Slurm copy only that ZIP back to the
host ([Docker](docker.md), [Slurm](slurm.md)).

## Collect by hand

Run the collector on the machine, container or node that ran the batch, after the supervisor,
role hosts and worlds have all stopped:

```sh
.venv/bin/robofrontier collect runs/policy/MY_BATCH --output runs/exports/MY_BATCH
```

The lower-level entry is `.venv/bin/python -m robofrontier.batch.collect BATCH --output DIR`;
it exits 1 after publishing a collection that needs review.

- The collector checks writer locks, recorded host processes and terminal state, and detects
  source changes during copying. SQLite is inspected on a disposable copy. A lock check cannot
  establish liveness on another machine, so never collect a container's or node's batch from
  outside it.
- Only registered role, delegation and snapshot sessions are collected, not the whole native
  home; snapshot sessions are listed in `jobs[].snapshot_sessions`. A missing required session
  makes the collection incomplete.
- Claude collections include each run's `private/engine/config/projects/**/*.jsonl`, auxiliary
  transcripts, referenced tool results and `private/evidence/*.jsonl`, plus a `sessions/` index.
  No other Claude configuration (credentials included) is copied.
- Unresolved physical requests, missing motion, corrupt chunks or changed source assets become
  explicit issues in `jobs[].issues`.
- `collection.json` (`robofrontier.policy-collection.v1`) records file hashes, models, topology
  and session/role associations. `complete: true` means the collection checks passed, not that
  any task succeeded.
- An existing destination is refused; live writers, unsafe paths or changed files fail
  without publishing anything. Symlinks are not followed.

## Archive, extract, restore

```sh
.venv/bin/robofrontier archive runs/exports/MY_BATCH --output runs/archives/MY_BATCH.zip
.venv/bin/robofrontier extract runs/archives/MY_BATCH.zip --output runs/extracted/MY_BATCH
.venv/bin/python -m robofrontier.batch.archive_policy_batch restore runs/extracted/MY_BATCH \
  --output runs/restored/MY_BATCH
```

Every destination must be new. `extract` verifies the ZIP and publishes the compressed object
folder; **`restore` is required** to get ordinary JSONL, motion chunks, images and frozen inputs.
Never point a session reader or motion renderer at `objects/`.

`archive` keeps incomplete collections too, with `collection_complete: false` and every issue;
it cannot fill gaps, settle unknown actions or change a score. The directory form requires a
complete collection unless told otherwise:

```sh
.venv/bin/python -m robofrontier.batch.archive_policy_batch create runs/exports/MY_BATCH \
  --output runs/archives/MY_BATCH-directory [--allow-incomplete]
.venv/bin/python -m robofrontier.batch.archive_policy_batch verify runs/archives/MY_BATCH-directory
```

How the archive stores data:

- Identical content is stored once by SHA-256; text and objects are compressed with zlib. The
  outer ZIP uses stored entries, since its payloads are already compressed.
- Images inside data URIs and recognized MCP/Anthropic Base64 image fields are extracted into
  image objects and restored byte for byte (`jsonl_images_v2`). Unrecognized formats keep their
  original bytes.
- Creation validates every file's reconstructed size and SHA-256; restore checks every object
  and publishes only after validation. Paths, bytes, permissions and modification times are
  kept; inode identity, ownership, access time and extended attributes are not. Hashes detect
  corruption; they are not signatures.

Ship a dataset with the source revision that made it, so the matching restore tool is used.

## Restored layout

```text
runs/restored/MY_BATCH/
  collection.json                     # Models, roles, sessions and file hashes
  sessions/<profile>/<case>/          # Associated native session JSONL
  batch/<profile>/<case>/
    public/observations/              # JPEG observations
    private/
      inputs/                         # Frozen scene, assets, source and settings
      evidence/                       # Claude CLI turn events, when present
      engine/                         # Engine config and transcript copies
      state/                          # Runtime database and related evidence
      outputs/
        motion/                       # stream.json, chunks, events and source/
        suite-process.jsonl           # Evaluator/process evidence
```

Original absolute paths stay unchanged for audit; use the collection's relative mappings on
another machine. Restoring does not restart a world or repeat physical actions.

## Motion, observations and replay

- Motion is `robofrontier.motion.v1`: float32 states (capture's float64-to-float32 conversion
  is the only quantization), XOR deltas and NPZ chunks; archiving reconstructs them exactly.
- Observations are JPEG 896 x 560, quality 85 (`render.observation_profile`). The archiver never
  re-encodes them.
- Session transcripts keep their full history; the archiver does not drop repeated messages.
- Replay uses the recording's own `motion/source/`. Factory replay needs a matching Factory scene
  and assets ([Factory replay](../factory/replay.md)); observation resolution does not cap later
  video, which defaults to 1920 x 1080.

To compare an original collection with its restored copy:

```sh
.venv/bin/python -m scripts.verify_evidence_replay runs/exports/MY_BATCH \
  runs/restored/MY_BATCH --output runs/engineering/MY_BATCH-replay-check
```

It compares every file hash, all motion states, timestamps and appearance events, then rendered
first/middle/last samples; `--factory /path/to/scene.xml` adds Factory geometry and image
checks. Read `report.json` for the coverage; samples are not a full video or a task result.

## Space and privacy

Reserve space for the batch, the collection, the archive and temporary files; restoring needs
the full uncompressed size. Archive a 36-task batch once, sequentially. These tools need no API
keys. Evidence holds model trajectories, private task inputs and connection details: keep it
private and review it before sharing. Keep an independent backup and verify a restore before
removing any source.

## Storage settings of policy runs

`configs/harnesses/policy.json` freezes these into each run's `harness.json`:

- `motion_hz: 30`: 30 motion states per simulated second. Colour changes are written on the
  physics clock to `motion/events.jsonl`.
- `process_log: "events-10s"`: `suite-process.jsonl` starts with the header
  `robofrontier.suite-process.v2`. The scorer samples every 0.02 simulated seconds and writes a
  `type: event` line whenever a non-continuous result field changes, and a `type: snapshot`
  line with object poses every 10 simulated seconds and at the end. Continuous fields
  (accumulated `*_s` seconds, `samples`, raw Dial angles, speeds and clearances, Relay
  `timber_inside_fraction`) appear only in snapshots. Each Dial trial is written with its event.
  On 600 simulated seconds of moving arms this is about 2.6 MB per simulated hour for
  `transport-a12-d3` and 20 MB for `mosaic-a08-12x24-d3`.

Other values the harness accepts: `events-1s` and `events-60s` (snapshots every 1 or 60 s; with
`events-60s` a scene that records motion leaves poses out of all but the last snapshot, and
`robofrontier.analysis.motion_query.object_poses` reads them from the recording), and `full`
(a complete snapshot every 0.1 s, which Oracle tooling reads).

## Session transcripts

A Claude run keeps its transcripts in `private/engine/config/projects/`. Codex writes them into
its home; at the end of every segment the Codex host copies each thread of the run (roles,
delegates and snapshot anchors) into `private/engine/transcripts/`, verified by SHA-256 and
listed in `index.json`. The host never deletes the home originals, since a continued segment
resumes those threads. Reports and collection read the run's copies first.

Once a run is final and idle, compress its transcripts:

```sh
.venv/bin/python -m robofrontier.batch.session_archive archive RUN_DIR
```

Each transcript becomes `.jsonl.xz` in place, and for Codex the home originals are removed.
Every compressed copy must decompress to the original SHA-256 and be recorded in
`private/outputs/session-archive.json` before its original goes; a home original goes only
while it still equals the run's verified copy. A run that could still be continued is refused
unless `--final` says it will not be. Readers accept both forms, and an interrupted archive
resumes on the next call.

## Videos of policy runs

`robofrontier/media/render.py` renders each run's simple-background video at 1280 x 720 and its
family speedup (Mosaic 30x). It keeps only meaningful motion (`robofrontier/media/motion_cut.py`:
directed arm, finger or object motion), then drops rendered frames in which no view visibly
changes, until no still stretch is longer than two frames. The resulting `motion-cut.json` maps
to the recording's own states; pass it to `robofrontier factory import-motion --timeline` so the
1920 x 1080 Factory video shows the same states. The recording is never changed.
