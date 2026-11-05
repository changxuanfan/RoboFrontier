# Documentation

Start with [getting started](getting-started.md), the [repository layout](repository-layout.md) and the
[command-line guide](unified-cli.md). The [project page source](../site/DESIGN.md) lives in `site/`.

| Topic | Guides |
| --- | --- |
| Overview | [Getting started](getting-started.md), [architecture](architecture.md), [repository layout](repository-layout.md), [command line and configuration](unified-cli.md) |
| Tasks | [The four families](tasks/README.md): [Transport](tasks/transport.md), [Relay](tasks/relay.md), [Mosaic](tasks/mosaic.md), [Dial](tasks/dial-best5.md); [task atlas](tasks/atlas.md) |
| Rules of a run | [Runtime protocol](protocol.md), [contact physics](physics.md) |
| Engines | [Overview](engines/README.md), [Codex](engines/codex.md), [Claude Code](engines/claude-code.md), [providers](engines/providers.md) |
| Running | [Docker](running/docker.md), [Slurm](running/slurm.md), [Policy Python environment](running/policy-environment.md), [Linux handoff](running/server-benchmark.md), [continuing after an exit](running/run-segments.md), [evidence storage](running/evidence-storage.md), [saved-run viewer](running/local-viewer.md), [manager runbook](meta-runbook.md) |
| Oracle | [Privileged Oracle execution](oracle/README.md), [recovery](oracle/recovery.md), [Relay recorded video](oracle/relay-recorded-video.md) |
| Factory | [Design and rendering](factory/README.md), [replay](factory/replay.md), [Linux and Slurm](factory/server.md), [editing](factory/editorial.md) |
| Development | [Testing](development/testing.md), [harness acceptance scope](harness-v2-verification.md), [Anthropic subscription qualification](development/anthropic-subscription-qualification.md) |
| History | [archive/](archive/README.md): dated plans, validations and earlier layouts |

`task-atlas/` is the published atlas site, built by `scripts/build_task_atlas.py`.
