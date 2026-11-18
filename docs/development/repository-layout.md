# Repository layout

Each top-level folder has one job. When adding a file, put it where its job is described here.
If no folder fits, the file probably belongs in a run or output folder, not in Git.

```text
RoboTeam/
  benchmark/        the released tasks (4 task types x 9 cases), the pinned asset archive and the hall
  roboteam/         the Python package: sim, tasks, runtime, harness, launch, analysis
  prompts/          every text a model reads: rules, roles and guides
  scripts/          engineering commands: release, analysis, site, dev
  tests/            the tests, laid out like the package
  docs/             guides
  site/             the project page
  docker/           the container image
  .github/          CI workflows
```

Files at the root:

| File | What it is |
| --- | --- |
| `README.md` | The introduction to the benchmark |
| `roboteam.toml` | The defaults for new runs |
| `models.json` | The models, one section per harness |
| `pyproject.toml`, `uv.lock`, `.python-version` | The Python package and its locked environment |
| `.env.example` | The credentials template |
| `LICENSE`, `LICENSE-DATA.md` | The license of the code and the license of the data and media |
| `.prettierrc.json` | Formatting of the JavaScript files |
| `.gitignore`, `.gitattributes`, `.dockerignore` | Git and Docker settings |

## The package

Every folder also has an `__init__.py`.

```text
roboteam/
  cli.py                 the `roboteam` command
  configuration.py       loads and validates roboteam.toml, a site TOML and command options
  io.py                  the repository root, file hashes, atomic JSON writes
  sim/                   the simulation
    robot_control.py     the arm and hand controller
    kinematics.py        inverse kinematics
    franka_limits.py     the speed, acceleration and force limits of a real Franka Panda
    motion_check.py      sampled checks of planned moves against other arms
    profile.py           physics settings a scene file cannot hold
    health.py            fails a step on a numeric failure
    workstation.py       reads a frozen workstation's visible poses
    motion_recording.py  the recording of a run's motion
    live_video.py        MP4 recording while a run runs
    render/              worker.py image.py look.py backend.py cocoa.py
    hall/                build.py (the factory hall scene) desks.py (the cases placed in it) labels.py
                         flat.py (the built hall that runs load) world.py (a task at its desk in the hall)
  tasks/                 the released tasks and their scoring
    task_types.py        resolves a released case and its public facts
    config.py            one task definition for the scene and the public task
    public.py            the public task, and checks of a released task against its scene
    scene.py             scene checks, freezing a scene into a run, camera names
    ground_truth.py      the files of a ground_truth run
    provenance.py        content fingerprints of scenes and logic
    evaluate.py          the evaluator: process events and completion
    dial.py              the Dial feedback rules
    relay_goal_fraction.py   how much of a timber lies over GOAL
    contact_episodes.py  counts of robot contact episodes
  runtime/               what runs inside one run
    world/               pipeline.py service.py store.py sqlite_busy.py effective_physics.py seal.py
                         fault_injection.py dashboard.html
    tools/               the robot tool: robot_ops.py action_batch.py delegation.py scheduling.py
                         run_skills.py public_files.py stop_diagnostics.py tool_errors.py tools_mode.py
                         observation_mode.py ground_truth.py (the `state` operation)
                         pipeline_client.py
    run/                 setup.py bootstrap.py layout.py segments.py versions.py diagnostics.py cli.py
                         defaults.json (the runtime's default settings)
    time/                clock.py quota.py outage.py egress_pause.py
    sandbox/             access.py policy_env.py policy_env_probe.py
      policy-env/        core.in core.lock store.in all.lock mujoco.in mujoco.lock
  harness/
    codex/               launch.py job_harness.py recover_task.py tool_backend.py file_sandbox.py
                         tool_worker.py desktop_robot_mcp.py
      checks/            cli.py broker.py snapshot.py
      host/              the Node.js host: policy_host.js rpc.js gateway_rpc.js job_gateway.js
                         tool_broker.js meta_dispatcher.js initialize.js preflight.js borrowed_auth.js
                         model_template.json
    claude/              run.py supervisor.py recover_task.py robot_mcp.py
      session/           runner.py session_host.py session_host_base.py session_recovery.py recovery.py
                         native_home.py budget.py cost_state.py
      systems/           single_agent.py adaptive.py adaptive_dispatch.py standing_team.py dispatch.py
                         fork_setup.py adaptive_setup.py provenance.py request_identity.py
      checks/            preflight.py readiness.py blocked_precheck.py offline_probe.py
    shared/              what both harnesses import: landlock.py tool_worker.py owner.py recovery.py
                         identity.py native.py preflight_probe.py robot_mcp.py robot_tool.json
    adapters/
      claude_in_codex/   gateway.py monitor.py requirements.txt
      gpt_in_claude/     gateway.py auth.py websocket.py requirements.txt
  launch/                prepare.py tasks.py supervise.py launch_schedule.py codex_batch.py
                         claude_batch.py claude_prepare.py
    local/               mac.py linux.py
    slurm/               job.py auth.py proxy.py
    container/           container.py entrypoint.py
    results/             collect.py archive.py archive_batch.py session_archive.py report.py
                         host_metrics.py assets.py
  analysis/              analysis of finished runs: archive.py extract.py metrics.py atomic.py
                         motion.py motion_query.py paired.py session_archive.py
```

