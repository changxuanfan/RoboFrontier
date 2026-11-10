# Policy Python environment

Policy scripts use one frozen Python environment instead of whatever the host has. On macOS
`robofrontier prepare` uses it by default: the environment built from the current locks under
`/Users/Shared/robofrontier` (or `ROBOFRONTIER_POLICY_ENV_BASE`) that passed its check.
Preparation refuses when that one is missing, unchecked or failed, rather than falling back to
the host's Python. `ROBOFRONTIER_POLICY_ENV=PATH` picks another environment, and
`ROBOFRONTIER_POLICY_ENV=off` keeps the host's Python for a run. `robofrontier plan` shows the
choice as `policy_environment`. Runs already prepared keep what they froze. Other hosts keep
the host's Python, and naming an environment there is refused, until they have been tested
through each engine's sandbox.

## Use it

Build once per host, into a folder outside the home folder and the repository. This step needs
the network and `uvx`; the result is read-only and runs need no network:

```sh
.venv/bin/python -m scripts.build_policy_env --base /Users/Shared/robofrontier
```

Check it before a batch. This drives each real CLI with a local stub model, so it contacts no
provider and uses no credential:

```sh
.venv/bin/python -m scripts.check_policy_env /Users/Shared/robofrontier/policy-env-<id>
```

Prepare as usual; the default applies. To name another environment, or to keep the host's
Python:

```sh
ROBOFRONTIER_POLICY_ENV=/Users/Shared/robofrontier/policy-env-<id> .venv/bin/robofrontier prepare ...
ROBOFRONTIER_POLICY_ENV=off .venv/bin/robofrontier prepare ...
```

## What a run gets

- `python` and `pip` for Python 3.12 with the packages of `configs/policy-env/core.in`. The
  packages of `store.in` install offline with `pip install NAME` and stay in the run.
- No robot simulators, planners, kinematics libraries or PyTorch. No network or web search.
- A shell environment holding only the frozen variables, with temporary files, `HOME` and caches
  under `workspace/.tmp`. The CLIs keep their own environment and credentials.
- `public/inputs/environment.md`, which the first message carries, and
  `public/inputs/policy-env.sh`, which Claude Code sources before each command.

## What a policy can reach

`private/inputs/policy-access.json` freezes the table and the environment's hash. Preparation
refuses an environment whose files changed.

| Access | Paths |
|---|---|
| Write | The run's `workspace/`, and `/tmp` |
| Read | The run's `public/`, the environment, and the operating system |
| Closed | The rest of the run, other runs, every checkout, `/Users`, `/Volumes`, `/var/tmp`, `/var/folders`, `/opt`, `/usr/local`, `/Library/Keychains` |

Codex renders the table as a permission profile. Claude Code renders it as file-tool rules plus
its Bash sandbox.

## Known limits

- **`/tmp` is open and shared.** Closing it breaks zsh here-documents and the Claude CLI's record of
  each command's working directory, which use fixed paths there. So a policy can read and write what
  other runs and other programs on the host keep in `/tmp`, including other Claude sessions' files
  in `/tmp/claude-<uid>`. Scripts' temporary files still default to `workspace/.tmp`.
- **The root stays readable.** A table without it aborts even `/bin/sh` on macOS, so this closes
  what holds people's data, other runs and other software rather than listing what stays open.
  `/usr/bin/python3` still runs, without third-party packages.
- **Harness and policy environments stay separate on purpose.** Both use Python 3.12, but the
  harness keeps its own installation, MuJoCo and Pillow; merging them would give scripts the
  simulator.

## Newer versions

Update `PYTHON` and `UV` in `scripts/build_policy_env.py`, relock as its docstring shows, and
rebuild. Linux hosts need glibc 2.28 or newer for the locked wheels.
