# Repository layout and retained data

The repository contains source, pinned metadata and the public task atlas.
Runtime data and large assets have separate explicit installation/backup paths.
Cloning source is not a backup of ignored recordings or credentials.

| Path | Purpose |
| --- | --- |
| `README.md` | Installation, defaults, command examples and integration status |
| `robofrontier.toml` | Unified defaults for new runs; prepared runs freeze their resolved settings |
| `robofrontier/` | Shared physics/runtime/evidence contracts and native engine modules |
| `robofrontier/codex/`, `robofrontier/claude/` | Native Codex and Claude Code engines |
| `benchmark/release.json` | Current 36-case policy/Oracle source registry |
| `configs/policy-assets.json` | Pinned policy asset archive, hashes and release identity |
| `configs/factory-assets.json` | Separate optional Factory recording bundle lock |
| `configs/models.json`, `configs/claude-models.json` | Engine-specific provider/model profiles |
| `prompts/` | Public policy and role/tool instructions |
| `scripts/`, `tests/` | Engineering commands, retained scene/reference builders and regression checks |
| `web/task-atlas/` | Editable English atlas templates and browser interactions |
| `docs/task-atlas/` | Tracked, verified public offline atlas with 72 current initial JPEG views |
| `docs/` | Guides, source provenance, acceptance ledger and explicitly historical material |
| `docker/` | Unified image and labeled legacy image |
| `runs/policy/`, `runs/oracle/` | Ignored original run evidence, frozen inputs and motion |
| `runs/exports/` | Ignored stopped-run collections and portable evidence ZIP files |
| `runs/engineering/` | Ignored engineering checks, failure evidence and acceptance receipts |
| `outputs/` | Ignored renders, editable media projects and exported delivery packages |
| `.robofrontier/` | Ignored task-local native state and container command receipts |
| `vendor/`, `configs/environments/**/assets/` | Ignored large assets restored from the pinned package |

Use the [unified CLI guide](unified-cli.md) to run a benchmark, the
[Oracle guide](oracle.md) for explicit reference execution, and the
[Factory guide](factory.md) to import a recording and render a different
background. The [atlas guide](task-atlas.md) explains current public browsing,
verification and offline ZIP distribution.

## Original evidence versus collections

Original task evidence and native session homes are the writable sources during
execution. Each run's `codex-home.json` records its exact native home; new API
runs use a separate task home below `.robofrontier/codex/`. Claude engineering
runs use their run-local `private/claude-config`. Host JSONL events are not a
substitute for native session transcripts.

Collection occurs after writers stop. It resolves task-associated sessions and
copies the required portable evidence into `runs/exports/`, where an archive can
deduplicate identical files and extract inline images reversibly. Originals stay
available for audit and native history. A successful ZIP does not reclaim their
disk space automatically. Deleting originals is a separate decision after
verified restore and independent backup; see [evidence storage](evidence-storage.md).
Never monitor active node/container SQLite files through a shared mount.

## Legacy local delivery layouts

Older local worktrees may contain `outputs/final/manifest.json` and relative
media links under `outputs/final/oracle/` and `outputs/final/factory/`. These were
browsing indexes, not source-controlled media bundles. Their manifests preserve
original paths, source-frame edits, playback rates, hashes and assisted labels.
Keep those records with the matching recordings. A new release cannot silently
reinterpret an old Oracle recording as autonomous or replace its frozen physics.

The previous untracked atlas under `outputs/task-atlas/v1-20261027/` and its
exported ZIP are legacy local artifacts. The tracked English replacement is
`docs/task-atlas/`; it is generated anew from the current public release. Old
worktree cleanup/retention receipts under
`runs/engineering/cli-migration-cleanup-20261027/` describe that historical local
inventory, not permission to delete future recordings. Current cleanup must use
its own explicit scope and verification.

The early `config.json` and single-arm demo remain legacy application inputs.
They are not the unified benchmark configuration. Historical docs and plan files
must be read with their date/source context; current defaults and acceptance are
stated in the unified guides and [integration ledger](archive/unified-main.md).
