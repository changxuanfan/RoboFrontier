# Codex batch manager prompt

Give this prompt to a coding agent with terminal and repository access. The outer session can
use any model; Codex CLI and the frozen profile select the measured model. Read the
[Codex engine guide](../../docs/engines/codex.md) and the
[providers section](../../docs/engines/README.md#providers) before using it.

```text
Act as the outer manager for a RoboFrontier batch run by Codex. First read
docs/unified-cli.md and docs/engines/codex.md.

Settings:
- profile: luna
- effort: high
- families: [transport, mosaic, relay, dial]
- level: 1
- min_arms: true
- topology: adaptive
- parallel: 4
- mode: plan            (plan | precheck | run)
- output: runs/policy/codex-l1

1. Inspect the checkout, its commit and whether the tree is clean. Manage this batch only;
   leave other sessions' runs to their operators.
2. Run `robofrontier doctor --engine codex --profile PROFILE`. Report missing credential
   variable names only, never values. If .env is absent, copy .env.example with mode 0600;
   never overwrite an existing .env.
3. Run `robofrontier plan --engine codex --profile PROFILE --effort EFFORT` with the selection.
   Report each case, its arm count and the model. For mode=plan, stop here.
4. For mode=precheck (real spend, only when authorized): run
   `robofrontier preflight --engine codex --profile PROFILE --effort EFFORT --confirm-spend`.
   Keep the receipt and report the result. A run is refused until it passes for this profile,
   catalog and CLI version; a `--smoke-only` receipt does not qualify a run.
5. For mode=run (real spend, only when authorized): `robofrontier prepare` into a new output
   folder with the selection, then `robofrontier run OUTPUT` (under launchd on macOS, or with
   `--durable` on Linux). Poll `robofrontier status OUTPUT` until it ends; stop with
   `robofrontier stop OUTPUT` and then inspect each run's seal and needs_review fields. A run
   that stopped unexpectedly continues by itself once; continue others by hand with
   `robofrontier continue OUTPUT [--cases ...]` only when asked.
6. Report the profile and effort, the cases, concurrency, each run's final state and evidence
   paths, and anything still unverified.

The outer manager owns setup and supervision; the inner model owns task decisions, visual
reasoning and robot actions. Keep private answers isolated and frozen inputs unchanged; never
inject actions or change scoring. Do not switch models, update a CLI or start a second copy of
a batch after a provider fault; report it with its evidence.
```

The selection is a Cartesian product: one profile and the four families at level 1 with the
fewest arms give four runs. Each batch has one profile; prepare separate batches for other
profiles and add up their concurrency. Prepare on the host that runs the batch, never copy a
prepared folder to another host.
