# Run folders

Everything a run reads and writes is in files. This page says where they are and what each one
is, for the runs root, a batch and one run. The paths of a run and a batch are defined once, in
`roboteam/runtime/run/layout.py`; every other guide links here for the layout.

## The runs root

The runs root is `<repo>/runs` unless `paths.runs_root` or `ROBOTEAM_RUNS_ROOT` names another
folder. Nothing under it is in Git.

```text
runs/
  batches/         the batches you prepare with --output (a convention; any new folder works)
  receipts/        preflight receipts, which `run` checks before it starts a batch
    claude/basic/<id>/receipt.json             the basic check of a Claude Code model
    claude/blocked-parent/<id>/receipt.json    its fork-while-waiting check
    codex/compatibility/<model>/report.json    the full check of a Codex model
    codex/smoke/<model>/report.json            the short check; it never qualifies a run
  checks/          reports of local checks: physics validation, the runtime checker, test reports
  exports/         <batch>-<hash>/ and <batch>-<hash>.zip: the collected evidence of a stopped batch
  asset-cache/     the downloaded asset archive, named by its SHA-256
  scene-cache/     scene files shared between runs, named by their SHA-256
```

## A batch

A batch is a set of runs of one harness, one model and one agent system, prepared and
supervised together.

```text
<batch>/
  batch.json               what was prepared: the cases, the versions, the layout name
  effective-config.json    the resolved settings, the system among them (`policy.system`)
  models/<model>/          the frozen model entry
  control/                 the supervisor's files: supervisor.lock, supervisor-status.json and
                           supervisor-claim.json (Claude Code), STOP once a stop was asked for,
                           durable/ (the background service: service.json, stdout.log, stderr.log)
  <model>/<case>/          one run
```

`<model>` is the entry name of `models.json` (for example `haiku_subscription`), not the
provider's model name: two entries of the same model with different logins are different
folders. The agent system is not in the path, because a batch has exactly one; read it from
`effective-config.json`, or from `roboteam status <batch>`.

## One run

```text
<batch>/<model>/<case>/
  public/                    what the agents may read
    inputs/                  the frozen task: task.json, rules.md, roles.json, roles/, guide/,
                             task/ (the task type's guide and files), environment.md, policy-env.sh
    observations/            every image a role asked for: obs-<id>-<number>-<camera>.jpg. The
                             number rises with each capture; sort by it, or by file time
    results/                 <Delegate>.json: what each adaptive delegate returned (the run's
                             score is in private/outputs/, not here)
  workspace/                 the agents' only writable folder and their working directory
    skills.md                the lessons file all roles of the run share; it starts empty
    .tmp/                    the temporary and cache folders of the agents' shell
  private/                   closed to the agents
    inputs/                  frozen at `prepare`: task.json and scene/ (with the answers),
                             frozen-source/ (the code and prompts the run uses), run.json,
                             effective-config.json, models.json, policy-access.json (the access
                             table), bootstrap/ (the first and the resume messages of each
                             role), meta/, release.json, manifest.json (the hash of each of these)
    state/                   live: runtime.sqlite (the run's database), control/ (locks, STOP),
                             connections/, budget.sqlite (the cost ledger of a Claude Code run)
    logs/                    owner.log (the world), host.jsonl (one line per tool call and turn),
                             admin-client.log, and the harness's own logs
    harness/                 the harness's files: per-turn events (turns/) or transcripts, the MCP
                             and sandbox configuration
    outputs/                 the results, below
```

### `private/outputs/`

| File | What it holds |
| --- | --- |
| `evaluation.json` | The score. `task_success` says whether the task was completed; `matched_goals` of `total_goals`, the violations (arm collisions among them), `termination_reason` (`wall_limit` at the time limit, absent after an accepted `finish`), the simulation speed, and `final_observation`: the images the world took at the cutoff |
| `seal.json` | How the run closed: `sealed`, the world's `lifecycle`, `unresolved_action_ids` (empty for a clean end), `video` (`"recording": "off"` unless `render.record_realtime_video` is set), and the final images. `final_observation` is the seal's own capture, taken only when the world was still running when it was sealed; after a time-limit cutoff the world has already taken its images and exited, so that field is empty, `cutoff_observation` names the images instead, and `capture_error` and `shutdown_error` only say that no world answered |
| `budget-cutoff.json`, `evaluation-window.json` | The evaluation at the time limit and the stretch of the process record it was made from |
| `events.jsonl` | The run's event log, exported from the database: every call, action, message and state change in order |
| `runtime.json` | A summary of the database at the end: lifecycle, active time, the roles, messages and jobs |
| `motion/` | The recorded motion, 30 samples per simulated second, in chunks |
| `suite-process.jsonl` | The evaluator's process record: a snapshot every 10 s and every event between |
| `scene.xml`, `effective-physics.json`, `hall.json`, `render-backend.json` | The scene the world loaded, its physics settings, the hall's hashes and the renderer that drew the images |
| `cpu-performance.jsonl` | How much wall time stepping and rendering took, every 5 s |
| `segments/<k>/` | The same files for segment `k` of a [continued run](continuation.md) |

A report with per-role usage, messages and overlap is not written by the run. Make it from a
stopped run with:

```sh
.venv/bin/python -m roboteam.launch.results.report <batch>/<model>/<case>
```

It adds `report.json`, `report.md` and `messages.json` to `private/outputs/`
([reports](../harness/README.md#reports-and-metric-definitions)).

A whole run folder is private: it holds the session transcripts and the answers of the task.
[Evidence storage](evidence-storage.md) says what is collected into an export and how to keep it.
