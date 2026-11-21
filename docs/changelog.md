# Changelog

Changes that a user of the benchmark can notice. A change to the tasks, the prompts, the robot
tool or the physics is marked **benchmark**, because results before and after it are not
comparable.

## Unreleased

- Run data layout: batches are under `runs/batches/` (was `runs/policy/`), preflight receipts
  under `runs/receipts/` (was `runs/engineering/`), the scene cache under `runs/scene-cache/`
  (was `runs/state-assets/`). Batches and receipts made before this change are not read.
  What the agents see (`public/`, the prompts, the robot tool) is unchanged.
- A Claude Code batch names its control files `supervisor-status.json`, `supervisor-claim.json`
  and `supervisor.lock` (were `engineering-*`); the lock has the same name as in a Codex batch.
- Modules renamed: `roboteam/runtime/run/admin.py` (was `cli.py`), `roboteam/launch/cases.py`
  (was `tasks.py`), `roboteam/analysis/run_files.py` (was `archive.py`); the `tools` and
  `observation` conditions are in `roboteam/tasks/`. The subpackages no longer import upward
  (`tests/repo/test_layering.py`).
- A wrong CLI or library version is refused with the command that installs the pinned one.
- A world started under an X display that needs an authority file (`xvfb-run`, a forwarded
  display) now gets `XAUTHORITY`; before, its window could not open.
- Claude Code models: `opus_subscription` now uses the saved Claude Code login, like
  `haiku_subscription`; the token model is `opus_subscription_token`.
- `seal.json` names the final images taken at the cutoff (`cutoff_observation`) and says
  `"recording": "off"` when no video was asked for.
- A failed Codex preflight prints its cause instead of a Python traceback.
- The operator guides moved to `docs/runs/` (`operator-runbook.md` and two prompts).
- Citation, contribution guide and package metadata added.
- Fewer files at the repository root: the contribution guide, the code of conduct and the
  Prettier settings are in `.github/`, this changelog in `docs/`, the Docker ignore file beside
  the Dockerfile; `.python-version` is gone (`requires-python` already says 3.12).

## 0.1.0

The release described in the paper ([arXiv:2611.22138](https://arxiv.org/abs/2611.22138)): 36
tasks in four task types, four agent systems, and the Codex and Claude Code harnesses.
