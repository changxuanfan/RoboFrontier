# Dated native Factory server acceptance: 2026-11-01

These checks were recorded on `codex/factory-server-handoff` before unified-main
integration. See the [native handoff](../factory/server.md) for commands and the
[unified Factory guide](../factory/replay.md) for current configuration. Data was published
as [factory-r14-20261101](https://github.com/changxuanfan/RoboFrontier/releases/tag/factory-r14-20261101).
This record establishes the scoped native data/rendering checks below, not
benchmark scores, a full presentation or acceptance of every later integration
change. New integration checks appear in the
[implementation ledger](unified-main.md).

## Data binding

- Complete archive: 5,839,108,494 bytes in seven parts. The lock in
  `configs/factory-assets.json` pins each part's size and SHA-256.
- Archive SHA-256:
  `c713bc84b9521000b7d0b166faa409b9a368b842aaa52c9689e0e2a95c8bb3fe`.
- Data-manifest SHA-256:
  `2d88810bc69b1104e128b72d9c1fc217a0dd0aeb195e49100ec909bfc10bda7e`.
- Full export, archive creation, restoration into another directory and
  manifest/checksum validation of 123,198 files passed.
- The public download did not require GitHub login. The release service's
  SHA-256 values for all seven parts matched the repository lock.
- All 36 stations retained frozen sources and qualification flags. Mosaic was
  R14. Two reused d2 recordings in L3 displays retained `recorded_case_id`.

## Native macOS checks

The recorded environment was Python 3.12.6, MuJoCo 3.16.0, NumPy 2.5.4,
Blender 5.1.2 and FFmpeg 7.0.2. These video checks explicitly selected CPU.

| Check | Observed result | Qualification boundary |
| --- | --- | --- |
| Factory/evidence automatic tests | 34 passed | Includes safe paths, split restore, frozen plans, failure cleanup and actual subprocess SIGTERM |
| Full playback preparation | 72 items | 36 stations x front/side; not 72 fully rendered videos |
| 36-station FK | 108 sampled states passed | First/middle/last per desk; maximum position error about 5.03e-15 m; no physics integration |
| Minimum-arm Level 1, all four families | Eight front/side clips passed | Three frames each, 640 x 360, 8 samples, 30 fps; full decode and frame counts checked |
| Presentation entry | Three frames passed | Camera/playback-restart entry, not a full 210.5-second delivery |
| New benchmark motion import | One recording per family passed | Real closed Luna recordings with their own frozen source; first/middle/last FK and three-frame front previews; untrimmed edits retained |
| Factory diagnostics after evidence restore | Four families passed | Independent MuJoCo image/FK samples; not a substitute for Cycles video checks |

The recorded automatic-test command was:

```sh
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=tests:scripts .venv/bin/python -m unittest \
  test_factory_bundle test_factory_timeline test_factory_source_compatibility \
  test_factory_mesh_rotation test_factory_video_frames test_factory_array_replay \
  test_evidence_replay test_factory_desk_cameras test_factory_layout \
  test_factory_materials test_factory_backend
```

Real-data `test_factory_timeline` checks require setup; otherwise they explicitly
skip. A skip is not acceptance. The complete data package was installed for the
recorded local run, and those checks were not skipped. Re-execution on newer
source may have a different test count and must retain its own result.

## Linux and Slurm checks

A fresh clone ran on an Ubuntu 22.04 compute node with a newly installed
Python 3.12.11 environment. Asset preparation job `428551` automatically fetched
all public release parts, restored the package and passed full validation:
123,198 files, 36 stations and the release manifest SHA-256 matched. The same
CPU allocation loaded the full Factory and frozen sources, checking 36 stations
at first/middle/last for 108 geometry states, without physics integration or
model calls.

The compute node initially lacked `libxkbcommon.so.0`. Device check `428552`
and first video attempts failed, and the remaining attempts in that round were
stopped. After adding a user-space system-library path, device check `428561`
passed with Blender 5.1.2, NVIDIA H800 and driver 580.159.03. OPTIX saw only its
one allocated GPU. The dependency/configuration is documented in the handoff;
it was not source-data or motion corruption.

Re-submitted array `428562` used the same frozen plan; all eight items reported
`COMPLETED / 0:0`. Each family contributed minimum-arm Level 1 front/side clips,
three frames each, 640 x 360, 8 samples and 30 fps. Every video passed full decode,
frame count and checksum-verified return to shared storage, producing
`complete.json`. Failed attempts were retained rather than overwritten. A Mosaic
GPU video was downloaded and visually inspected.

The requested concurrency ceiling was two. Seven unrelated jobs already ran
under the shared account, so these render items actually executed serially.
This is not evidence for simultaneous rendering on two GPUs or its performance.

Independent CPU test job `428565` passed the recorded 34 tests in 14.023 seconds,
with no skips. FFmpeg/FFprobe were 7.0.2-static. All jobs created for this
acceptance ended; no other user's jobs were modified. Server outputs were under
that checkout's `runs/factory/linux-smoke/`, with videos indexed by CLI status.
Full receipts were under `runs/engineering/server-validation/`. They are ignored
runtime artifacts and do not arrive through Git clone.

The recorded acceptance did not render 72 complete desk videos or a complete
210.5-second presentation. Short-preview checks cannot establish those gates.
