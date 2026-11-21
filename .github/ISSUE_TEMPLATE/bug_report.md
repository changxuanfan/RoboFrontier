---
name: Bug report
about: A command fails, a run ends wrongly, or the docs do not match what happens
labels: bug
---

**What happened**

**What you expected**

**How to reproduce**

The commands, from a clean checkout if possible, and the site TOML without credentials.

**Environment**

- Host: (macOS / Linux, GPU or CPU rendering, Slurm, Docker)
- Commit: (`git rev-parse --short HEAD`)
- Harness and CLI version: (`claude --version` or `codex --version`)
- Model entry of `models.json`:
- Output of `.venv/bin/roboteam doctor`:

**Evidence**

The relevant part of `roboteam status BATCH`, and of a run's `private/outputs/seal.json` and
`private/logs/`. A whole run folder is private: it holds session transcripts. Remove anything
you do not want public, and never paste a credential.
