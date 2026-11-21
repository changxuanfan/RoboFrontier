# Testing

All tests run offline: none calls a model provider. Install the locked environment and restore
the assets first ([getting started](../getting-started.md)):

```sh
uv sync --locked
.venv/bin/roboteam bootstrap
```

Node.js is needed for the Node host tests. Tests that drive an installed harness CLI run it against
a local stub model and skip when the CLI is absent.

## Formatting and lint

Python is formatted and linted with [ruff](https://docs.astral.sh/ruff/) at the version CI pins;
the settings are in `pyproject.toml` (110 columns, quotes kept as written). CI runs both checks
before the tests:

```sh
uvx ruff@0.17.5 format --check roboteam scripts tests    # without --check: rewrite the files
uvx ruff@0.17.5 check roboteam scripts tests             # --fix applies the safe fixes
```

The Codex host and the Node tests are formatted with Prettier (`.github/prettierrc.json`):

```sh
npx --yes prettier@3 --config .github/prettierrc.json --write roboteam/harness/codex/host/*.js "tests/**/*.js" "tests/**/*.cjs"
```

## Every test, in parallel

```sh
.venv/bin/python -m scripts.dev.run_tests                          # one worker per CPU
.venv/bin/python -m scripts.dev.run_tests runtime harness.codex.test_codex_quota --workers 4
.venv/bin/python -m scripts.dev.run_tests --report runs/checks/all-tests.json
```

Each `tests/**/test_*.py` module runs in its own process and each `tests/**/test_*.js` with
`node --test`. (`tests/harness/codex/test_meta_dispatcher.cjs` runs through the runtime checker
below.) Arguments name modules (`runtime.run.test_run_segments`) or folders under `tests/`
(`harness`). A failed module runs once more alone; only a repeated failure counts, and the report
says which modules failed only in parallel. Other options: `--timeout-s`, `--no-node`,
`--skip NAME ...`. The command exits 1 when a failure repeats.

Tests that start a world open a hidden GLFW window. On macOS the screen must be unlocked (the
window service does not answer otherwise); on Linux use a display, for example
`xvfb-run -a -s "-screen 0 1920x1080x24"`.

## One module

```sh
PYTHONPATH=tests:tests/helpers .venv/bin/python -m unittest runtime.world.test_pipeline
node --test tests/harness/codex/test_tool_errors.js
```

## The runtime checker

```sh
.venv/bin/python -m scripts.dev.check_runtime --protocol-only --report runs/checks/protocol.json
.venv/bin/python -m scripts.dev.check_runtime --report runs/checks/full.json
```

`--protocol-only` runs a fixed set of contract modules with MuJoCo model creation and stepping
blocked; the full mode discovers every Python test. Both also run the Node host tests, JavaScript
syntax checks and the documentation link check. What each covers is in
[runtime check coverage](test-coverage.md).

## Physics validation

```sh
.venv/bin/python -m scripts.release.validate_physics                    # every scenario, every case
.venv/bin/python -m scripts.release.validate_physics carry dial --workers 4
.venv/bin/python -m scripts.release.validate_physics rest --cases transport-small-l1
```

Scenarios: `rest`, `carry`, `place`, `push`, `collide`, `relay`, `dial`, `timing`. Results go to
`runs/checks/validate-physics/<time>.json`; `tests/sim/test_validation.py` runs a fast
part. The criteria and the results are in [physics](../benchmark/physics.md#validation).

## Fault injection

To test how a team recovers from one arm's failed action, a fault can be frozen into a prepared
run before it starts:

```sh
.venv/bin/python -m roboteam.runtime.world.fault_injection RUN_DIR --robot A --action-index 3
```

The third independent action of arm `A` (or of any arm, with `--robot '*'`) then times out
quickly and stays unsettled for a set time, so the role must use `recover_action`. The setting
is written to `private/inputs/fault-injection.json`, which the agents cannot read. It is named
in the manifest and marks the run's report as fault-injected. Use it for engineering runs only.

## CI

`.github/workflows/tests.yml` has one job, `all-tests`, on a clean Linux machine. It runs
`check_runtime --protocol-only`, then `scripts.dev.run_tests --workers 4` under `xvfb-run` with the
scene assets restored. It starts on pull requests, on pushes to `main` and by hand
(`workflow_dispatch`), except when a change touches only `docs/`, `site/`, `README.md` or the
licenses. Two paths under those folders still start it: `docs/runs/continuation.md` and
`site/data/`.

`all-tests` sets `ROBOTEAM_OUTAGE_PROBE=off` and `ROBOTEAM_NO_NOTIFY=1`; set them locally
too to keep the network-outage probe and desktop notifications out of test runs.

## Skips and opt-in tests

A test skips, rather than fails, when what it needs is absent: a harness CLI, Linux or a Landlock
ABI, the restored scene assets, or local data that is not in Git (finished runs). Read the
skipped count in the report; a skipped test is not a pass.

These environment variables turn on longer tests that need an installed harness CLI or local data:

| Variable | Test |
| --- | --- |
| `ROBOTEAM_PHYSICS_SMOKE=1`, `ROBOTEAM_PHYSICS_VIDEO=1`, `ROBOTEAM_PHYSICS_CASE=<case>` | `harness.claude.test_claude_physics_smoke`, with video, on another case than `transport-small-l1` |
| `ROBOTEAM_PHYSICS_BATCH=1` | `harness.claude.test_claude_parallel_physics_smoke` |
| `ROBOTEAM_PHYSICS_STANDING=1`, `ROBOTEAM_PHYSICS_SIGNAL=1`, `ROBOTEAM_PHYSICS_FINISH=1`, `ROBOTEAM_MOSAIC_IMAGE=1` | Claude standing-team, signal, finish and Mosaic image integration tests |
| `ROBOTEAM_NATIVE_TEST_RECEIPTS=1` | Keep the receipts of `harness.claude.test_claude_standing_team_integration` |

## Filesystems

Keep test databases, harness homes, temporary executables and fixture outputs on one local
filesystem. Never open an active SQLite database across a Docker or network-filesystem boundary.
In a Linux container, give the tests writable local temporary folders and a writable bytecode
location. A pass with the CPU renderer says nothing about NVIDIA EGL, a real Slurm allocation
or the resources 36 runs at once need.
