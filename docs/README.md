# Documentation

Start with [getting started](getting-started.md): it goes from a fresh clone to a finished run.
The [command-line guide](cli.md) lists every setting and command, and the
[repository layout](development/repository-layout.md) says where each file belongs.

| Topic | Guides |
| --- | --- |
| Overview | [Getting started](getting-started.md), [architecture](development/architecture.md), [repository layout](development/repository-layout.md), [command line and configuration](cli.md) |
| Tasks | [The four task types](tasks/README.md): [Transport](tasks/transport.md), [Relay](tasks/relay.md), [Mosaic](tasks/mosaic.md), [Dial](tasks/dial.md); the [released cases](../benchmark/README.md); the [project page](https://changxuanfan.github.io/RoboTeam/) shows all 36 |
| Rules of a run | [Runtime protocol](benchmark/rules.md), [physics and robot limits](benchmark/physics.md) |
| Harnesses | [Overview](harness/README.md), [Codex](harness/codex.md), [Claude Code](harness/claude-code.md), [providers](harness/README.md#providers) |
| Running | [Mac](hosts/mac.md), [RunPod and plain Linux](hosts/linux.md), [Slurm](hosts/slurm.md), [Docker](hosts/docker.md), [policy Python environment](hosts/policy-environment.md), [robot-only runs](benchmark/robot-tool-only.md), [stopped runs and continuing them](runs/continuation.md), [evidence storage](runs/evidence-storage.md), [saved-run viewer](runs/viewer.md), [Codex access-only attachments](harness/shared-login.md), [manager runbook](development/manager-runbook.md) |
| Configuration | [Settings files](cli.md#settings-files), [example site TOMLs](hosts/examples), [engineering scripts](../scripts/README.md) |
| Development | [Testing](development/testing.md), [harness check coverage](development/test-coverage.md) |
| Project page | [Design and sources](../site/DESIGN.md) |
