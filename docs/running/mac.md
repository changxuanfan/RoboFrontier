# Running on a Mac

A Mac runs a batch as a user launchd job, so the batch outlives the terminal or agent session
that started it. [`configs/examples/mac.toml`](../../configs/examples/mac.toml) is a starting
site TOML: copy it to an untracked file (here `site.toml`) and edit it.

## 1. Prerequisites

- macOS on Apple silicon, with the lid kept open (see [Limits](#limits)).
- Python 3.12, [uv](https://docs.astral.sh/uv/) (its `uvx` builds the policy environment),
  Node.js and `ffmpeg`.
- The engine CLI at its pinned version, first on `PATH`: Claude Code 2.1.316 (`claude`) or
  Codex 0.165.0 (`codex`). `robofrontier/runtime/versions.py` holds the pins, with MuJoCo,
  NumPy and Pillow; `prepare` and `run` refuse any other version.

## 2. Install

```sh
git clone https://github.com/changxuanfan/RoboFrontier.git
cd RoboFrontier
uv sync --locked --extra oracle
.venv/bin/robofrontier bootstrap      # downloads and verifies the pinned task assets
```

## 3. Credentials

```sh
cp .env.example .env && chmod 600 .env
```

Fill in only the variable your profile reads (`configs/models.json`, `env_key`):

| Profile | Credential |
| --- | --- |
| Claude `haiku_subscription_token`, `opus_subscription` | `CLAUDE_CODE_OAUTH_TOKEN` in `.env` (from `claude setup-token`) |
| Claude `haiku`, `opus` | `ANTHROPIC_API_KEY` in `.env` |
| Codex `luna` | `OPENAI_API_KEY` in `.env` |
| Codex `luna_subscription`, `sol61_subscription` | No variable: log in once with `CODEX_HOME=~/.robofrontier/codex-home codex login` |

Keep credentials in `.env`, not exported in the shell. `prepare`, `run` and `continue` load
`.env` themselves; the launchd job file stores no credential, and the Claude token reaches the
CLI on a pipe.

## 4. Policy environment

Build once per Mac, then check it. The default base is `/Users/Shared/robofrontier`, so no
variable is needed:

```sh
.venv/bin/python -m scripts.build_policy_env --base /Users/Shared/robofrontier   # prints its root
.venv/bin/python -m scripts.check_policy_env /Users/Shared/robofrontier/policy-env-<id>
```

The check drives each real CLI against a local stub (no model calls) and records a receipt
beside the build. `prepare` refuses a build that has not passed it. Check again after changing
a CLI version. Details: [policy environment](policy-environment.md).

## 5. Local check and preflight

```sh
.venv/bin/robofrontier --config site.toml doctor          # CLI, sandbox, renderer; exits 2 on failure
.venv/bin/robofrontier --config site.toml plan            # tasks, model, policy_environment; no model calls
.venv/bin/robofrontier --config site.toml preflight --confirm-spend --max-budget-usd 1   # Claude
.venv/bin/robofrontier --config site.toml preflight --confirm-spend                      # Codex
```

`preflight` makes a few paid calls. For Claude it runs the basic and the blocked-parent
prechecks and writes receipts under `<runs root>/engineering/claude-precheck/` and
`claude-blocked-precheck/`; for Codex it writes
`<runs root>/engineering/model-compatibility/<profile>/report.json`. `run` refuses a batch
without receipts matching its profile and CLI version.

## 6. Prepare and run

```sh
.venv/bin/robofrontier --config site.toml prepare --output runs/policy/my-batch
.venv/bin/robofrontier run runs/policy/my-batch          # submits the launchd job and returns
.venv/bin/robofrontier status runs/policy/my-batch       # includes the job's state under "durable"
.venv/bin/robofrontier stop runs/policy/my-batch         # an orderly stop
.venv/bin/robofrontier continue runs/policy/my-batch     # continue stopped runs by hand
```

`run` and `continue` read the batch's frozen configuration, not `--config`. `run --foreground`
runs in the current process instead of launchd. `run` refuses a batch that is not freshly
prepared; `run --continue` picks up a batch whose supervisor died. Each run gets 24 h of
active time from START and is scored at the cutoff or when the team finishes. A run that stops
unexpectedly continues by itself once; see [continuation](continuation.md).

The launchd job:

- has `ProcessType=Interactive`, so macOS schedules it like a foreground application;
- runs under `caffeinate -ims`, which keeps the Mac awake for the job's life;
- writes `service.plist`, `metadata.json`, `stdout.log` and `stderr.log` into
  `<batch>/control/durable/` (a continuation into `control/durable/continue-<n>/`).

A network outage and a used-up usage limit pause the run in place and resume it by themselves
([continuation](continuation.md#time)).

## 7. Results

Each run's results, videos and evidence stay in its folder under the batch. When the batch ends,
`run` collects it into `<runs root>/exports/<batch>-<hash>/` and archives a verified ZIP beside
it. The runs root is `paths.runs_root` or `ROBOFRONTIER_RUNS_ROOT` (default `<repo>/runs`).
See [evidence storage](evidence-storage.md).

## Limits

- **Closing the lid sleeps the Mac** despite `caffeinate`. Keep it open, or use an external
  display with power. Sleep is not counted as active time, but nothing advances meanwhile.
- **Screen lock.** The world renders through a hidden window. While the screen is locked the
  window service may not answer, and a world that starts then waits; running worlds continue.
- **`ProcessPoolExecutor` fails under Claude Code's sandbox on macOS**; `multiprocessing.Pool`
  works ([policy environment](policy-environment.md#known-limits)).
- `render.device` resolves to `native` on macOS.
