# Codex benchmark manager prompt

Give the following prompt to a coding agent with terminal access to this checkout.
The outer agent can use any model or desktop application. The measured policy
model runs inside Codex CLI and is selected by the frozen profile and effort.
For provider-specific setup, read `docs/engines/providers.md`; historical prices
in `docs/archive/model-pricing-20261028.md` are dated observations, not current quotes.

```text
Manage a RoboFrontier Codex benchmark through the unified command line.
Read docs/unified-cli.md before executing commands.

Requested settings:
- config: repository defaults, unless an operator settings path is supplied
- engine: codex
- profile: luna
- effort: high
- topology: adaptive
- families: [transport, mosaic, relay, dial]
- level: 1
- min_arms: true
- parallel: 4
- mode: plan
- output: runs/policy/luna-l1-small-001
- next_level: none

Modes:
- plan: local inspection and an exact task plan; no provider requests.
- smoke: only an explicitly authorized paid --smoke-only provider check.
- run: a full authorized provider preflight, fresh preparation and execution.
Authorization must cover the selected provider/profile, tasks and stage. Reuse
existing authorization where applicable; a prompt example is not spend consent.

1. Check the checkout, branch, commit and benchmark/release.json.
   Identify the selected release. Manage only this new batch; other sessions'
   runs remain with their original operators.
2. Use robofrontier doctor with the requested engine/profile and render backend.
   It checks local prerequisites, not provider authentication or compatibility.
   If .env is absent, scripts.benchmark_handoff init-env can create an empty
   template. Preserve existing credentials; report only missing variable names.
3. Use robofrontier plan with the requested profile, effort, topology, selection
   and parallelism. Global --config precedes the subcommand. Report exact case
   IDs, arm counts, model, topology and task count. Stop here for mode=plan.
4. For mode=smoke, run robofrontier preflight --smoke-only --confirm-spend with
   matching settings only after spend authorization. Report its actual receipt
   and result. A smoke check does not replace full provider qualification.
5. For mode=run, run the full authorized preflight. Its receipt must match the
   current profile, catalog and native CLI. Preserve failed receipts; continue
   to preparation only when qualification passes. Use robofrontier prepare
   --output OUTPUT with the same resolved settings and a new output directory.
   Inspect batch.json and frozen effective-config.json before running. Existing
   directories are evidence; select a fresh name instead of overwriting them.
6. Execute robofrontier run OUTPUT in a persistent terminal and retain its live
   process handle. Parallelism and startup spacing come from frozen settings.
   The host initializes state and starts roles itself; no manual READY or START
   steps are required. Read this batch's atomic status and logs every 30-60
   seconds, reporting actual progress, terminal results and engineering errors.
   An observation timeout is not a process exit: poll the same live handle.
7. After all task hosts stop, inspect sealing and unresolved action states, then
   report per-case results, errors, collected data and verified ZIP paths.
   Collection/archive settings are frozen per batch. For next_level=none, end.
   If the request explicitly includes another level, prepare a new batch with
   that level, the same model/families and its matching smallest arm counts.

Protocol: the inner measured model makes task decisions, interprets images and
operates robots. The outer manager performs engineering setup and supervision.
Keep frozen inputs, original logs, private scoring isolation and native session
identity. Policy agents must not receive Oracle solutions, private Dial answers,
external action strategies or robot actions chosen by the outer manager. Report
the inner profile and effort; the outer session's model is not the tested model.

For provider/rate-limit/protocol faults, retain evidence and report the exact
failure. Use the existing host's safe recovery. Do not switch models, alter a
running task, start a replacement world, update a CLI automatically or create a
second copy of the same batch. Use robofrontier stop OUTPUT to request stopping
this batch, then inspect final status. Its policy time limit remains the frozen
START-based limit; an external short-test stop must not rewrite task instructions.
```

The unified entry prepares one profile per batch. Select a different engine-
compatible profile explicitly for another model. For multiple profiles, prepare
separate named batches and define their combined concurrency; `parallel=4` in
four independent supervisors would allow sixteen task hosts, not four total.
The legacy `scripts.benchmark` multi-profile entry remains available with its
own documented arguments and receipts. A runtime task slot is not a bound on
provider request concurrency, because task roles can call the provider at once.
