# Engineering scripts

Experiments run through the `roboteam` command ([getting started](../docs/getting-started.md),
[command-line guide](../docs/unified-cli.md)). The scripts here are the engineering commands
around it. Run each from the repository root as `.venv/bin/python -m scripts.NAME`; `--help`
lists its options. The gateways below access model providers when listing models or
forwarding authenticated requests; the ChatGPT sign-in helper accesses the authorization
service only when explicitly invoked. The other scripts do not call a model provider.

## Experimental Codex / Claude transport

| Script | Purpose |
| --- | --- |
| `codex_claude_gateway.py` | Authenticated loopback Responses-to-Messages adapter for `claude-opus-5-5`; Codex owns tools, sessions, compaction and forks |
| `codex_claude_monitor.py` | Live cache-hit rate, token totals and estimated cost per run from the gateway's metadata log; read-only, standard library |

Install the optional [adapter dependency](../configs/requirements/codex-claude.txt) into a separate
environment and run the gateway as `python scripts/codex_claude_gateway.py`, not with
`-m scripts.NAME`. The monitor needs no extra package. See
[credentials, limits and the live-run commands](../docs/engines/codex-claude-api.md).

## Experimental Claude Code / GPT transport

| Script | Purpose |
| --- | --- |
| `chatgpt_plan_auth.py` | Explicit ChatGPT plan sign-in and protected OAuth credential management |
| `claude_chatgpt_gateway.py` | Authenticated loopback Messages-to-Responses adapter; Claude Code owns tools, sessions and forks |
| `chatgpt_plan_websocket.py` | Gateway support module for connection-local Responses history and shared API admission |

Install the optional [adapter dependencies](../configs/requirements/chatgpt-plan.txt).
Run the standalone entry points as `python scripts/chatgpt_plan_auth.py` and
`python scripts/claude_chatgpt_gateway.py`, rather than with `-m scripts.NAME`.
The WebSocket module is imported by the gateway, not a separate command.
See [authentication, API-key handoff and validation](../docs/engines/claude-chatgpt-plan.md).

## Policy environment

| Script | Purpose |
| --- | --- |
| `build_policy_env.py` | Build the read-only Python environment and offline wheel store for policy scripts, once per host (`--base FOLDER`) |
| `check_policy_env.py` | Check a built environment and each engine's sandbox with a local stub model before a batch uses them (`ENVIRONMENT --scratch FOLDER [--engine]`) |

See [policy environment](../docs/running/policy-environment.md).

## Release and physics

| Script | Purpose |
| --- | --- |
| `build_release.py` | Write the release into the released case folders: `physics`, `settle`, `letters`, `codes`, `public`; `check` confirms the scenes carry the release physics. Each step rewrites the hashes in `benchmark/release.json` |
| `validate_physics.py` | Check the release physics and the Franka limits on the released scenes: `rest`, `carry`, `place`, `push`, `collide`, `relay`, `dial`, `timing`; results in `runs/engineering/validate-physics/` |

See [physics](../docs/physics.md) and [benchmark](../benchmark/README.md).

## Tests and checks

| Script | Purpose |
| --- | --- |
| `run_tests.py` | Run every Python and Node test in parallel, rerunning a failed module alone; CI's `all-tests` job |
| `check_harness.py` | Offline checks: fake services, robot and contact physics, Node hosts, syntax and documentation links; `--protocol-only` blocks physics |

See [testing](../docs/development/testing.md).

## Evidence, analysis and viewers

These read finished runs; none starts a model or physics.

| Script | Purpose |
| --- | --- |
| `run_analysis.py` | Extract archived runs and compute timing, outcomes and atomic-step metrics: `extract`, `compute`, `dial-turns`, `atomic`, `session-archive`. The data root, run list and outputs are arguments; no run data lives in the repository |
| `paired_tests.py` | Compare conditions task by task from a JSON file of outcomes: exact McNemar tests with Holm's correction, and bootstrap intervals for tasks completed and for speed |
| `communication_report.py` | Summarize recorded multi-role communication without inferring model intent |
| `verify_evidence_replay.py` | Compare restored evidence with the original: all motion states and events, and sampled renders |
| `view_policy_batch.py` | Loopback, read-only batch viewer using existing JSON and images only ([viewer](../docs/running/local-viewer.md)) |

## Factory and project page

| Script | Purpose |
| --- | --- |
| `replay_motion_in_factory.py` | Replay recorded source states, with optional cuts, in a Factory; never steps task physics |
| `site_media.py` | Encode task videos for the project page and README with posters and a verified manifest: `encode`, `montage`, `stills`, `explainer` |
| `site_film.py` | Cut the film and its short teaser from the raw Robo World render, and derive the page hero loop and banner: `short`, `film`, `web`, `banner` |
| `site_data.py` | Generate the project page's `site/data/` indexes and the README task gallery: `tasks`, `media`, `readme-gallery` |

## Package commands

Some lower-level commands live in the package and run as `.venv/bin/python -m MODULE`:

| Module | Purpose |
| --- | --- |
| `roboteam.batch.handoff` | `doctor`, `init-env` (create `.env` from `.env.example` with mode 0600), `assets`, `setup-assets` (install the asset archive offline), `restore` |
| `roboteam.batch.tasks` | `list`, `check`, `prepare`, `prepare-batch`: audit released tasks and their inputs, or prepare runs directly |
| `roboteam.batch.archive_policy_batch` | `create`, `verify`, `restore`: the lower-level evidence archive; `restore` rebuilds an extracted archive in its original layout |
| `roboteam.engines.codex.check_codex_cli` | Exercise the installed Codex CLI's tools, images and forks against a local stub |
| `roboteam.factory.commands` | `build`, `view`, `poses`, `video`: build, view and render the Oracle workstations in one Factory |

`roboteam/factory/blender/export.py` and `render.py` run inside Blender to export and render
Cycles scenes. `roboteam/engines/codex/meta_dispatcher.js` executes frozen Meta operations; it
is not a task-solving agent.

Do not modify frozen inputs or delete evidence to make a preparation or archive check pass.
