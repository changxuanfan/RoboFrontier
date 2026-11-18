# Engineering scripts

Experiments run through the `roboteam` command ([getting started](../docs/getting-started.md),
[command-line guide](../docs/cli.md)). The scripts here are the engineering commands around
it, in four folders: `release/`, `dev/`, `analysis/` and `site/`. Run each from the repository
root as a module; `--help` lists its options. None of them calls a model provider.

```sh
.venv/bin/python -m scripts.release.build_policy_env --help
```

## Release: `scripts/release/`

### Policy environment

| Script | Purpose |
| --- | --- |
| `build_policy_env.py` | Build the read-only Python environment that the agents' own code runs in, with its offline package store. Once per host: `--base FOLDER`. `--variant mujoco` builds the environment of ground-truth runs |
| `check_policy_env.py` | Check a built environment and each harness's sandbox with a local stub model before a batch uses them: `ENVIRONMENT [--scratch FOLDER] [--harness codex\|claude]` |

See [policy environment](../docs/hosts/policy-environment.md).

### Release and physics

| Script | Purpose |
| --- | --- |
| `build_release.py` | The steps that wrote the released case folders: `physics`, `letters`, `codes`, `public`, `cameras`, `settle`, and `freeze`. The release is frozen, so every step that writes now refuses. `check` confirms that the scenes carry the release physics |
| `build_hall.py` | Build the factory hall that runs load (`benchmark/hall/built/`, not in Git) from the released scenes, and pin its hash in `benchmark/assets.json` |
| `validate_physics.py` | Check the release physics and the Franka limits on the released scenes. Scenarios: `rest`, `carry`, `place`, `push`, `collide`, `relay`, `dial`, `timing`. Results go to `runs/engineering/validate-physics/` |

See [physics](../docs/benchmark/physics.md) and [the released files](../benchmark/README.md).

## Development: `scripts/dev/`

| Script | Purpose |
| --- | --- |
| `run_tests.py` | Run every Python test and every `test_*.js` in parallel, and run a failed module once more alone. CI's `all-tests` job |
| `check_runtime.py` | Offline checks of the runtime: the tests, the Node.js host scenarios, syntax of Python and JavaScript files, and the links in Markdown. `--protocol-only` runs a fixed list of tests with physics blocked |
| `verify_evidence_replay.py` | Compare restored evidence with the original: every file hash, all motion states and events, and sampled images |
| `view_batch.py` | A read-only viewer of a batch in the browser, on loopback, from saved JSON and images only ([viewer](../docs/runs/viewer.md)) |

See [testing](../docs/development/testing.md).

## Analysis: `scripts/analysis/`

These read finished runs. None starts a model or a world, and no run data lives in the
repository: the data folder, the list of runs and the output paths are arguments.

| Script | Purpose |
| --- | --- |
| `run_analysis.py` | Extract archived runs and compute timing, outcomes and atomic-step metrics: `extract`, `compute`, `dial-turns`, `atomic`, `session-archive` |
| `paired_tests.py` | Compare conditions task by task from a JSON file of outcomes: exact McNemar tests with Holm's correction, and bootstrap intervals |
| `communication_report.py` | Summarize the messages the roles of a batch sent each other |

## Project page: `scripts/site/`

| Script | Purpose |
| --- | --- |
| `site_media.py` | Make the videos and images of the project page and the README: `encode`, `montage`, `stills`, `starts`, `explainer` |
| `site_data.py` | Generate the project page's `site/data/` files and the README's task gallery: `tasks`, `media`, `readme-gallery` |

## Commands inside the package

Some lower-level commands live in the package and run the same way, for example
`.venv/bin/python -m roboteam.launch.tasks list`.

| Module | Purpose |
| --- | --- |
| `roboteam.launch.results.assets` | `doctor` (a report on tools, models and assets), `init-env` (create `.env` from `.env.example` with mode 0600), `assets` and `setup-assets` (pack the asset archive; install one without network access), `restore` |
| `roboteam.launch.tasks` | `list`, `check`, `prepare`, `prepare-batch`: list the released tasks, check their inputs, or prepare runs directly |
| `roboteam.launch.results.collect` | The collector behind `roboteam collect` |
| `roboteam.launch.results.archive_batch` | `create`, `verify`, `restore`: the evidence archive as a folder; `restore` rebuilds the original files from an extracted archive |
| `roboteam.launch.results.session_archive` | `keep`, `archive`: copy and compress a run's session transcripts ([evidence storage](../docs/runs/evidence-storage.md#session-transcripts)) |
| `roboteam.launch.results.report` | Write a finished run's `report.json` ([reports](../docs/harness/README.md#reports-and-metric-definitions)) |
| `roboteam.runtime.run.cli` | Low-level operations on one run, such as `seal` and `export` ([manager runbook](../docs/development/manager-runbook.md)) |
| `roboteam.runtime.world.fault_injection` | Freeze one failing action into a prepared engineering run ([testing](../docs/development/testing.md#fault-injection)) |
| `roboteam.harness.claude.recover_task`, `roboteam.harness.codex.recover_task` | Recover one run whose host closed while its world stayed paused ([task recovery](../docs/runs/recovery.md)) |
| `roboteam.harness.codex.checks.cli`, `.broker`, `.snapshot` | Check the installed Codex CLI's tools, images, forks and tool backend against a local stub ([Codex](../docs/harness/codex.md)) |
| `roboteam.harness.claude.checks.preflight`, `.blocked_precheck`, `.readiness`, `.offline_probe` | The two Claude Code preflight checks on their own, a comparison of their receipts, and a check against local stubs ([Claude Code](../docs/harness/claude-code.md#preflight-and-receipts)) |
| `roboteam.harness.codex.desktop_robot_mcp` | The robot tool for threads of the Codex Desktop app ([Codex](../docs/harness/codex.md#codex-desktop-threads-optional)) |
| `roboteam.launch.slurm.proxy` | The Mac side of a Slurm job's network route ([Slurm](../docs/hosts/slurm.md#10-the-mac-route-mac-ssh)) |
| `roboteam.harness.adapters.claude_in_codex.gateway`, `.monitor` | The optional local gateway that lets Codex run `claude-opus-5-5`, and its cache monitor ([Claude in Codex](../docs/harness/claude-in-codex.md)) |
| `roboteam.harness.adapters.gpt_in_claude.gateway`, `.auth` | The optional local gateway that lets Claude Code run `gpt-6.1-sol`, and its sign-in ([GPT in Claude Code](../docs/harness/gpt-in-claude-code.md)) |

The two gateways also run as files, from an environment that has only their own
`requirements.txt` installed, for example
`python roboteam/harness/adapters/claude_in_codex/gateway.py`. They contact a model provider
only when they forward a request; the sign-in contacts OpenAI only when you run it.

Do not modify frozen inputs or delete evidence to make a preparation or an archive check pass.
