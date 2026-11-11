# Repository layout

Each top-level folder has one job. When adding a file, put it where its job is described here;
if no folder fits, the file probably belongs in a run or output folder rather than in Git.

```text
RoboFrontier/
  benchmark/        the released tasks: 4 families x 9 cases, and the Oracle's scenes
  robofrontier/     the Python package: runtime, physics, tasks, engines, batches
  prompts/          every text a model reads
  configs/          model profiles, harnesses, locks and example site TOMLs
  scripts/          engineering commands
  tests/            regression tests and their fixtures
  docs/             guides
  assets/           shared art: the Factory sources and the runtime dashboard
  site/             the project page
  docker/           the container image
  .github/          CI workflows
  runs/ outputs/ vendor/ .venv/ .robofrontier/    not in Git (see below)
```

At the root: `README.md` introduces the benchmark; `robofrontier.toml` holds the defaults for new runs; `pyproject.toml`, `uv.lock` and
`.python-version` pin the Python environment; `.env.example` is the credentials template;
`LICENSE` covers the code and `LICENSE-DATA.md` the data; `.gitignore`, `.gitattributes` and
`.dockerignore` configure Git and Docker.

## Tracked folders

| Folder | Holds | Does not hold |
| --- | --- | --- |
| `benchmark/` | `release.json`, `legacy-paths.json`, `pruned-paths.json`; per family (`transport/`, `mosaic/`, `relay/`, `dial/`) its `catalog.json` and nine case folders, each with the scene, task, environment, workstation and `public/` (the public task and family materials a run receives); `dial/best5-r11.json`; and `oracle/`: one folder per case with the scene its Oracle recordings were made on, plus `oracle/sources/` (the Transport, Mosaic and Relay source scenes, their assets included, and the Transport catalog). See [benchmark/README.md](../benchmark/README.md). | Draft scene revisions; run results |
| `robofrontier/` | One subpackage per job: `runtime/` (the shared world, service, store, run setup and layout, segments, policy environment, pinned versions), `physics/` (robot control, Franka limits, kinematics, motion checks, sleep and settle rules, rendering), `tasks/` (released task definitions, public projection and scoring), `engines/` (`claude/`, `codex/` with the Node hosts, `common/`), `batch/` (preparing, supervising, collecting and archiving batches on Mac, Linux, Slurm and containers), `oracle/` (privileged reference execution), `media/` (motion recordings, edits and videos), `analysis/` (offline analysis of archived runs) and `factory/` (the 3D Factory, with `factory/blender/` run inside Blender). At the top level: `cli.py`, `configuration.py` and `io.py`. | Run data; one-off tools |
| `prompts/` | `rules.md`; `roles/` with one prompt per role (`single-controller.md`, `team-controller.md` for `controller-worker`, `adaptive-controller.md`, `worker.md`, `meta-manager.md`); `skills/` (one per family, plus `robot-collaboration/` with its `references/`); `managers/codex.md` and `managers/claude.md`, the outer manager for each engine. | Anything a model does not read |
| `configs/` | `models.json` (model profiles, one section per engine), `harness.json` and `harnesses/` (`policy.json`, `oracle.json`), `policy-env/` (the policy environment's inputs and locks), `policy-assets.json` and `factory-assets.json` (pinned asset locks), `backgrounds/` (Factory looks) and `examples/` (`mac.toml`, `slurm.toml`, `runpod.toml`). See [configs/README.md](../configs/README.md). | Released tasks (`benchmark/`); credentials |
| `scripts/` | Commands an engineer runs with `python -m scripts.NAME`, each listed once in [scripts/README.md](../scripts/README.md). | Library code (put it in `robofrontier/`) |
| `tests/` | `test_*.py` grouped like the package (`runtime/`, `physics/`, `tasks/`, `engines/`, `batch/`, `oracle/`, `media/`, `analysis/`, `factory/`, and `repo/` for repository and script checks), the Node host tests under `engines/`, shared helpers at the top level (`fake_pipeline.py`, `motion.py`, `single_arm_scene.py`, `older_configuration.py` and three Node clients) and `fixtures/` (recorded Transport and Relay states). See [testing](development/testing.md). | Large recorded evidence |
| `docs/` | Overview guides at the top level, and guides by topic in `engines/`, `tasks/`, `running/`, `oracle/`, `factory/` and `development/`; `media/readme/` holds the README images. `meta-runbook.md`, `architecture.md` and `harness-verification.md` stay at the top level because every prepared run freezes them by name. `history.md` and `cleanup-20261110.md` are the only history. | Generated renders (`docs/generated/` is ignored) |
| `assets/` | `pipeline_dashboard.html`, the dashboard the runtime serves, and `robo_factory/`: the asset manifest, the tour and film projects with their titles and subtitles, the camera plan, fonts, Poly Haven source textures, the authored exterior texture, `viewer.html` and the Blender `requirements.txt`. | Task scenes; generated Factory meshes and textures |
| `site/` | The project page: `index.html`, `DESIGN.md`, `data/` (task, media and results indexes) and `assets/` (`atlas/`, `css/`, `img/`, `js/`, and `video/` with the hero loop). | The task videos, which are published from separate media repositories |
| `docker/` | `Dockerfile` for `robofrontier container`. | |
| `.github/` | `workflows/harness.yml` (the offline checks) and `workflows/site.yml` (the project page). | |

## Folders not in Git

| Folder | Holds |
| --- | --- |
| `runs/` (or `paths.runs_root`) | `policy/` and `oracle/` (run evidence, frozen inputs, recorded motion), `engineering/` (checks, receipts, validation results), `exports/` (collections of stopped runs and their ZIPs), `state-assets/` and `asset-cache/` (content-addressed caches), `factory-data/` (the Factory recording release) |
| `outputs/` | Renders, video projects and delivery packages; `outputs/final/preservation.json` protects the released Oracle motion |
| `vendor/panda/` | The Franka Panda model, restored by `robofrontier bootstrap` |
| `benchmark/*/*/assets/` | Scene meshes and textures, restored from the pinned asset archive; the Oracle case folders link to the released cases' files |
| `configs/evaluations/private/` | Private Dial evaluator inputs that Oracle records name |
| `assets/robo_factory/meshes/`, `assets/robo_factory/textures/` | Generated by each Factory build (except the tracked exterior texture) |
| `docs/generated/` | Local renders |
| `site/_media/`, `site/_directions/`, `site/_dev/` | Local encoded media and design explorations for the project page |
| `.venv/` | The locked Python environment from `uv sync` |
| `.robofrontier/` | Native engine homes and container receipts |
| `.env` | Credentials, from `.env.example` |

Cloning the repository backs up none of these. See [evidence storage](running/evidence-storage.md)
for collection, archiving and restore.

## Rules

- `scripts/build_release.py` writes the released scenes and their public files; nothing at run
  time rebuilds or patches them. `benchmark/release.json` names every file by hash.
- Frozen runs, recordings and review packages keep the paths they were made with. Read them
  through `robofrontier.tasks.families.current_path`;
  [benchmark/legacy-paths.json](../benchmark/legacy-paths.json) maps each earlier path of a
  released input or policy text to its current one.
- Store shared material once. A text or file that several cases use by design, such as family
  guidance, has one copy that every record points at. Files generated from a case's own scene stay
  in that case, even when two cases generate the same bytes: a scene folder must be complete on
  its own. Git stores identical contents once either way.
- Run data stays out of Git. Analysis code goes in `robofrontier/analysis/` and takes the data
  root and outputs as arguments.
