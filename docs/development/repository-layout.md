# Repository layout

Each top-level folder has one job. When adding a file, put it where its job is described here;
if no folder fits, the file probably belongs in a run or output folder rather than in Git.

```text
RoboTeam/
  benchmark/        the released tasks (4 task types x 9 cases), the pinned asset archive and the hall
  roboteam/         the Python package: sim, tasks, runtime, harness, launch, analysis
  prompts/          every text a model reads: rules, roles and guides
  scripts/          engineering commands: release, analysis, site, dev
  tests/            regression tests, laid out like the package
  docs/             guides
  site/             the project page
  docker/           the container image
  .github/          CI workflows
  runs/ outputs/ vendor/ .venv/ .roboteam/    not in Git (see below)
```

At the root: `README.md` introduces the benchmark; `roboteam.toml` holds the defaults for new runs
and `models.json` the models; `pyproject.toml`, `uv.lock` and `.python-version` pin the
Python environment; `.env.example` is the credentials template; `LICENSE` covers the code and
`LICENSE-DATA.md` the data; `.gitignore`, `.gitattributes` and `.dockerignore` configure Git and
Docker.

## The package

```text
roboteam/
  cli.py configuration.py io.py
  sim/                 robot control, kinematics, Franka limits, motion checks, the physics profile,
                       health, workstations, motion recordings, the live video
    render/            worker.py image.py look.py backend.py cocoa.py
    hall/              build.py (the factory hall scene) desks.py (the cases placed in it) labels.py
  tasks/               released task definitions, the public projection, scenes and scoring
  runtime/
    world/             pipeline.py service.py store.py sqlite_busy.py effective_physics.py seal.py
                       fault_injection.py dashboard.html
    tools/             the robot tool: robot_ops.py action_batch.py delegation.py scheduling.py
                       run_skills.py public_files.py stop_diagnostics.py tool_errors.py tools_mode.py
                       pipeline_client.py
    run/               setup.py bootstrap.py layout.py segments.py versions.py diagnostics.py cli.py
                       defaults.json (the policy runtime's default settings)
    time/              clock.py quota.py outage.py egress_pause.py
    sandbox/           access.py policy_env.py policy_env_probe.py policy-env/ (inputs and locks)
  harness/
    codex/             launch.py job_harness.py recover_task.py tool_backend.py file_sandbox.py
                       tool_worker.py desktop_robot_mcp.py
      checks/          cli.py broker.py snapshot.py
      host/            the Node hosts: policy_host.js rpc.js gateway_rpc.js job_gateway.js
                       tool_broker.js meta_dispatcher.js initialize.js preflight.js borrowed_auth.js
                       model_template.json
    claude/            run.py supervisor.py recover_task.py robot_mcp.py
      session/         runner.py session_host.py session_host_base.py session_recovery.py recovery.py
                       native_home.py budget.py cost_state.py
      systems/         single_agent.py adaptive.py adaptive_dispatch.py standing_team.py dispatch.py
                       fork_setup.py adaptive_setup.py provenance.py request_identity.py
      checks/          preflight.py readiness.py blocked_precheck.py offline_probe.py
    shared/            what both harnesses import: landlock.py tool_worker.py owner.py recovery.py
                       identity.py native.py preflight_probe.py robot_mcp.py robot_tool.json
    adapters/
      claude_in_codex/ gateway.py monitor.py requirements.txt
      gpt_in_claude/   gateway.py auth.py websocket.py requirements.txt
  launch/              prepare.py tasks.py supervise.py launch_schedule.py codex_batch.py
                       claude_batch.py claude_prepare.py
    local/             mac.py linux.py
    slurm/             job.py auth.py proxy.py
    container/         container.py entrypoint.py
    results/           collect.py archive.py archive_batch.py session_archive.py report.py
                       host_metrics.py assets.py
  analysis/            offline analysis of archived runs
```

## Tracked folders

