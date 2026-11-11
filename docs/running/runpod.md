# Running on RunPod (plain Linux)

A RunPod pod, or any Linux host without Slurm, runs a batch as a background service:

```sh
.venv/bin/robofrontier --config site.toml prepare --output /workspace/robofrontier-runs/policy/my-batch
.venv/bin/robofrontier run /workspace/robofrontier-runs/policy/my-batch --durable
.venv/bin/robofrontier status /workspace/robofrontier-runs/policy/my-batch
.venv/bin/robofrontier stop /workspace/robofrontier-runs/policy/my-batch
```

With a systemd user manager `--durable` starts a transient user service; without one (RunPod
containers have none) it starts a `setsid` daemon in its own session
(`robofrontier/batch/linux.py`). The batch's `control/durable/` folder holds the service record
and its logs; a second submission of the same batch is refused. `status` reports whether the
service still runs. [`configs/examples/runpod.toml`](../../configs/examples/runpod.toml) is a
starting site TOML.

## The pod

- **Data.** Keep runs on the pod's persistent volume: `paths.runs_root` (or
  `ROBOFRONTIER_RUNS_ROOT`) names where receipts, exports and caches go, and `prepare --output`
  where a batch goes. The policy's access table denies `/workspace` as a whole; a run's own
  `public/` and `workspace/` folders and the policy environment are the only places it reaches.
- **Isolation.** Claude Code's own Bash sandbox does not run in a RunPod container, so Bash runs
  under Landlock ([Claude Code](../engines/claude-code.md)); Codex uses its `landlock-v1` tool
  backend. A pod forbids user namespaces, so no command gets a private `/dev/shm`: it stays
  closed, and Python's process pools fail there while threads and subprocesses work
  ([policy environment](policy-environment.md)).
- **Tools.** Put the Node.js and CLI folders on `PATH` (`/workspace/tools/node/bin` and
  `/workspace/tools/npm/bin` on the pod used here) in every shell that prepares, runs or checks.
- **Rendering.** Without a GPU use `render.device = "cpu"` (Mesa's llvmpipe); the world process
  limits it to two threads per run.
- **Policy environment.** Build it on the pod and run its check there, with
  `ROBOFRONTIER_POLICY_ENV_BASE` naming the base ([policy environment](policy-environment.md)).

A network outage and a used-up usage limit pause the run in place and resume it by
themselves ([continuation](continuation.md#time)). Verified on a live pod (48 CPUs, kernel 6.8,
Landlock ABI 4) on 2026-11-11: the policy environment check passes for Claude and Codex.
