# Contributing

Thank you for helping with RoboTeam. This page says how to set up, check and send a change.

## Set up

```sh
uv sync --locked
.venv/bin/roboteam bootstrap
```

The project runs from a checkout only: the package reads `roboteam.toml`, `models.json`,
`prompts/` and `benchmark/` from the repository root, so a wheel installed elsewhere does not
work. [Getting started](../docs/getting-started.md) has the full setup, and
[repository layout](../docs/development/repository-layout.md) says where everything is.

## Check a change

```sh
uvx ruff@0.17.5 format roboteam scripts tests
uvx ruff@0.17.5 check roboteam scripts tests
xvfb-run -a -s "-screen 0 1920x1080x24" .venv/bin/python -m scripts.dev.run_tests   # Linux
.venv/bin/python -m scripts.dev.run_tests                                           # macOS
```

All tests run offline and call no model. [Testing](../docs/development/testing.md) covers single
modules, the runtime checker and the opt-in tests. CI runs the same commands on every pull
request.

## What a change should keep

- **The benchmark stays fixed.** A change to `benchmark/`, `prompts/`, the robot tool or the
  physics changes what is measured. Say so in the pull request, and rebuild the release record
  with `scripts/release/build_release.py`.
- **The agents stay inside the sandbox.** A change under `roboteam/runtime/sandbox/` or to the
  access table needs the policy environment check
  ([policy environment](../docs/hosts/policy-environment.md)) to pass on Linux and macOS.
- **No credentials** in code, tests, TOML files, command arguments or commits. Tests use the
  fixed fake values already in the suite.
- **Layering.** `roboteam/sim` and `roboteam/tasks` do not import `roboteam/runtime`,
  `roboteam/harness` or `roboteam/launch`; `roboteam/runtime` does not import
  `roboteam/harness` or `roboteam/launch`. `tests/repo/test_layering.py` checks this.
- **Docs move with code.** A renamed path, option or file is renamed in `docs/` in the same
  change; the link check in `scripts.dev.check_runtime` fails otherwise.

## Send it

Open a pull request against `main` with what changed, why, and how you checked it. For a new
model, add its entry to `models.json` and say which preflight receipt passed. For a bug, a
failing test first is the most useful thing you can send.

By contributing you agree that your code is released under the [MIT License](../LICENSE) and your
data and media under [CC BY 4.0](../LICENSE-DATA.md).
