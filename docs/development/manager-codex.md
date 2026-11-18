# Codex batch manager prompt

Give this prompt to a coding agent with terminal and repository access. The outer session can
use any model; Codex and the frozen model entry select the measured model. Read the
[Codex guide](../harness/codex.md) and the
[providers section](../harness/README.md#providers) before using it.

```text
Act as the outer manager for a RoboTeam batch run by Codex. First read
docs/cli.md and docs/harness/codex.md.

Settings:
- model: sol
- effort: high
- task types: [transport, mosaic, relay, dial]
- level: 1
- min_arms: true
- system: adaptive
- parallel: 4
- mode: plan            (plan | precheck | run)
- output: runs/policy/codex-l1

1. Inspect the checkout, its commit and whether the tree is clean. Manage this batch only;
   leave other sessions' runs to their operators.
2. Run `roboteam doctor --harness codex --model MODEL`. Report missing credential
   variable names only, never values. If .env is absent, create it with
   `python -m roboteam.launch.results.assets init-env`; never overwrite an existing .env.
3. Run `roboteam plan --harness codex --model MODEL --effort EFFORT` with the selection.
   Report each case, its arm count and the model. For mode=plan, stop here.
4. For mode=precheck (real spend, only when authorized): run
   `roboteam preflight --harness codex --model MODEL --effort EFFORT --confirm-spend`.
   It makes the compatibility receipt; keep it and report the result. A run is refused until it
   passes for this model, catalog and CLI version; a `--smoke-only` receipt does not qualify.
5. For mode=run (real spend, only when authorized): `roboteam prepare` into a new output
   folder with the selection, then `roboteam run OUTPUT` (under launchd on macOS, or with
   `--durable` on Linux). Poll `roboteam status OUTPUT` until it ends; stop with
   `roboteam stop OUTPUT` and then inspect each run's seal and needs_review fields. A run
   that stopped unexpectedly continues by itself once; continue others by hand with
   `roboteam continue OUTPUT [--cases ...]` only when asked.
6. Report the model and effort, the cases, concurrency, each run's final state and evidence
   paths, and anything still unverified.

The outer manager owns setup and supervision; the inner model owns task decisions, visual
reasoning and robot actions. Keep private answers isolated and frozen inputs unchanged; never
inject actions or change scoring. Do not switch models, update a CLI or start a second copy of
a batch after a provider fault; report it with its evidence. A ChatGPT-login model needs
runtime.codex_home_scope = "shared" in a site TOML passed with --config.
```

The selection is a Cartesian product: one model and the four task types at level 1 with the
fewest arms give four runs. Each batch has one model; prepare separate batches for other
models and add up their concurrency. Prepare on the host that runs the batch, never copy a
prepared folder to another host.
