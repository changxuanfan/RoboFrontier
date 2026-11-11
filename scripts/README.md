# Engineering command index

Use the unified `robofrontier` command for new experiments. Start with the root
[README](../README.md), [configuration guide](../docs/unified-cli.md), and
[component map](../docs/engines/README.md#component-map). The unified CLI selects a native
Codex or Claude runner; it does not turn one engine into the other.

For a lower-level module, run `.venv/bin/python -m scripts.MODULE` (or the dotted
package module named in the table) from the repository root. Keep existing module names when reproducing historical evidence.

| Entry | Purpose and scope |
| --- | --- |
| `robofrontier config/plan/bootstrap/prepare` | Resolve public TOML settings, select current released tasks, restore pinned assets, and freeze new inputs without calling a model |
| `robofrontier doctor/preflight/run/status/stop` | Check local prerequisites; explicitly authorize provider checks; execute and monitor the selected native engine; request an orderly stop |
| `robofrontier collect/archive/extract` | Collect stopped native sessions and task evidence, create a verified deduplicated ZIP, and verify/extract it |
| `robofrontier container` | Build committed source and execute with persistent local Docker volumes |
| `robofrontier slurm-submit` | Freeze a submission and optionally queue node-local execution with verified stage-out |
| `robofrontier factory/oracle` | Replay frozen motion in Factory, or explicitly run privileged reference execution; neither is a policy benchmark launch |
| `benchmark models/plan/preflight/prepare/run/status/stop` | Native Codex interface retained for compatibility, with model selection, task filters, provider checks, concurrency, and START-based task limits |
| `robofrontier.batch.handoff doctor/init-env/assets/restore` | Inspect handoff prerequisites, create a private local environment file, and export/restore assets with SHA verification |
| `robofrontier.engines.codex.check_codex_cli` | Exercise the real Codex CLI's tools, images, and forks against a local Responses stub, without external model calls |
| `robofrontier.batch.tasks list/check/prepare/prepare-batch` | Audit current release selection and inputs, or use the retained lower-level preparation interface |
| `robofrontier.factory.commands build/video/poses` | Low-level scene construction, public pose export, and Cycles video; requires an explicitly matching source |
| `check_harness` | Run the offline Python, JavaScript, documentation, and protocol regression inventory; historical fixtures may require separate assets |
| `check_oracle_preservation` | Check the preservation manifest and frozen Oracle source bindings |
| `run_analysis extract/compute/dial-turns/atomic/session-archive` | Offline analysis of archived runs: timing, outcomes and atomic-step failure rates (version 2 step rules in `robofrontier/analysis/atomic.py`); data root, run list and outputs are arguments, and no run data lives in the repository |
| `robofrontier/factory/blender/export.py`, `render.py` (inside Blender) | Export and render Cycles scenes, reuse fixed-camera frames, and compare sampled source poses |
| `site_media encode/montage/stills/explainer` | Encode task videos to 720p with posters and a verified manifest, build the family montages, README stills and the README benchmark figure |
| `site_film short/film/web/banner` | Cut the film and its short teaser from the raw Robo World render with motion graphics in the page's style, and derive the page hero loop, README teaser and banner |
| `site_data tasks/media/readme-gallery` | Generate the project page's task and video indexes and fill the README task gallery |

## Every script

Run a Python module with `.venv/bin/python -m scripts.NAME` from the repository root. Each purpose below is the script's own docstring.

### Benchmark engines and runs

Native Codex and Claude hosts, preparation and provider checks. `robofrontier` calls these. The Codex batch runner and Node host (`codex_policy_host.js`, `codex_rpc.js`, `codex_preflight.js`, `codex_initialize.js`) are in `robofrontier/engines/codex/`.

| Script | Purpose |
| --- | --- |
| `build_policy_env.py` | Build the read-only Python environment and offline package store for policy scripts, once per host. |
| `check_policy_env.py` | Before a batch, check an environment and each engine's sandbox with stub models; no provider is contacted. |

### Evidence, reports and viewers

Read finished runs; none starts a model or physics.

| Script | Purpose |
| --- | --- |
| `communication_report.py` | Summarize recorded multi-role communication without inferring model intent. |
| `run_analysis.py` | Extract archived runs and compute timing, outcomes and atomic-step metrics; data root, run list and outputs are arguments. |
| `summarize_oracle_batch.py` | Read-only summary of complete Oracle results, pilots and ongoing attempts. |
| `verify_evidence_replay.py` | Compare restored evidence, all motion states/events and sampled renders. |
| `view_policy_batch.py` | Loopback, read-only batch viewer using existing JSON and images only. |

### Repository, assets and checks

| Script | Purpose |
| --- | --- |
| `site_media.py` | Encode project page videos, family montages and README stills. |
| `site_film.py` | Cut the RoboFrontier film and its short teaser from the raw Robo World render, with motion graphics drawn in the project page's style. |
| `site_data.py` | Generate `site/data/` indexes and the README task gallery. |
| `build_release.py` | Write the release's physics into every released scene and start each scene at rest; rewrites the release index. |
| `validate_physics.py` | Check the release physics and Franka limits on the released scenes: rest, carrying, placing, pushing, collisions, Relay handover, Dial turning and step time. |
| `check_harness.py` | Offline checks: fake services, robot/contact physics and real encoder recovery. |
| `run_tests.py` | Run every Python and Node test in parallel, rerunning a failed module alone; CI's all-tests job. |
| `check_oracle_preservation.py` | Verify protected historical bytes with inode-aware hashing. |

### Factory, replay and video

Offline presentation of recorded motion; never steps task physics.

| Script | Purpose |
| --- | --- |
| `replay_motion_in_factory.py` | Replay immutable source states and optional scene-independent cuts in a factory. |

### Task builders, previews and viewers

Build or inspect released scenes; names are kept for provenance.

| Script | Purpose |
| --- | --- |

### Oracle runs and engineering

Privileged reference execution and its diagnostics. A name with `oracle`, `commission` or `probe` is never a scored policy entry.

| Script | Purpose |
| --- | --- |

`meta_dispatcher.js` executes frozen Meta operations; it is not an autonomous
task-solving agent.

Family builders, audits, and Oracle scripts keep their historical names for
provenance, tests, and reproducibility. A name containing `oracle`, `commission`,
or `probe` does not make that script a scored policy entry or select the current
released task version.

Do not modify frozen inputs or delete source evidence merely to make a
preparation or archive check pass.
