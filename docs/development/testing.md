# Testing

All tests run offline: none calls a model provider. Install the locked environment and restore
the assets first ([getting started](../getting-started.md)):

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
```

The CI `all-tests` job installs the same Oracle extra so the complete suite can import its reference controllers.

Node.js is needed for the Node host tests. Tests that drive an installed engine CLI run it against
a local stub model and skip when the CLI is absent.

## Every test, in parallel

```sh
.venv/bin/python -m scripts.run_tests                          # one worker per CPU
.venv/bin/python -m scripts.run_tests runtime engines.test_codex_quota --workers 4
.venv/bin/python -m scripts.run_tests --report runs/engineering/all-tests.json
```

Each `tests/**/test_*.py` module runs in its own process and each `tests/**/test_*.js` with
`node --test`. Arguments name modules (`runtime.test_run_segments`) or folders under `tests/`
(`engines`). A failed module runs once more alone; only a repeated failure counts, and the report
says which modules failed only in parallel. Other options: `--timeout-s`, `--no-node`,
`--skip NAME ...`. The command exits 1 when a failure repeats.

Tests that start a world open a hidden GLFW window. On macOS the screen must be unlocked (the
window service does not answer otherwise); on Linux use a display, for example
`xvfb-run -a -s "-screen 0 1920x1080x24"`.

## One module

```sh
PYTHONPATH=tests:scripts .venv/bin/python -m unittest runtime.test_pipeline
node --test tests/engines/test_tool_errors.js
```

## The harness checker

```sh
.venv/bin/python -m scripts.check_harness --protocol-only --report runs/engineering/protocol.json
.venv/bin/python -m scripts.check_harness --report runs/engineering/full.json
```

`--protocol-only` runs a fixed set of contract modules with MuJoCo model creation and stepping
blocked; the full mode discovers every Python test. Both also run the Node host tests, JavaScript
syntax checks and the documentation link check. What each covers is in
[harness check coverage](../harness-verification.md).

## Physics validation

```sh
.venv/bin/python -m scripts.validate_physics                    # every scenario, every case
.venv/bin/python -m scripts.validate_physics carry dial --workers 4
.venv/bin/python -m scripts.validate_physics rest --cases transport-a04-d1
```

Scenarios: `rest`, `carry`, `place`, `push`, `collide`, `relay`, `dial`, `timing`. Results go to
`runs/engineering/validate-physics/<time>.json`; `tests/physics/test_validation.py` runs a fast
part. Criteria and the current status are in [physics](../physics.md#validation).

## CI

`.github/workflows/harness.yml` runs on every pull request and on pushes to `main`:

| Job | What it runs |
| --- | --- |
| `harness` | `check_harness --protocol-only`, then the engine parity, run layout, segment, evidence storage and policy environment modules |
| `all-tests` | `scripts.run_tests --workers 4` under `xvfb-run`, with the scene assets restored |
| `analysis-and-scripts` | Analysis, script and record tests without scene assets, so nothing can load a scene |

`all-tests` sets `ROBOFRONTIER_OUTAGE_PROBE=off` and `ROBOFRONTIER_NO_NOTIFY=1`; set them locally
too to keep the network-outage probe and desktop notifications out of test runs.

## Skips and opt-in tests

A test skips, rather than fails, when what it needs is absent: an engine CLI, Linux or a Landlock
ABI, the restored scene assets, or ignored local data (finished runs, Oracle source edits under
`outputs/oracle/`). Read the skipped count in the report; a skipped test is not a pass.

These environment variables turn on longer tests that need a native CLI or local data:

| Variable | Test |
| --- | --- |
| `ROBOFRONTIER_PHYSICS_SMOKE=1`, `ROBOFRONTIER_PHYSICS_VIDEO=1` | `engines.test_claude_physics_smoke`, with video |
| `ROBOFRONTIER_PHYSICS_BATCH=1` | `engines.test_claude_parallel_physics_smoke` |
| `ROBOFRONTIER_PHYSICS_STANDING=1`, `ROBOFRONTIER_PHYSICS_SIGNAL=1`, `ROBOFRONTIER_PHYSICS_FINISH=1`, `ROBOFRONTIER_MOSAIC_IMAGE=1` | Claude standing-team, signal, finish and Mosaic image integration tests |
| `ROBOFRONTIER_NATIVE_TEST_RECEIPTS=1` | Keep the receipts of `engines.test_claude_standing_team_integration` |
| `ROBOFRONTIER_PRESERVATION_CHECK=1` | `repo.test_oracle_preservation`, which hashes the protected Oracle files (several minutes) |

## Filesystems

Keep test databases, engine homes, temporary executables and fixture outputs on one local
filesystem. Never open an active SQLite database across a Docker or network-filesystem boundary.
In a Linux container, give the tests writable local temporary folders and a writable bytecode
location. Linux CPU and Mesa results do not cover NVIDIA EGL, real Slurm allocations or
36-run resource capacity.