## Tracked folders

| Folder | Holds | Does not hold |
| --- | --- | --- |
| `benchmark/` | `README.md`; `release.json`; `assets.json`, which pins the asset archive; one folder per task type (`transport/`, `mosaic/`, `relay/`, `dial/`) with its `catalog.json` and nine case folders, each with `scene.xml`, `task.json`, `environment.json`, `workstation.json` and `public/` (the public task and the task materials a run receives); `hall/`, the sources of the factory hall (`layout.json`, `fonts/`, `textures/`, `source/`). See [benchmark/README.md](../../benchmark/README.md) | Draft scenes; run results |
| `roboteam/` | The package, as drawn above. Data files sit beside the code that reads them: the dashboard beside the world that serves it, `defaults.json` beside run setup, the policy environment's lock files beside `policy_env.py`, each adapter's `requirements.txt` beside its gateway | Run data; one-off tools |
| `prompts/` | `rules.md`; `roles/` with one prompt per role (`single-agent.md`, `adaptive-controller.md`, `team-controller.md` for `hierarchical`, `worker.md`, `meta-manager.md`); `guides/` with `collaboration/` (`guide.md`, `tools.md`, `communication.md`, `adaptive.md`, `motion-check.md`) and one guide per task type (`transport.md`, `mosaic.md`, `relay.md`, `dial.md`) | Anything a model does not read (the prompts for an outer manager are in `docs/development/`) |
| `scripts/` | Commands an engineer runs with `python -m scripts.FOLDER.NAME`, in `release/`, `analysis/`, `site/` and `dev/`, each listed in [scripts/README.md](../../scripts/README.md) | Library code (put it in `roboteam/`) |
| `tests/` | `test_*.py`, `test_*.js` and one `.cjs` file, laid out like the package: `sim/` (with `hall/`), `tasks/`, `runtime/{world,tools,run,time,sandbox}/`, `harness/{codex,claude,shared,adapters}/`, `launch/`, `analysis/`, and `repo/` for checks of the repository and the scripts. `helpers/` holds what tests share (`fake_pipeline.py`, `fake_session.py`, `motion.py`, `single_arm_scene.py`, `team_settings.py`, `relay_contract.py`, `claude_batch_control.py`, two provider stand-ins and three Node.js clients); the test runner puts it on the import path. See [testing](testing.md) | Large recorded evidence |
| `docs/` | `README.md` (the index), `getting-started.md` and `cli.md` at the top level; `tasks/`; `benchmark/` (rules, physics, robot-only runs); `harness/` (overview, Codex, Claude Code, the two adapters, shared login); `hosts/` (Mac, Linux, Slurm, Docker, the policy environment, and `examples/` with a starting site TOML per platform); `runs/` (time, continuation, recovery, evidence storage, viewer); `development/`; `media/readme/`, the README's images. Every prepared run freezes `development/manager-runbook.md`, `architecture.md` and `test-coverage.md` by name | Generated files |
| `site/` | The project page: `index.html`, `DESIGN.md`, `data/` (`tasks.json`, `media.json`, `oracle-videos.json`) and `assets/` (`atlas/`, `css/`, `img/`, `js/`) | The task videos and the results, which the page fetches from the media repository `RoboTeam-media` |
| `docker/` | `Dockerfile` for `roboteam container` | |
| `.github/` | `workflows/tests.yml` (the offline checks) and `workflows/site.yml` (the project page) | |

## Folders not in Git

| Folder | Holds |
| --- | --- |
| `runs/` (or `paths.runs_root`) | `policy/` (batches: frozen inputs, evidence, recorded motion), `engineering/` (receipts, checks, validation results), `exports/` (collections of stopped batches and their ZIPs), `state-assets/` and `asset-cache/` (caches addressed by content hash) |
| `vendor/panda/` | The Franka Panda model, restored by `roboteam bootstrap` |
| `benchmark/*/*/assets/` | Scene meshes and textures, restored by `roboteam bootstrap` |
| `benchmark/hall/built/` | The hall that runs load, built by `scripts/release/build_hall.py` and restored by `roboteam bootstrap` |
| `benchmark/hall/meshes/`, generated files in `benchmark/hall/textures/` | Intermediate files of a hall build |
| `outputs/` | Output of a hall scene build (`roboteam/sim/hall/build.py`) |
| `site/_media/`, `site/_directions/`, `site/_dev/` | Local encoded media and design drafts of the project page |
| `.venv/`, `.venv-gateway/` | The locked Python environment from `uv sync`; the optional environment of the two adapters |
| `.roboteam/` | Per-run Codex homes, preflight state and container records |
| `.env` | Credentials, from `.env.example` |

Cloning the repository backs up none of these. See [evidence storage](../runs/evidence-storage.md)
for collection, archiving and restore.

## Rules

- The released scenes and their public files are frozen. `scripts/release/build_release.py`
  wrote them; nothing at run time rebuilds or patches them. `benchmark/release.json` names
  every file by hash.
- Store shared material once. A text or file that several cases use by design, such as a task
  type's guide, has one copy that every record points at. Files generated from a case's own
  scene stay in that case, even when two cases generate the same bytes: a case folder must be
  complete on its own.
- Run data stays out of Git. Analysis code goes in `roboteam/analysis/` and takes the data
  folder and the output paths as arguments.
