# Engineering scripts

Experiments run through the `roboteam` command ([getting started](../docs/getting-started.md),
[command-line guide](../docs/cli.md)). The scripts here are the engineering commands
around it, in four folders: `release/`, `analysis/`, `site/` and `dev/`. Run each from the
repository root as `.venv/bin/python -m scripts.FOLDER.NAME` (for example
`-m scripts.release.build_release`); `--help` lists its options. None of them calls a model
provider.

## Release: `scripts/release/`

### Policy environment

| Script | Purpose |
| --- | --- |
| `build_policy_env.py` | Build the read-only Python environment and offline wheel store for policy scripts, once per host (`--base FOLDER`) |
| `check_policy_env.py` | Check a built environment and each engine's sandbox with a local stub model before a batch uses them (`ENVIRONMENT --scratch FOLDER [--engine]`) |

See [policy environment](../docs/hosts/policy-environment.md).

### Release and physics

| Script | Purpose |
| --- | --- |
| `build_release.py` | Write the release into the released case folders: `physics`, `settle`, `letters`, `codes`, `public`; `check` confirms the scenes carry the release physics. Each step rewrites the hashes in `benchmark/release.json` |
| `validate_physics.py` | Check the release physics and the Franka limits on the released scenes: `rest`, `carry`, `place`, `push`, `collide`, `relay`, `dial`, `timing`; results in `runs/engineering/validate-physics/` |

See [physics](../docs/benchmark/physics.md) and [benchmark](../benchmark/README.md).

## Development: `scripts/dev/`

| Script | Purpose |
| --- | --- |
| `run_tests.py` | Run every Python and Node test in parallel, rerunning a failed module alone; CI's `all-tests` job |
| `check_harness.py` | Offline checks: fake services, robot and contact physics, Node hosts, syntax and documentation links; `--protocol-only` blocks physics |
| `verify_evidence_replay.py` | Compare restored evidence with the original: all motion states and events, and sampled renders |
| `view_batch.py` | Loopback, read-only batch viewer using existing JSON and images only ([viewer](../docs/runs/viewer.md)) |

See [testing](../docs/development/testing.md).

## Analysis: `scripts/analysis/`

These read finished runs; none starts a model or physics.

| Script | Purpose |
| --- | --- |
| `run_analysis.py` | Extract archived runs and compute timing, outcomes and atomic-step metrics: `extract`, `compute`, `dial-turns`, `atomic`, `session-archive`. The data root, run list and outputs are arguments; no run data lives in the repository |
| `paired_tests.py` | Compare conditions task by task from a JSON file of outcomes: exact McNemar tests with Holm's correction, and bootstrap intervals for tasks completed and for speed |
| `communication_report.py` | Summarize recorded multi-role communication without inferring model intent |

## Project page: `scripts/site/`

| Script | Purpose |
| --- | --- |
| `site_media.py` | Encode task videos for the project page and README with posters and a verified manifest: `encode`, `montage`, `stills`, `explainer` |
| `site_data.py` | Generate the project page's `site/data/` indexes and the README task gallery: `tasks`, `media`, `readme-gallery` |

## Package commands

Some lower-level commands live in the package and run as `.venv/bin/python -m MODULE`:

| Module | Purpose |
| --- | --- |
| `roboteam.launch.results.assets` | `doctor`, `init-env` (create `.env` from `.env.example` with mode 0600), `assets`, `setup-assets` (install the asset archive offline), `restore` |
| `roboteam.launch.tasks` | `list`, `check`, `prepare`, `prepare-batch`: audit released tasks and their inputs, or prepare runs directly |
| `roboteam.launch.results.archive_batch` | `create`, `verify`, `restore`: the lower-level evidence archive; `restore` rebuilds an extracted archive in its original layout |
| `roboteam.harness.codex.checks.cli` | Exercise the installed Codex CLI's tools, images and forks against a local stub |
| `roboteam.harness.adapters.claude_in_codex.gateway`, `.monitor` | The optional loopback gateway that lets Codex drive `claude-opus-5-5`, and its read-only cache monitor ([Claude in Codex](../docs/harness/claude-in-codex.md)) |
| `roboteam.harness.adapters.gpt_in_claude.gateway`, `.auth` | The optional loopback gateway that lets Claude Code drive `gpt-6.1-sol`, and its ChatGPT sign-in ([GPT in Claude Code](../docs/harness/gpt-in-claude-code.md)) |

The two gateways also run as files, from an environment that has only their own
`requirements.txt` installed: `python roboteam/harness/adapters/claude_in_codex/gateway.py`.
They access model providers when listing models or forwarding authenticated requests; the
ChatGPT sign-in accesses the authorization service only when explicitly invoked.

`roboteam/harness/codex/host/meta_dispatcher.js` executes frozen Meta operations; it
is not a task-solving agent.

Do not modify frozen inputs or delete evidence to make a preparation or archive check pass.
