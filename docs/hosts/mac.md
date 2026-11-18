# Running on a Mac

A Mac runs a batch as a user launchd job, so the batch outlives the terminal or agent session
that started it. [`docs/hosts/examples/mac.toml`](examples/mac.toml) is a starting
site TOML: copy it to an untracked file (here `site.toml`) and edit it.

## 1. Prerequisites

- macOS on Apple silicon, with the lid kept open (see [Limits](#limits)).
- Python 3.12, [uv](https://docs.astral.sh/uv/) (its `uvx` builds the policy environment),
  Node.js and `ffmpeg`.
- The engine CLI at its pinned version, first on `PATH`: Claude Code 2.1.316 (`claude`) or
  Codex 0.165.0 (`codex`). `roboteam/runtime/run/versions.py` holds the pins, with MuJoCo,
  NumPy and Pillow; `prepare` and `run` refuse any other version.

## 2. Install

```sh
git clone https://github.com/changxuanfan/RoboTeam.git
cd RoboTeam
uv sync --locked
.venv/bin/roboteam bootstrap      # downloads and verifies the pinned task assets
```

## 3. Credentials

```sh
cp .env.example .env && chmod 600 .env
```

Fill in only the variable your profile reads (`models.json`, `env_key`):

| Profile | Credential |
| --- | --- |
| Claude `opus` (default), `haiku` | `ANTHROPIC_API_KEY` in `.env` |
| Claude `opus_subscription`, `haiku_subscription_token` | `CLAUDE_CODE_OAUTH_TOKEN` in `.env` (from `claude setup-token`) |
| Codex `sol` (default), `luna` | `OPENAI_API_KEY` in `.env` |
| Codex `sol_subscription`, `luna_subscription` | No variable: log in once with `CODEX_HOME=~/.roboteam/codex-home codex login` |

Keep credentials in `.env`, not exported in the shell. `prepare`, `run` and `continue` load
`.env` themselves; the launchd job file stores no credential, and the Claude token reaches the
CLI on a pipe.

## 4. Policy environment

Build once per Mac, then check it. The default base is `/Users/Shared/roboteam`, so no
variable is needed:

```sh
.venv/bin/python -m scripts.release.build_policy_env --base /Users/Shared/roboteam   # prints its root
.venv/bin/python -m scripts.release.check_policy_env /Users/Shared/roboteam/policy-env-<id>
```

The check drives each real CLI against a local stub (no model calls) and records a receipt
beside the build. `prepare` refuses a build that has not passed it. Check again after changing
a CLI version. Details: [policy environment](policy-environment.md).

## 5. Local check and preflight

```sh
.venv/bin/roboteam --config site.toml doctor          # CLI, sandbox, renderer; exits 2 on failure
.venv/bin/roboteam --config site.toml plan            # tasks, model, policy_environment; no model calls
.venv/bin/roboteam --config site.toml preflight --confirm-spend --max-budget-usd 1   # Claude
.venv/bin/roboteam --config site.toml preflight --confirm-spend                      # Codex
```

`preflight` makes a few paid calls. For Claude it runs the basic and the blocked-parent
prechecks and writes receipts under `<runs root>/engineering/claude-precheck/` and
`claude-blocked-precheck/`; for Codex it writes
`<runs root>/engineering/model-compatibility/<profile>/report.json`. `run` refuses a batch
without receipts matching its profile and CLI version.

## 6. Prepare and run

A running batch checks its source for changes and aborts every run, for good, when one appears
(`INTEGRITY_ABORT`; [continuation](../runs/continuation.md)). Run batches from a checkout nothing edits
while they run, a detached worktree of `main` outside the repository for example, with the data
root pointing where the receipts and results belong:

```sh
git worktree add --detach ~/Repos/RoboTeam-run main
cd ~/Repos/RoboTeam-run && uv sync --locked && install -m 600 ../RoboTeam/.env .env
export ROBOTEAM_RUNS_ROOT=~/Repos/RoboTeam/runs
```

```sh
.venv/bin/roboteam --config site.toml prepare --output runs/policy/my-batch
.venv/bin/roboteam run runs/policy/my-batch          # submits the launchd job and returns
.venv/bin/roboteam status runs/policy/my-batch       # includes the job's state under "durable"
.venv/bin/roboteam stop runs/policy/my-batch         # an orderly stop
.venv/bin/roboteam continue runs/policy/my-batch     # continue stopped runs by hand
```

`run` and `continue` read the batch's frozen configuration, not `--config`. `run --foreground`
runs in the current process instead of launchd. `run` refuses a batch that is not freshly
prepared; `run --continue` picks up a batch whose supervisor died. Each run gets 24 h of
active time from START and is scored at the cutoff or when the team finishes. A run that stops
unexpectedly continues by itself once; see [continuation](../runs/continuation.md).

The launchd job:

- has `ProcessType=Interactive`, so macOS schedules it like a foreground application;
- runs under `caffeinate -ims`, which keeps the Mac awake for the job's life;
- writes `service.plist`, `metadata.json`, `stdout.log` and `stderr.log` into
  `<batch>/control/durable/` (a continuation into `control/durable/continue-<n>/`).

A network outage and a used-up usage limit pause the run in place and resume it by themselves
([continuation](../runs/continuation.md#time)).

## 7. Results

Each run's results, videos and evidence stay in its folder under the batch. When the batch ends,
`run` collects it into `<runs root>/exports/<batch>-<hash>/` and archives a verified ZIP beside
it. The runs root is `paths.runs_root` or `ROBOTEAM_RUNS_ROOT` (default `<repo>/runs`).
See [evidence storage](../runs/evidence-storage.md).

## Limits

- **Closing the lid sleeps the Mac** despite `caffeinate`. Keep it open, or use an external
  display with power. Sleep is not counted as active time, but nothing advances meanwhile.
- **Screen lock.** The world renders through a hidden window. While the screen is locked the
  window service may not answer, and a world that starts then waits; running worlds continue.
- **`ProcessPoolExecutor` fails under Claude Code's sandbox on macOS**; `multiprocessing.Pool`
  works ([policy environment](policy-environment.md#known-limits)).
- `render.device` resolves to `native` on macOS.
