# Configuration and frozen inputs

The released tasks are in [`../benchmark/`](../benchmark/README.md). For a new run, start with [`../robofrontier.toml`](../robofrontier.toml), not a
legacy family JSON or the root `config.json` single-arm demo. The unified loader
resolves repository defaults, a partial operator TOML, and explicit CLI overrides
in that order. It rejects unknown fields and freezes the effective configuration
into a new batch. Changing settings does not change an already prepared batch.
See the [configuration and CLI guide](../docs/unified-cli.md).

| Path | Purpose |
| --- | --- |
| `models.json` | Native Codex model/provider profiles; unified defaults select Luna/high with API authentication |
| `claude-models.json` | Native Claude Code model/provider profiles; select an engine-specific profile explicitly |
| `policy-assets.json` | Pinned policy asset archive and integrity inventory used by automatic bootstrap/preparation |
| `factory-assets.json` | Independent R14 Factory recording release, split sizes and SHA-256 fingerprints; it does not change policy scene selection |
| `harnesses/policy.json` | Native shared runtime/tool defaults; model fields are baseline native settings, not overrides of a frozen unified profile |
| `backgrounds/robo_factory.json` | Factory appearance, layout and shared visual resources |
| `suites/frontier-current-oracle.json` | Frozen 36-station Oracle recording inputs for Factory layout; not proof of current task-solving qualification |
| `environments/` | Scene revisions before release, and the earlier revisions released cases and Oracle recordings name as sources |

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
[editorial commands](../docs/factory-editorial.md) to make and freeze a working
copy. Do not manually replace asset hashes or rewrite frozen motion to make a
different input appear to match the release.
