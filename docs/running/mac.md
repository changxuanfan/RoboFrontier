# Running on a Mac

A Mac runs a batch under the user's launchd service, so it outlives the terminal or agent
session that started it. This is the default for `run`, a continuation included:

```sh
.venv/bin/robofrontier prepare --config site.toml --output runs/policy/my-batch
.venv/bin/robofrontier run runs/policy/my-batch          # under launchd
.venv/bin/robofrontier status runs/policy/my-batch
.venv/bin/robofrontier stop runs/policy/my-batch         # an orderly stop
.venv/bin/robofrontier continue runs/policy/my-batch     # continue stopped runs by hand
```

`--foreground` runs in the current process instead. [`configs/examples/mac.toml`](../../configs/examples/mac.toml)
is a starting site TOML.

## What the service does

- **Priority.** The service has `ProcessType=Interactive`, so macOS schedules it like an
  application in front, not as background work.
- **Sleep.** It runs under `caffeinate`, which keeps the Mac awake while the batch runs.
  **Closing the lid still puts it to sleep**; keep it open, or use an external display with
  power. A sleep is not counted as active time and no run fails because of it, but nothing
  advances while the Mac sleeps.
- **Credentials.** The service file stores none; `run` loads `.env` itself.
- **Screen lock.** The world opens a hidden window for rendering. While the screen is locked
  the window service may not answer, and a world that starts then waits; runs already going
  are not affected.

## Before the first run

- The frozen policy Python environment is built and checked under `/Users/Shared/robofrontier`
  ([policy environment](policy-environment.md)); `prepare` refuses without it.
- Claude runs need passed precheck receipts for their profile, Codex runs a compatibility
  receipt (`robofrontier preflight --confirm-spend`).
- The installed engine CLI, MuJoCo, NumPy and Pillow have the pinned versions
  (`robofrontier/runtime/versions.py`).

A network outage and a used-up usage limit pause the run in place and resume it by
themselves ([continuation](continuation.md#time)).