| Folder | Holds | Does not hold |
| --- | --- | --- |
| `benchmark/` | `release.json`; per task type (`transport/`, `mosaic/`, `relay/`, `dial/`) its `catalog.json` and nine case folders, each with the scene, task, environment, workstation and `public/` (the public task and task materials a run receives); `assets.json`, the pinned asset archive; `hall/`, the factory hall (`layout.json`, `fonts/`, `textures/`, `source/`). See [benchmark/README.md](../../benchmark/README.md). | Draft scene revisions; run results |
| `roboteam/` | The package, as drawn above. Its data files travel with the code that reads them: the dashboard beside the world that serves it, `defaults.json` beside run setup, the policy environment's locks beside `policy_env.py`, each adapter's `requirements.txt` beside its gateway. | Run data; one-off tools |
| `prompts/` | `rules.md`; `roles/` with one prompt per role (`single-agent.md`, `team-controller.md` for `hierarchical`, `adaptive-controller.md`, `worker.md`, `meta-manager.md`); `guides/` with `collaboration/` (`guide.md` and `tools.md`, `communication.md`, `adaptive.md`, `motion-check.md`) and one guide per task type (`transport.md`, `mosaic.md`, `relay.md`, `dial.md`). | Anything a model does not read (the outer manager prompts are in `docs/development/`) |
| `scripts/` | Commands an engineer runs with `python -m scripts.FOLDER.NAME`, in `release/`, `analysis/`, `site/` and `dev/`, each listed once in [scripts/README.md](../../scripts/README.md). | Library code (put it in `roboteam/`) |
| `tests/` | `test_*.py` and `test_*.js` laid out like the package: `sim/`, `tasks/`, `runtime/{world,tools,run,time,sandbox}/`, `harness/{codex,claude,shared,adapters}/`, `launch/`, `analysis/`, and `repo/` for repository and script checks. `helpers/` holds what tests share (`fake_pipeline.py`, `fake_session.py`, `motion.py`, `single_arm_scene.py`, `team_settings.py`, `relay_contract.py`, `claude_batch_control.py`, two provider stubs and three Node clients); the test runner puts it on the import path. See [testing](testing.md). | Large recorded evidence |
| `docs/` | `getting-started.md` and `cli.md` at the top level; `tasks/`, `benchmark/` (rules, physics, robot-tool-only runs), `harness/` (Codex, Claude Code, the two adapters, shared login), `hosts/` (Mac, Linux, Slurm, Docker, the policy environment, and `examples/` with a starting site TOML per platform), `runs/` (continuation, evidence storage, viewer) and `development/`; `media/readme/` holds the README images. Every prepared run freezes `development/manager-runbook.md`, `architecture.md` and `test-coverage.md` by name. | Generated renders (`docs/generated/` is ignored) |
| `site/` | The project page: `index.html`, `DESIGN.md`, `data/` (task and media indexes, and the note on each Oracle video) and `assets/` (`atlas/`, `css/`, `img/`, `js/`). | The task videos, which are published from separate media repositories; the results, which the page fetches from the data repository |
| `docker/` | `Dockerfile` for `roboteam container`. | |
| `.github/` | `workflows/tests.yml` (the offline checks) and `workflows/site.yml` (the project page). | |

## Folders not in Git

| Folder | Holds |
| --- | --- |
| `runs/` (or `paths.runs_root`) | `policy/` (run evidence, frozen inputs, recorded motion), `engineering/` (checks, receipts, validation results), `exports/` (collections of stopped runs and their ZIPs), `state-assets/` and `asset-cache/` (content-addressed caches) |
| `outputs/` | Renders and delivery packages |
| `vendor/panda/` | The Franka Panda model, restored by `roboteam bootstrap` |
| `benchmark/*/*/assets/` | Scene meshes and textures, restored from the pinned asset archive |
| `benchmark/hall/meshes/`, `benchmark/hall/textures/` | Generated by each factory hall build (except the tracked exterior texture) |
| `docs/generated/` | Local renders |
| `site/_media/`, `site/_directions/`, `site/_dev/` | Local encoded media and design explorations for the project page |
| `.venv/` | The locked Python environment from `uv sync` |
| `.roboteam/` | Native harness homes and container receipts |
| `.env` | Credentials, from `.env.example` |

Cloning the repository backs up none of these. See [evidence storage](../runs/evidence-storage.md)
for collection, archiving and restore.

## Rules

- `scripts/release/build_release.py` writes the released scenes and their public files; nothing at run
  time rebuilds or patches them. `benchmark/release.json` names every file by hash.
- Store shared material once. A text or file that several cases use by design, such as task type
  guidance, has one copy that every record points at. Files generated from a case's own scene stay
  in that case, even when two cases generate the same bytes: a scene folder must be complete on
  its own. Git stores identical contents once either way.
- Run data stays out of Git. Analysis code goes in `roboteam/analysis/` and takes the data
  root and outputs as arguments.
