# Documentation

Start with [getting started](getting-started.md): it goes from a fresh clone to a finished run.
The [command-line guide](cli.md) lists every command and setting.

| Topic | Guides |
| --- | --- |
| First steps | [Getting started](getting-started.md), [command line and settings](cli.md) |
| Tasks | [The four task types](tasks/README.md): [Transport](tasks/transport.md), [Relay](tasks/relay.md), [Mosaic](tasks/mosaic.md), [Dial](tasks/dial.md). The 36 released tasks are in [`benchmark/`](../benchmark/README.md), and the [project page](https://changxuanfan.github.io/RoboTeam/) shows each one |
| Rules of a run | [Rules](benchmark/rules.md), [physics and robot limits](benchmark/physics.md), [robot-only runs](benchmark/robot-tool-only.md) |
| Harnesses | [Overview and models](harness/README.md), [Codex](harness/codex.md), [Claude Code](harness/claude-code.md) |
| Optional adapters | [Claude in Codex](harness/claude-in-codex.md), [GPT in Claude Code](harness/gpt-in-claude-code.md), [sharing a Codex login on Slurm](harness/shared-login.md) |
| Hosts | [Mac](hosts/mac.md), [Linux](hosts/linux.md), [Slurm](hosts/slurm.md), [Docker](hosts/docker.md), [policy Python environment](hosts/policy-environment.md), [example site TOMLs](hosts/examples) |
| Runs | [Run folders](runs/run-folder.md) (every file of a run), [time and pauses](runs/time.md), [continuing a stopped run](runs/continuation.md), [task recovery](runs/recovery.md), [evidence storage](runs/evidence-storage.md), [saved-run viewer](runs/viewer.md) |
| Development | [Changelog](changelog.md), [architecture](development/architecture.md), [repository layout](development/repository-layout.md), [testing](development/testing.md), [what the runtime checker covers](development/test-coverage.md), [engineering scripts](../scripts/README.md) |
| Managing batches with an agent | [Operator runbook](runs/operator-runbook.md), prompts for [Codex](runs/operator-prompt-codex.md) and [Claude Code](runs/operator-prompt-claude.md) |
| Project page | [Design and sources](../site/DESIGN.md) |

## Terms

The guides use these words with one meaning each.

### What is run

| Term | Meaning |
| --- | --- |
| Task type | Transport, Mosaic, Relay or Dial |
| Team size | `small`, `medium` or `large`: how many arms a task has |
| Level | `l1`, `l2` or `l3`: how hard the same job is |
| Task, case | One released task, named `<task type>-<team size>-l<level>`, for example `mosaic-large-l3`. The code and file names say *case* |
| Run | One attempt at one task by one team of agents; one trial. A run that stops and continues is still the same trial |
| Batch | A folder of prepared runs that are started and supervised together. A batch has one harness and one model |
| Harness | The coding-agent program the agents run in: `codex` or `claude` (Claude Code) |
| Model | An entry of `models.json`, such as `sol` or `opus`. It names the provider's model, the endpoint and the credential variable |
| System | How the agents are organized: `adaptive`, `single-agent`, `hierarchical` or `decentralized` |
| Tools | `full` (the robot tool and the harness's shell and file tools) or `robot_only` (the robot tool alone) |
| Observation | `images` (camera images) or `ground_truth` (the simulator's state instead of images) |
| Guide | A text an agent reads about how to work: the collaboration guide and one guide per task type, under `prompts/guides/` |

### Who acts in a run

| Term | Meaning |
| --- | --- |
| Policy | The team of agents that is measured. Everything the policy may read is under the run's `public/` folder |
| Role | One agent of the policy, with its own session: a Controller, a Worker or a delegate |
| Controller | The role that leads. In `single-agent` and `adaptive` it controls arms itself |
| Worker | A role that controls one arm for the whole run (`hierarchical`, `decentralized`) |
| Delegate | A temporary role that an `adaptive` Controller creates by forking its own session and hands some arms |
| Session | One conversation of a harness CLI with the model: a Codex thread or a Claude Code session |
| Host | The process that runs the roles of one run: it starts their sessions, passes robot tool calls to the world and wakes idle roles |
| World | The simulation of one run. Its process, the *world owner*, steps the physics in real time, draws the images and scores the task |
| Robot tool | The one tool through which roles observe and move arms |
| Meta | The runtime's name for its own engineering manager: fixed operations such as binding sessions and delivering wakes. It makes no task decisions |
| Manager | The person, script or outer agent that prepares, starts and stops batches. It is not measured |

### Preparing and checking

| Term | Meaning |
| --- | --- |
| Site TOML | A small TOML file of your own that overrides some defaults of `roboteam.toml`, passed with `--config` |
| Frozen | Copied into the run at `prepare` and recorded by hash. A run uses its frozen inputs, code and settings even if the checkout changes later |
| Manifest | The run's list of frozen files and their hashes (`private/inputs/manifest.json`) |
| Policy environment | The Python environment the agents' own code runs in. It is built once per host and is separate from the benchmark's Python |
| Access table | The frozen list of folders the agents' file tools and shell may read or write. It closes the checkout, the home folder, other runs and shared storage |
| Sandbox | The operating-system mechanism that enforces the access table: Seatbelt on macOS, bubblewrap or Landlock with seccomp on Linux |
| Landlock | A Linux kernel feature with which a process restricts its own file and network access. `landlock-v1` is this project's sandbox built on it, for hosts where the harness's own sandbox cannot run |
| Tool backend | How Codex's shell, patch and image tools are confined: `native` (Codex's own sandbox) or `landlock-v1` |
| Doctor | `roboteam doctor`: local checks of the CLI, the sandbox and the renderer. No model call |
| Preflight | `roboteam preflight`: a few paid model calls that check the model works with the harness |
| Receipt | The file a passed check writes. `run` refuses a batch whose model and CLI version have no matching receipt |

### During and after a run

| Term | Meaning |
| --- | --- |
| START | The moment a run's clock starts. Each run has its own |
| Active time | The time a trial is running. Pauses, host sleep and the gaps between segments do not count |
| Cutoff | The end of a run's time limit (24 hours of active time). The world is scored then |
| Finish | The team's declaration that the task is done. Accepting it starts scoring; it is not a success verdict |
| Segment | One uninterrupted stretch of a run. A continuation starts the next segment of the same trial |
| Seal | Closing a world in order: no new actions, final images, then exit. `seal.json` is the record of it |
| Egress | A run's outbound network path to the model provider |
| Loopback gateway | A local process on `127.0.0.1` that translates one model API into another; used only by the two optional adapters |
| Evidence | Everything a run leaves: sessions, images, motion, records and scores |
| Collection | A portable copy of a stopped batch's evidence, with file hashes |
| Runs root | Where runs, receipts and exports go: `paths.runs_root`, by default `<repo>/runs` |
