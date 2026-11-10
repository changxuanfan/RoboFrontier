# History

The main decisions in the order they were made, and where the earlier records are. The records
themselves (plans, handoffs, validations and engineering logs) were in `docs/archive/` until the
2026-11-10 cleanup; they are in the tag `archive/pre-cleanup-20261110`:

```sh
git show archive/pre-cleanup-20261110:docs/archive/README.md
git checkout archive/pre-cleanup-20261110 -- docs/archive        # all of them, into the tree
```

## Timeline

| Date | What changed | Records (in `archive/pre-cleanup-20261110`) |
| --- | --- | --- |
| 2026-10-19 | First NoSlip and slip diagnosis; RGB-only attempt | `docs/archive/history/noslip-validation-20261019.md`, `slip-diagnosis-20261019.md`, `rgb-attempt-20261019.md` |
| 2026-10-22 | Robot command audit: what a policy command really does | `docs/archive/robot-command-reality-audit-20261022.md` |
| 2026-10-24 to 10-27 | Frontier V2 suite: Transport r11–r13, Mosaic r13/r14, Relay r8–r16, Dial BEST5 r11; the Oracle recordings | `docs/archive/plans/suite-v2/`, `docs/archive/history/transport-*.md`, `mosaic-*.md`, `relay-*.md`, `dial-*.md` |
| 2026-10-27 | Robo Factory and its integration | `docs/archive/history/robo-factory-*.md` |
| 2026-10-28 | Native Claude Code harness; model compatibility and pricing observations | `docs/archive/plans/claude-native-harness-20261028.md`, `model-compatibility-20261028.md`, `model-pricing-20261028.md` |
| 2026-10-30 | Evidence storage validated | `docs/archive/evidence-storage-validation-20261030.md` |
| 2026-11-01 | Claude Code engine merged beside Codex, all four topologies | `docs/archive/unified-main.md` |
| 2026-11-02, 11-03 | Engine parity (PRs #6–#13); released inputs moved into `benchmark/`; Relay scored at 70 % inside GOAL; unused scripts pruned (tag `archive/pre-prune-20261103`) | `docs/archive/unified-main.md`, `benchmark/pruned-paths.json` |
| 2026-11-03 | Landlock Bash isolation for CPU hosts | `docs/archive/history/codex-landlock-cpu-research-20261103.md` |
| 2026-11-06 | Frozen policy Python environment (PRs #14–#17); simulation speed work; Relay handover rules (#19) | [Policy environment](running/policy-environment.md) |
| 2026-11-09 | realtime-v2 physics (#20); second code review; benchmark rules: 24 h of active time scored at the cutoff, continuations are the same trial, Relay handovers airborne only (#21) | `outputs/review/` on the author's machine |
| 2026-11-10 | Outage probe over TLS, task recovery, Mac defaults (#23–#28); cleanup plan D1–D40 and stage 0 (#29) | [Cleanup record](cleanup-20261110.md) |
| 2026-11-10, 11-11 | The cleanup: release physics in the scenes and real Franka limits, one release, one evaluator, both engines alike, stop table and usage-limit pauses, Oracle and configs tidied, model-visible text rewritten | [Cleanup record](cleanup-20261110.md), [Physics](physics.md) |

## Tags

| Tag | What it keeps |
| --- | --- |
| `archive/pre-prune-20261103` | The tree before unused scripts and records were pruned on 2026-11-03 |
| `archive/pre-cleanup-20261110` | The tree before the 2026-11-10 cleanup, including `docs/archive/`, `configs/environments/`, `configs/suites/` and the scene builder |
| `archive/branch/...` | Every experiment branch and worktree that was removed, at its last commit |
