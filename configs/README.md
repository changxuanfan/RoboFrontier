# Configuration and frozen inputs

The released tasks are in [`../benchmark/`](../benchmark/README.md). For a new run, start with [`../robofrontier.toml`](../robofrontier.toml), not a
legacy family JSON. The unified loader
resolves repository defaults, a partial operator TOML, and explicit CLI overrides
in that order. It rejects unknown fields and freezes the effective configuration
into a new batch. Changing settings does not change an already prepared batch.
See the [configuration and CLI guide](../docs/unified-cli.md).

| Path | Purpose |
| --- | --- |
| `models.json` | Native Codex model/provider profiles; unified defaults select Luna/high with API authentication |
| `codex-model-template.json` | Model metadata a Codex run starts from when its home has no cached entry for the model |
| `claude-models.json` | Native Claude Code model/provider profiles and transcript pricing; select an engine-specific profile explicitly |
| `harness.json` | Default runtime harness, used when a task names none |
| `harnesses/policy.json` | Native shared runtime/tool defaults for policy runs; model fields are baseline native settings, not overrides of a frozen unified profile |
| `harness-frontier-v2.json`, `harnesses/oracle.json` | The first is the Frontier V2 harness historical suites name by file. The first differs from `harness.json` in `topology` and `action_timeout_sim_s` (15 s, the earlier default; `harness.json` now allows 30 s). `harnesses/oracle.json` (formerly `harness-frontier-v2-servo2.json`) is the Oracle's, with its own model and effort fields |
| `policy-assets.json` | Pinned policy asset archive and integrity inventory used by automatic bootstrap/preparation |
| `factory-assets.json` | Independent R14 Factory recording release, split sizes and SHA-256 fingerprints; it does not change policy scene selection |
| `backgrounds/robo_factory.json` | Factory appearance, layout and shared visual resources |
| `patterns/` | Tulip pattern parameters used by the Frontier V2 scene builder |
| `retention.json` | What `scripts/curate_repository.py` keeps: Oracle sources, released inputs, final media and selected policy evidence; `skip_runs` names the `runs/` data roots it never proposes (batches and policy runs are always kept) |
| `examples/luna-l3-cpu.toml` | CPU Slurm example for the four maximum-arm Level 3 tasks |
| `environments/` | Scene revisions before release, the earlier revisions released cases and Oracle recordings name as sources, and scenes the tests open |
| `suites/` | Generated catalogs of earlier collections; `frontier-current-oracle.json` is the 36-station Oracle layout used by the Factory |

The remaining family registries, catalogs, harness JSON and older task configs
preserve the original experiments' version identities. Legacy
`suites/frontier-v2.json` and general generators do not replace purpose-specific
selection in [`../benchmark/release.json`](../benchmark/release.json). Compatibility evidence does not change
an original fingerprint, establish equivalent old/new Relay scoring, or authorize
applying new physical properties to an archived recording.

Keep credentials in the ignored `.env` or environment, never in these files.
API and subscription authentication belong to the selected native engine and
profile; choosing a model name alone does not establish provider compatibility.
Observation rendering, offline Factory rendering, model service timing, task
START timing and scheduler allocation lifetime have separate settings. Their
names and precedence are documented in the unified guide rather than inferred
from an old native script's defaults.

Editable Factory camera/title/subtitle projects are presentation inputs, not
policy settings. The shipped project is
[`tour-project.json`](../assets/robo_factory/tour-project.json); use the
[editorial commands](../docs/factory/editorial.md) to make and freeze a working
copy. Do not manually replace asset hashes or rewrite frozen motion to make a
different input appear to match the release.
