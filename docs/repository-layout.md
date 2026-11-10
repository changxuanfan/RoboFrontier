# Repository layout

Each top-level folder has one job. When adding a file, put it where its job is
described here; if no folder fits, the file probably belongs in a run or output
folder rather than in Git.

```text
RoboFrontier/
  benchmark/        the released tasks: 4 families x 9 cases
  robofrontier/     the Python package: runtime, task logic, engines
  prompts/          every text a model reads
  configs/          run settings, and scenes that are not (yet) released
  scripts/          engineering commands
  tests/            regression tests and their fixtures
  docs/             guides and dated history
  assets/           shared art: Factory meshes and the runtime HTML dashboard
  docker/           the container image
  runs/ outputs/ vendor/ .robofrontier/    not in Git (see below)
```

## Tracked folders

| Folder | Holds | Does not hold |
| --- | --- | --- |
| `benchmark/` | `release.json`, per family its catalog and nine case folders, and `oracle/` (the scenes the Oracle ran on). A case folder has the scene, task and workstation, and `public/`: the public task and family materials a run receives. See [benchmark/README.md](../benchmark/README.md). | Draft or historical scene revisions; run results |
| `robofrontier/` | The package, one subpackage per job: `runtime/` (the shared world, service, store, run setup, layout and segments), `physics/` (robot control, Franka limits, kinematics, motion checks, the sleep and settle rules, rendering), `tasks/` (released task definitions, public projection and scoring), `engines/` (`claude/`, `codex/` and `common/`), `batch/` (preparing, supervising, collecting and archiving batches on Mac, Slurm and containers), `oracle/` (privileged reference execution), `media/` (motion recordings, edits and simple-background videos), `analysis/` (offline analysis of archived runs) and `factory/` (the 3D Factory, with `factory/blender/` run inside Blender). At the top level: `cli.py`, `configuration.py` and `io.py`. | Run data; one-off tools |
| `prompts/` | `rules.md` and `roles/`: one prompt per role, named after its mode (`single-controller.md`, `team-controller.md` for `controller-worker`, `adaptive-controller.md`, `worker.md`, `meta-manager.md`); `skills/` (one per family, plus robot collaboration), `managers/codex.md` and `managers/claude.md` (the outer manager for each engine). Earlier texts that old records name are in the tag `archive/pre-cleanup-20261110`. | Anything a model does not read |
| `configs/` | Engine model profiles (`models.json`, one section per engine), harnesses (`harness.json`, `harnesses/`), the policy environment locks (`policy-env/`), the pinned asset locks (`policy-assets.json`, `factory-assets.json`), Factory looks (`backgrounds/`) and one example site TOML per platform (`examples/`). See [configs/README.md](../configs/README.md). | Released tasks (`benchmark/`); credentials |
| `scripts/` | Commands an engineer runs with `python -m scripts.NAME`. Each is listed in [scripts/README.md](../scripts/README.md). Generators of released or tracked data stay so that data can be rebuilt. | Library code (put it in `robofrontier/`) |
| `tests/` | `test_*.py` grouped like the package (`runtime/`, `physics/`, `tasks/`, `engines/`, `batch/`, `oracle/`, `media/`, `analysis/`, `factory/`, and `repo/` for repository and script checks), Node host tests under `engines/`, shared helpers at the top level and `fixtures/`. Run everything with `.venv/bin/python -m scripts.run_tests`, one module with `PYTHONPATH=tests:scripts .venv/bin/python -m unittest runtime.test_pipeline`. | Large recorded evidence |
| `docs/` | Guides by topic: `engines/`, `tasks/`, `running/`, `oracle/`, `factory/`, `development/`; `history.md` indexes the earlier records, which are in the tag `archive/pre-cleanup-20261110`. The top level keeps the overview guides; `meta-runbook.md`, `architecture.md` and `harness-verification.md` stay there because every prepared run freezes them by name. | Generated renders (`docs/generated/` is ignored) |
| `assets/` | `robo_factory/` (Factory meshes, textures, fonts, tour project) and `pipeline_dashboard.html`, the dashboard the runtime serves. | Task scenes |
| `docker/` | `Dockerfile` for `robofrontier container`. | |

At the root: `robofrontier.toml` holds the defaults for new runs; `pyproject.toml`
and `uv.lock` pin the Python environment.

## Folders not in Git

| Folder | Holds |
| --- | --- |
| `runs/policy/`, `runs/oracle/` | Original run evidence, frozen inputs and recorded motion. The released Oracle motion is protected by `outputs/final/preservation.json`. |
| `runs/engineering/` | Engineering checks, failure evidence and acceptance receipts |
| `runs/exports/` | Collections of stopped runs and portable evidence ZIPs |
| `runs/state-assets/`, `runs/asset-cache/` | Content-addressed caches used by preparation and bootstrap |
| `outputs/` | Renders, video projects and delivery packages. `outputs/final/` is the curated delivery; `outputs/oracle-renders/` holds the Factory renders and the promo. |
| `vendor/panda/` | The Franka Panda model, fetched by `robofrontier bootstrap` |
| `benchmark/*/*/assets/`, `benchmark/oracle/**/assets/` | Scene meshes and textures, restored from the pinned asset archive (the Oracle copies link to the released cases' files) |
| `.robofrontier/` | Native engine homes and container receipts |

Cloning the repository does not back up any of these. See
[evidence storage](running/evidence-storage.md) for collection, archiving and restore.

## Rules

- The release is frozen. `scripts/build_release.py` wrote its scenes and public files once;
  nothing rebuilds them, and earlier scene revisions are only in the archive tag.
- Frozen runs, recordings and review packages keep the paths they were made with.
  Read them through `robofrontier.tasks.families.current_path`;
  [benchmark/legacy-paths.json](../benchmark/legacy-paths.json) lists every move,
  of released inputs and of policy texts alike.
- Store shared material once. A text or file that several cases use by design, such
  as family guidance, has one copy that every record points at. Files generated from
  a case's own scene stay in that case, even when two cases generate the same bytes:
  a scene folder is frozen whole, so it must be complete. Git stores identical
  contents once either way.
- Historical material keeps its date. Current behavior is described in the guides
  outside `docs/archive/`.
