# Engineering scripts

Experiments run through the `robofrontier` command ([getting started](../docs/getting-started.md),
[command-line guide](../docs/unified-cli.md)). The scripts here are the engineering commands
around it. Run each from the repository root as `.venv/bin/python -m scripts.NAME`; `--help`
lists its options. The GitHub PAT gateway below calls a model provider only when
listing models or forwarding an authenticated client request; the other scripts do not.

## GitHub PAT model transport

| Script | Purpose |
| --- | --- |
| `github_pat_gateway.py` | Loopback PAT transport for model catalogs, Chat Completions and Responses; no agent runtime |

`python scripts/github_pat_gateway.py --token-file /private/github_token.txt`
starts a standard-library-only loopback connector usable without installing
RoboFrontier, Copilot CLI or GHC API. It forwards Chat Completions and Responses,
including streamed tool calls. `--list-models` queries the current account's model
catalog. See [setup, Codex and Antigravity examples](../docs/engines/github-pat.md).

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
| `check_oracle_preservation.py` | Verify the protected Oracle bytes with inode-aware hashing; never repairs data |

See [testing](../docs/development/testing.md).

## Evidence, analysis and viewers

These read finished runs; none starts a model or physics.

| Script | Purpose |
| --- | --- |
| `run_analysis.py` | Extract archived runs and compute timing, outcomes and atomic-step metrics: `extract`, `compute`, `dial-turns`, `atomic`, `session-archive`. The data root, run list and outputs are arguments; no run data lives in the repository |
| `communication_report.py` | Summarize recorded multi-role communication without inferring model intent |
| `summarize_oracle_batch.py` | Read-only summary of complete Oracle results, pilots and ongoing attempts |
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
| `robofrontier.batch.handoff` | `doctor`, `init-env` (create `.env` from `.env.example` with mode 0600), `assets`, `setup-assets` (install the asset archive offline), `restore` |
| `robofrontier.batch.tasks` | `list`, `check`, `prepare`, `prepare-batch`: audit released tasks and their inputs, or prepare runs directly |
| `robofrontier.batch.archive_policy_batch` | `create`, `verify`, `restore`: the lower-level evidence archive; `restore` rebuilds an extracted archive in its original layout |
| `robofrontier.engines.codex.check_codex_cli` | Exercise the installed Codex CLI's tools, images and forks against a local stub |
| `robofrontier.factory.commands` | `build`, `view`, `poses`, `video`: build, view and render the Oracle workstations in one Factory |

`robofrontier/factory/blender/export.py` and `render.py` run inside Blender to export and render
Cycles scenes. `robofrontier/engines/codex/meta_dispatcher.js` executes frozen Meta operations; it
is not a task-solving agent.

Do not modify frozen inputs or delete evidence to make a preparation or archive check pass.
