# Policy Python environment

Policy scripts can use one frozen Python environment instead of whatever the host has. A run
uses it only when the trusted launcher sets `ROBOFRONTIER_POLICY_ENV` during `prepare`; every
other run, and every run already prepared, keeps its earlier behavior. Preparation refuses an
environment until the check below has passed on it. It has passed on macOS and on Slurm (Ubuntu
22.04, kernel 5.15, Landlock ABI 1); RunPod and Docker have not been tried.

## Use it

Build once per host, into a folder outside the home folder and the repository. This step needs
the network and `uvx`; the result is read-only and runs need no network:

```sh
.venv/bin/python -m scripts.build_policy_env --base /Users/Shared/robofrontier
```

Check it where batches will run, on a compute node for Slurm. This drives each real CLI with a
local stub model, so it contacts no provider and uses no credential. A pass records a receipt
beside the environment that lists each engine with the sandbox it ran (Codex's tool backend,
Claude Code's Bash isolation) and the CLI version on `PATH`. Preparation refuses any other
combination, so check again after changing a CLI, or to use Codex's `native` tool backend on Linux.
A receipt from before these lists is refused until the check runs again:

```sh
.venv/bin/python -m scripts.check_policy_env /Users/Shared/robofrontier/policy-env-<id> --scratch <batch location>
```

The receipt is per build, not per node: on shared storage, one pass admits every node that uses
that build. Nodes should match the one checked (kernel, Landlock, user namespaces); a node without
unprivileged user namespaces fails each Codex command rather than running it less confined.

Prepare with the flag:

```sh
ROBOFRONTIER_POLICY_ENV=/Users/Shared/robofrontier/policy-env-<id> .venv/bin/robofrontier prepare ...
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

## Slurm

- Set `slurm.scratch_root` outside `/tmp`, such as `/var/tmp`, and name shared storage in
  `ROBOFRONTIER_SHARED_DENY_ROOTS`.
- Keep the Mac route's `slurm.egress_root` outside `/tmp` too, since policies can read and write
  there. Preparing a run with an environment refuses it otherwise.
- Put the pinned Codex CLI (see `docs/engines/codex.md`) first on `PATH`. A newer one can reject the
  run's configuration, and a shared account's copy can change without notice, so a shared Slurm
  engine refuses any other version.

## Known limits

- **Keep Slurm scratch outside `/tmp`, such as under `/var/tmp`.** Landlock cannot open a folder
  and close something inside it, so with runs under `/tmp`, Codex could not list it or create files
  directly in it. The check shows this when `--scratch` matches the batch's location.
- **`ProcessPoolExecutor` fails under Claude on macOS.** Its sandbox refuses a system limit that
  the executor reads first. `multiprocessing.Pool` works, and Linux has no such limit.
- **Codex on Linux ignores `chmod`.** Landlock cannot limit which of the account's files a mode
  change reaches, so the call succeeds without doing anything; `pip` and `venv` still work, and
  `./script.sh` needs `bash script.sh`. It also blocks `kill` and sockets.
- **Each Codex command on Linux has its own empty `/dev/shm`.** It holds Python's multiprocessing
  locks and goes away with the command, so other jobs' shared memory stays out of reach. This needs
  unprivileged user namespaces, and commands fail on a host without them.
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
