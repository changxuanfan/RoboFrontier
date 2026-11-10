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
  web/              atlas page templates
  docker/           the container image
  runs/ outputs/ vendor/ .robofrontier/    not in Git (see below)
```

## Tracked folders

| Folder | Holds | Does not hold |
| --- | --- | --- |
| `benchmark/` | `release.json`, and per family its catalog, records and nine case folders. A case folder has the scene, task and workstation, and `public/` for reviewed material that belongs to that case only. See [benchmark/README.md](../benchmark/README.md). | Draft or historical scene revisions; run results |
| `robofrontier/` | The package. Engines are `codex/` and `claude/`; `suite/` builds and scores the four families; `factory/` replays recorded motion in the 3D Factory; `demo/` is the small teleoperation demo. Modules at the top level are the shared runtime (world, robot control, run setup and storage, evidence) and the scene adapters of earlier tasks that tests still exercise. | Data files; one-off analysis |
| `prompts/` | `rules.md` and `roles/`: one prompt per role, named after its mode (`single-controller.md`, `team-controller.md` for `controller-worker`, `adaptive-controller.md`, `worker.md`, `meta-manager.md`); `skills/` (one per family, plus robot collaboration), `managers/codex.md` and `managers/claude.md` (the outer manager for each engine), `archive/` (earlier texts that released records still name, including the family guidance `benchmark/release.json` delivers). | Anything a model does not read |
| `configs/` | Engine model profiles (`models.json`, `claude-models.json`, `codex-model-template.json`), harnesses (`harness.json`, `harness-frontier-v2*.json`, `harnesses/`), the pinned asset locks (`policy-assets.json`, `factory-assets.json`), Factory looks (`backgrounds/`), data retention (`retention.json`), the CPU slurm example (`examples/`), the Tulip pattern parameters of the Frontier V2 builder (`patterns/`), and two kinds of scenes: `environments/` (scene revisions before release, and the earlier revisions that released cases and Oracle recordings name as sources) and `suites/` (generated catalogs of earlier collections). | Released tasks; credentials |
| `scripts/` | Commands an engineer runs with `python -m scripts.NAME`. Each is listed in [scripts/README.md](../scripts/README.md). Generators of released or tracked data stay so that data can be rebuilt. | Library code (put it in `robofrontier/`) |
| `tests/` | `test_*.py`, Node host tests (`*.js`, `*.cjs`) and `fixtures/`. | Large recorded evidence |
| `docs/` | Guides by topic: `engines/`, `tasks/`, `running/`, `oracle/`, `factory/`, `development/`, `archive/` (dated history). The top level keeps the overview guides; `meta-runbook.md`, `architecture.md` and `harness-v2-verification.md` stay there because every prepared run freezes them by name. | Generated renders (`docs/generated/` is ignored) |
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
| `benchmark/*/*/assets/`, `configs/environments/**/assets/` | Scene meshes and textures, restored from the pinned asset archive |
| `.robofrontier/` | Native engine homes and container receipts |

Cloning the repository does not back up any of these. See
[evidence storage](running/evidence-storage.md) for collection, archiving and restore.

## Rules

- Released files are never edited in place. Build a new revision under
  `configs/environments/`, review it, then promote it into `benchmark/` with new
  hashes in `release.json`.
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
