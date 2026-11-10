# Configuration

Settings for new runs start in [`../robofrontier.toml`](../robofrontier.toml). The loader layers
the repository defaults, a partial site TOML (`--config`) and command-line options, in that
order, rejects unknown fields, and freezes the result into each new batch; changing a setting
never changes a prepared batch. The released tasks are in [`../benchmark/`](../benchmark/README.md);
the commands are in the [CLI guide](../docs/unified-cli.md).

| Path | What it is |
| --- | --- |
| `models.json` | Every model profile, one section per engine (`engines.codex`, `engines.claude`, which also holds Claude transcript prices). A run freezes its engine's section |
| `harnesses/policy.json` | The policy runtime's settings (topology, timeouts, observation images); no speeds or forces, which every action states |
| `harnesses/oracle.json` | The Oracle's harness, with its own model and effort fields |
| `harness.json` | The runtime harness a task without one uses (tests rely on its hierarchical topology) |
| `policy-env/` | The frozen policy Python environment: inputs and locks (`core`, `store`, `all`) |
| `policy-assets.json` | The pinned policy asset archive and its inventory, restored by `robofrontier bootstrap` |
| `factory-assets.json` | The Factory recording release: split sizes and SHA-256 fingerprints |
| `backgrounds/robo_factory.json` | Factory appearance, layout and shared visual resources |
| `evaluations/private/` | Private Dial evaluator inputs the Oracle's records name |
| `examples/mac.toml`, `slurm.toml`, `runpod.toml` | A starting site TOML for each platform |

Credentials belong in the ignored `.env` or the environment, never in these files. Choosing a
model name alone does not establish provider compatibility: a run needs passed preflight
receipts for its profile.

Editable Factory camera and title projects are presentation inputs, not policy settings; the
shipped one is [`tour-project.json`](../assets/robo_factory/tour-project.json) (see the
[editorial commands](../docs/factory/editorial.md)).
