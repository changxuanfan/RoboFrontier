# Policy Python environment

The agents of a run may write and run Python. Their code runs in one frozen Python
environment, the *policy environment*, never in the host's Python and never in the benchmark's
own environment. `roboteam prepare` freezes the build that matches the current lock files and
refuses when it is missing or has not passed its check. There is no way to prepare such a run
on the host's Python (`ROBOTEAM_POLICY_ENV=off` is refused). The one exception is a
[robot-only run](../benchmark/robot-tool-only.md): its agents have no shell, so it freezes no
environment.

With the environment, each run also freezes an *access table*: the list of folders the agents'
file tools and shell may read or write ([below](#what-a-policy-can-reach)). The harness's
*sandbox* enforces it.

Which build `prepare` uses:

| Setting | Build |
| --- | --- |
| `ROBOTEAM_POLICY_ENV=/abs/path/policy-env-<id>` | That build |
| `ROBOTEAM_POLICY_ENV_BASE=/abs/base` | `<base>/policy-env-<id>` for the current locks |
| Neither, on macOS | `/Users/Shared/roboteam/policy-env-<id>` |
| Neither, on Linux | None: `prepare` refuses |

`roboteam plan` shows the choice as `policy_environment`. A prepared run keeps what it froze.
On Slurm the job prepares its own batch on the compute node from the same two variables; see
[Slurm](slurm.md#5-policy-environment).

## Build

Once per host, into a folder outside the home folder, the repository and `/tmp`. It needs the
network and `uvx`; the result is read-only and runs need no network:

```sh
.venv/bin/python -m scripts.release.build_policy_env --base /Users/Shared/roboteam
```

It prints the build's `root`. The folder name carries a hash of the locks, the Python version
and the platform, so each host builds its own. Linux needs glibc 2.28 or newer.

### The mujoco variant

The ordinary environment holds no physics simulator. A run prepared with
`--observation ground_truth` ([ground-truth observation](../benchmark/rules.md#ground-truth-observation))
uses a second build instead: the same Python and packages plus `mujoco`, hash-locked in
`mujoco.lock` at the version of the repository's `uv.lock`. Build and check it the same way:

```sh
.venv/bin/python -m scripts.release.build_policy_env --base /Users/Shared/roboteam --variant mujoco
.venv/bin/python -m scripts.release.check_policy_env /Users/Shared/roboteam/policy-env-mujoco-<id>
```

Its folder is `policy-env-mujoco-<id>`, with its own hash and its own check receipt; the ordinary
build's name and hash do not depend on it. `prepare` picks the variant for ground_truth runs and
the ordinary build for every other run, and refuses either kind of run with the other build. The
check requires `import mujoco` and a short simulation to work in the variant and to fail in the
ordinary build. The variant's shells also search `/usr/sbin`, where macOS keeps the `sysctl`
that `import mujoco` runs.

## Check

Run the check where batches will run (on a compute node for Slurm), with `--scratch` on the
filesystem the batch will use:

```sh
.venv/bin/python -m scripts.release.check_policy_env /Users/Shared/roboteam/policy-env-<id> --scratch <batch location>
```

It drives each installed CLI with a local stub model in a throwaway run, with the access table
and variables a real run freezes. No provider is contacted and no credential is used. For each
harness it prints one line with the sandbox it ran, the number of attempts and any difference
from what is expected, and it exits nonzero on a difference. A pass writes a receipt beside the
build that lists, per harness, the sandbox (Codex's tool backend, Claude Code's Bash isolation)
and the CLI version on `PATH`. Without `--harness` it checks both harnesses, so both CLIs must
be installed; `--harness codex` or `--harness claude` checks one and adds it to the receipt.

`prepare` refuses any harness, sandbox or CLI version the receipt does not list, so check again
after changing a CLI. The sandbox the check uses:

| Host | Codex | Claude Code |
| --- | --- | --- |
| macOS | `native` | Claude Code's sandbox (Seatbelt) |
| Linux | `landlock-v1` | bubblewrap where `bwrap` and `socat` are on `PATH` and namespaces work, else `landlock-v1` |

The default `runtime.codex_tool_backend = "auto"` picks these; a Codex run with `native` set by
hand is refused on Linux. Claude Code's `landlock-v1` needs Landlock ABI 4 (Linux 6.7) and
`libseccomp`.

The receipt is per build: on shared storage one pass admits every node that uses that build.
Nodes should match the one checked (kernel, Landlock ABI, user namespaces).

## What a run gets

- `python` and `pip` for Python 3.12 with the packages of `roboteam/runtime/sandbox/policy-env/core.in`. The
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

The home folder, the harnesses' credential homes and every path in `ROBOTEAM_SHARED_DENY_ROOTS`
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
  unprivileged user namespaces. Without them (most cloud containers), and always for Claude's Landlock
  Bash, `/dev/shm` stays closed, so `multiprocessing.Pool` and `ProcessPoolExecutor` fail;
  threads and plain subprocesses work. The check records this as a known limit.
  When AppArmor restricts unprivileged user namespaces, the worker checks that
  restriction before entering an unmapped namespace and keeps `/dev/shm` closed.
  It does not change the host's AppArmor settings or grant access to shared locks.
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
- **Runtime and policy environments stay separate.** Both use Python 3.12, but the runtime keeps
  its own installation, MuJoCo and Pillow; merging them would give scripts the simulator.

## Newer versions

Update `PYTHON` in `roboteam/runtime/sandbox/policy_env.py` and `UV` in
`scripts/release/build_policy_env.py`, relock as the build script's docstring shows, rebuild and check.
