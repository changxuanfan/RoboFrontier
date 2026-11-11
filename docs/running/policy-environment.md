# Policy Python environment

Policy scripts run in one frozen Python environment, never the host's Python. Every run uses
one. `robofrontier prepare` freezes the build of the current locks and refuses when it is
missing or has not passed its check. There is no way to prepare a run on the host's Python
(`ROBOFRONTIER_POLICY_ENV=off` is refused).

Which build `prepare` uses:

| Setting | Build |
| --- | --- |
| `ROBOFRONTIER_POLICY_ENV=/abs/path/policy-env-<id>` | That build |
| `ROBOFRONTIER_POLICY_ENV_BASE=/abs/base` | `<base>/policy-env-<id>` for the current locks |
| Neither, on macOS | `/Users/Shared/robofrontier/policy-env-<id>` |
| Neither, on Linux | None: `prepare` refuses |

`robofrontier plan` shows the choice as `policy_environment`. A prepared run keeps what it froze.
On Slurm the job prepares its own batch on the compute node and reads only
`ROBOFRONTIER_POLICY_ENV`; see [Slurm](slurm.md#5-policy-environment).

## Build

Once per host, into a folder outside the home folder, the repository and `/tmp`. It needs the
network and `uvx`; the result is read-only and runs need no network:

```sh
.venv/bin/python -m scripts.build_policy_env --base /Users/Shared/robofrontier
```

It prints the build's `root`. The folder name carries a hash of the locks, the Python version
and the platform, so each host builds its own. Linux needs glibc 2.28 or newer.

## Check

Run the check where batches will run (on a compute node for Slurm), with `--scratch` on the
filesystem the batch will use:

```sh
.venv/bin/python -m scripts.check_policy_env /Users/Shared/robofrontier/policy-env-<id> --scratch <batch location>
```

It drives each real CLI with a local stub model in a throwaway run, with the access table and
variables a real run freezes; no provider is contacted and no credential is used. It prints
`ok`/`denied` per attempt and exits nonzero on any unexpected result. A pass writes a receipt
beside the build listing, per engine, the sandbox it ran (Codex's tool backend, Claude Code's
Bash isolation) and the CLI version on `PATH`. `--engine codex` or `--engine claude` checks one
engine and adds it to the receipt.

`prepare` refuses any engine, sandbox or CLI version the receipt does not list, so check again
after changing a CLI. The sandbox the check uses:

| Host | Codex | Claude Code |
| --- | --- | --- |
| macOS | `native` | Claude Code's sandbox (Seatbelt) |
| Linux | `landlock-v1` | bubblewrap where `bwrap` and `socat` are on `PATH` and namespaces work, else `landlock-v1` |

So on Linux set `runtime.codex_tool_backend = "landlock-v1"`; a Codex run with `native` is
refused there. Claude's `landlock-v1` needs Landlock ABI 4 and `libseccomp`.

The receipt is per build: on shared storage one pass admits every node that uses that build.
Nodes should match the one checked (kernel, Landlock ABI, user namespaces).

## What a run gets

- `python` and `pip` for Python 3.12 with the packages of `configs/policy-env/core.in`. The
  packages of `store.in` install offline with `pip install NAME` and stay in the run.
- No robot simulators, planners, kinematics libraries or PyTorch. No network or web search.
- A shell environment holding only the frozen variables, with temporary files, `HOME` and caches
  under `workspace/.tmp`. The CLIs keep their own environment and credentials.
- `public/inputs/environment.md`, which the first message carries, and
  `public/inputs/policy-env.sh`, which Claude Code sources before each command.

## What a policy can reach

`private/inputs/policy-access.json` freezes the table and the environment's hash; preparation
refuses an environment whose files changed.

| Access | Paths |
| --- | --- |
| Write | The run's `workspace/`, and `/tmp` |
| Read | The run's `public/`, the environment, and the rest of the root |
| Closed on macOS | The rest of the run, other runs, every checkout, `/Users`, `/Volumes`, `/var/tmp`, `/var/folders`, `/opt`, `/usr/local`, `/Library/Keychains` |
| Closed on Linux | The rest of the run, other runs, every checkout, `/home`, `/root`, `/mnt`, `/media`, `/raid`, `/var/tmp`, `/dev/shm`, `/opt`, `/usr/local`, `/workspace` |

The home folder, the engines' credential homes and every path in `ROBOFRONTIER_SHARED_DENY_ROOTS`
(a JSON list of absolute paths, for shared storage) are closed too. A run's own `public/` and
`workspace/` and the environment stay open beneath a closed folder. Codex renders the table as
a permission profile; Claude Code as file-tool rules plus its Bash isolation.

## Known limits

- **On Linux, runs and `TMPDIR` stay outside `/tmp`**, for example under `/var/tmp`. Landlock
  cannot open a folder and close something inside it, so a closed run, batch or `TMPDIR` under
  `/tmp` would leave nothing able to create files directly in `/tmp`. Preparation and the check
  refuse it; `TMPDIR=/tmp` itself is fine. macOS allows runs under `/tmp`.
- **`/tmp` is open and shared.** Closing it breaks zsh here-documents and the Claude CLI's
  record of each command's working directory. A policy can read and write what other runs and
  programs keep in `/tmp`, including other Claude sessions' files in `/tmp/claude-<uid>`.
  Scripts' temporary files default to `workspace/.tmp`.
- **`/dev/shm`.** Each Codex command on Linux gets its own empty `/dev/shm`, which needs
  unprivileged user namespaces. Without them (a RunPod pod), and always for Claude's Landlock
  Bash, `/dev/shm` stays closed, so `multiprocessing.Pool` and `ProcessPoolExecutor` fail;
  threads and plain subprocesses work. The check records this as a known limit.
- **`ProcessPoolExecutor` fails under Claude on macOS.** Its sandbox refuses a system limit the
  executor reads first; `multiprocessing.Pool` works.
- **Under Landlock, processes stay visible.** A policy shell can list other processes but cannot
  read their environments, trace or signal them.
- **Codex on Linux ignores `chmod`.** The call succeeds without effect; `pip` and `venv` work,
  and `./script.sh` needs `bash script.sh`. Codex on Linux also blocks `kill` and sockets.
- **No named Unix socket can be made under Landlock.** Python's process pools use socket pairs
  or abstract sockets and are not affected by this.
- **The system Python is closed on Linux.** `python3` and `pip` in `/usr/bin`, `/bin` and
  `/usr/sbin` cannot run; the folders stay listable and their other programs run. On macOS the
  root stays readable (a table without it aborts `/bin/sh`), so `/usr/bin/python3` runs, without
  third-party packages.
- **Harness and policy environments stay separate.** Both use Python 3.12, but the harness keeps
  its own installation, MuJoCo and Pillow; merging them would give scripts the simulator.

## Newer versions

Update `PYTHON` in `robofrontier/runtime/policy_env.py` and `UV` in
`scripts/build_policy_env.py`, relock as the build script's docstring shows, rebuild and check.
