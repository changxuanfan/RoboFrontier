# The Oracle

The Oracle is a set of privileged reference programs, one per family. Unlike a policy, an
Oracle reads hidden state: the scene file, live object poses, the evaluator and, for Dial, the
code. Its runs show that a task can be done and supply the reference videos; they are not
model results and are never scored as one. The Oracle makes no model calls.

Each Oracle run uses its own copy of the case, `benchmark/oracle/<case>/`: the scene its
recordings were made on, with that scene's physics. The release physics in
`benchmark/<family>/<case>/scene.xml` does not apply to it ([physics](../physics.md)).

| Family | Native entry (`robofrontier/oracle/`) | Strategy |
| --- | --- | --- |
| Transport | `run_transport_full_oracle.py` | Full-order solver |
| Mosaic | `run_mosaic_oracle.py` | Parallel endpoint planning in scratch models, one live world |
| Relay | `run_relay_live_oracle.py` | Rolling pipeline of carries and handovers |
| Dial | `run_blind_dial_oracle.py` | Blind solver that reads only BEST, in a separate process from the evaluator |

## Published reference videos

The 72 Oracle videos on the project page and in the README (36 cases, front and side) are
Robo World renders of the recordings named in the `oracle` rows of `benchmark/release.json`.
Each row's `qualification` says how its recording was made:

| Cases | Recording |
| --- | --- |
| Transport, all nine | Reference program, scene revision R13 |
| Mosaic `a04`, all levels | Reference program, scene revision R13 |
| Mosaic `a06` and `a08`, all levels | Operator-assisted reference program, scene revision R13 |
| Relay, all nine | Earlier runs whose completion was confirmed by review, not by the current evaluator |
| Dial, all but `dial-best5-n08-d3` | Reference program, scene revision R11 |
| `dial-best5-n08-d3` | Operator-assisted reference program, scene revision R11 |

Every recording was made with physics other than the release physics. In the Robo World
bundle, the Mosaic `a06` and `a08` Level 3 desks replay their Level 2 recordings
(`recorded_case_id`); the two levels differ only in the printed grid. Idle time is removed and
playback runs at the family speed (Transport and Relay 20×, Mosaic 30×, Dial 10×).

## Install

```sh
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap
```

## Run a reference

Every command takes `--config FILE` before `oracle`, makes no model calls and never restarts a
world.

```sh
.venv/bin/robofrontier oracle plan --families mosaic --level 1 --min-arms
.venv/bin/robofrontier oracle prepare --cases mosaic-a04-6x12-d1 \
  --output runs/oracle/mosaic-a04-d1 --render native
.venv/bin/robofrontier oracle run runs/oracle/mosaic-a04-d1
```

From another terminal:

```sh
.venv/bin/robofrontier oracle status runs/oracle/mosaic-a04-d1
.venv/bin/robofrontier oracle stop runs/oracle/mosaic-a04-d1
```

| Command | What it does |
| --- | --- |
| `plan` | Lists the cases the selection (`--cases`, `--families`, `--level`, `--min-arms`, or `[selection]`) matches; reads only |
| `prepare` | Needs exactly one case, a new `--output` directory and a clean committed checkout. Restores pinned assets, checks every file of the Oracle copy against its hashes, and freezes the executor source, harness, catalog, effective configuration and `private/execution-protocol.json`. Steps no physics |
| `run` | Launches the frozen native entry once, supervises it and writes the verdict; later TOML or checkout edits do not affect it |
| `status` | Reads `oracle-status.json` and the owner lock; never a live database |
| `stop` | Writes `STOP`; the supervisor sends SIGTERM to the native owner. A stop before launch prevents launch |

`prepare` options (defaults from `[oracle]` and `[render]` in `robofrontier.toml`):

| Option | Default | Meaning |
| --- | --- | --- |
| `--render {nvidia,cpu,native}` | `render.device` | Observation renderer; `native` on macOS |
| `--wall-limit-s` | 86,400 | Engineering time from owner launch, including planning and review pauses; not a policy clock |
| `--evaluation-mode` | `task-reference` | `task-reference` scores the terminal outcome (`terminal_outcome_v2`) and keeps process events as evidence; `strict-process` also requires a clean process history |
| `--mosaic-planning-workers` | 1 | Scratch planning processes; 0 uses every CPU |
| `--mosaic-max-goals` | 0 | 0 attempts the whole task; a positive value is a partial commissioning check, never a pass |
| `--codebook FILE` | none | Dial only: `{"code_symbols": [...]}`, one nonzero digit per dial |

`oracle.mosaic_physics_workers` (0, off) and `oracle.stop_grace_s` (120 s) are set in the TOML.
After a stop or the deadline, the owner gets `stop_grace_s` to clean up and report; then its
process group is killed and the run is kept as incomplete evidence.

**Dial code.** Without `--codebook`, `prepare` draws a fresh random code. To run against the
code a policy run of that case gets, write that case's entry from `private.dial_codes` in
`benchmark/release.json` as `{"code_symbols": [...]}` and pass it with `--codebook`. The file
is stored mode 0600 under `private/`; the solver gets only its path.

## Results

The execution directory keeps `oracle.json`, `effective-config.json`, `oracle-status.json`,
`oracle.log`, the frozen inputs in `private/` and the native trial in `trial/` (actions, motion,
evaluator log, `report.json`, recovery files). `oracle-status.json` ends in one phase:

| Phase | Meaning |
| --- | --- |
| `passed` | Full task completed, clean exit, no stop, no unresolved actions, no leftover processes |
| `commissioning_complete` | A `--mosaic-max-goals` check passed |
| `incomplete` | Finished without passing; read `trial/report.json` and `oracle.log` |
| `interrupted` | Stopped by `STOP`, a signal or the deadline |

From `robofrontier.oracle-report.v2` reports, status also copies `task_goal_met` (evaluator
outcome), `task_completed` (with valid physics and resolved execution), `process_clean`,
`execution_resolved`, `physics_valid` and `strategy_completed`. If a supervisor is killed its
native child can outlive it: check the recorded PID before collecting. Once every process has
stopped, `trial/motion` can be imported into Robo World with
[`robofrontier factory import-motion`](../factory/replay.md#import-a-closed-benchmark-recording).

## Review and assistance

At supported execution boundaries the Mosaic owner publishes privileged state in
`trial/review/observation.json`; a supervising person or coding session can submit a bounded
recovery under `trial/review/requests/`, answered in `trial/review/results/` (refused ones in
`trial/review/rejected/`). Every such intervention is recorded as
assistance in the report; it never resets the scene, removes events or replays an uncertain
action. [Recovery boundaries](recovery.md) lists what a recovery may and may not do.
