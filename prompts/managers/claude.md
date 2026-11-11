# Claude batch manager prompt

Give this prompt to a coding agent with terminal and repository access. The outer session can
use any model; Claude Code and the frozen profile select the measured model. Read the
[Claude Code guide](../../docs/engines/claude-code.md) before using it.

```text
Act as the outer manager for a RoboFrontier batch run by Claude Code. First read
docs/unified-cli.md and docs/engines/claude-code.md.

Settings:
- profile: haiku_subscription_token
- families: [transport, mosaic, relay, dial]
- level: 1
- min_arms: true
- topology: adaptive
- parallel: 4
- mode: plan            (plan | precheck | run)
- output: runs/policy/claude-l1
- precheck_budget_usd: 1

1. Inspect the checkout, its commit and whether the tree is clean. Manage this batch only;
   leave other sessions' runs to their operators.
2. Run `robofrontier doctor --engine claude --profile PROFILE`. Report missing credential
   variable names only, never values. If .env is absent, copy .env.example with mode 0600;
   never overwrite an existing .env.
3. Run `robofrontier plan --engine claude --profile PROFILE` with the selection. Report each
   case, its arm count and the model. For mode=plan, stop here.
4. For mode=precheck (real spend, only when authorized): run
   `robofrontier preflight --engine claude --profile PROFILE --confirm-spend --max-budget-usd B`,
   then `python -m robofrontier.engines.claude.claude_blocked_precheck --profile PROFILE
   --max-budget-usd B --confirm-spend`. Keep both receipts and report the results. A run is
   refused until both pass for this profile and CLI version.
5. For mode=run (real spend, only when authorized): `robofrontier prepare` into a new output
   folder with the selection, then `robofrontier run OUTPUT` (under launchd on macOS, or with
   `--durable` on Linux). Poll `robofrontier status OUTPUT` until it ends; stop with
   `robofrontier stop OUTPUT` and then inspect each run's seal and needs_review fields. A run
   that stopped unexpectedly continues by itself once; continue others by hand with
   `robofrontier continue OUTPUT [--cases ...]` only when asked.
6. Report the profile, the cases, concurrency, each run's final state and evidence paths, and
   anything still unverified.

The outer manager owns setup and supervision; the inner model owns task decisions, visual
reasoning and robot actions. Keep private answers isolated and frozen inputs unchanged; never
inject actions or change scoring. CLI-reported costs are estimates, not a payment ceiling.
```

The selection is a Cartesian product: one profile and the four families at level 1 with the
fewest arms give four runs. Prepare on the host that runs the batch, never copy a prepared
folder to another host.
