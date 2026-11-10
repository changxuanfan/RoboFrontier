# Development checks and optional historical fixtures

Install the locked Python environment and Node.js before running these checks.
The selected native CLIs are needed only by tests that explicitly exercise them.
See the acceptance ledger (`docs/archive/unified-main.md`, in the [archive tag](../history.md)) for exact results and limitations.

## Protocol checks

```sh
PYTHONPATH=tests:scripts .venv/bin/python -m scripts.check_harness \
  --protocol-only --report runs/engineering/protocol.json
```

This group prohibits MuJoCo model creation and physical stepping. It tests
synthetic task/runtime contracts, private scoring,
frozen inputs, recovery boundaries, JavaScript and portable documentation links.
It starts no native policy session and calls no model/provider. Its passing
result does not qualify actual robot dynamics, native provider behavior or
multi-agent task solving.

## Every test, in parallel

```sh
.venv/bin/python -m scripts.run_tests                     # one worker per CPU
.venv/bin/python -m scripts.run_tests runtime engines.test_codex_quota --workers 4
```

Each `tests/**/test_*.py` module runs in its own process and each `tests/**/test_*.js` with
`node --test`; a failed module runs once more alone, and only a repeated failure counts. Tests
that start a world open a hidden GLFW window: on macOS the screen must be unlocked (the window
service does not answer otherwise), on Linux use a display such as `xvfb-run -a`. CI's
`all-tests` job runs it that way.

## Full local discovery

```sh
PYTHONPATH=tests:scripts .venv/bin/python -m scripts.check_harness \
  --report runs/engineering/full.json
```

Full discovery additionally exercises real robot/contact physics and media
codecs. When installed, native CLIs may communicate with isolated synthetic
loopback model endpoints. These are test sessions, not paid provider inference
or measured model-solving runs. Existing explicit physical/provider qualification
switches remain separate; inspect skipped tests rather than counting them as
executed qualifications.

The `c830202` follow-up passes 1,536 checks on each of macOS and Linux,
with zero failures/errors and 17 conditional skips. Two captured-state placement
regressions reproduce the prior search failures. All 19 related Transport/Oracle
checks pass on both platforms, and a fresh current-scene Transport L1 reference
completes all 12 goals with clean process/physics/action verdicts. This is private
Oracle engineering, not model qualification or a new physical-candidate release.
Older opt-in native/replay receipts retain their exact source and data scope.

The ordinary policy bootstrap restores the current 36-case policy inputs. Full
historical discovery also reads older scene assets/previews, the original
source-preservation receipt, selected closed Oracle reports/streams and their
frozen harness/evaluator source. They are ignored data, not Git source. Missing
fixtures are errors; do not regenerate approximate images, rewrite old reports,
change hashes or relabel a historical success as current physics qualification.

The local 2026-11-02 passing discovery used independently copied historical
fixtures from the preserved primary checkout. Scene XML identities and pinned
asset/report/source hashes were verified, and original files were retained.
The restoration receipts are under
`runs/engineering/main-integration-oracle-final-20261102/`. The optional local
delivery contains `legacy-test-fixtures-v4.tar.gz` and
`legacy-test-fixtures-v4.json`. It contains original ignored test inputs, not
new task qualification or native sessions. Its 45,141 files are pinned by
individual SHA-256 checksums. The archive checksum is
`b1ddf425f8c538a05fab705767f28d586905fc49944901a60c2cf0d5bb9bfe06`.
The manifest checksum, supplied independently of its contents, is
`909e9a42b2c4048bb9d5affc58fdc3930c449394b8efb1f83e854ae98ff9ba06`.

Download the [optional archive](https://github.com/changxuanfan/RoboFrontier/releases/download/development-fixtures-20261102/legacy-test-fixtures-v4.tar.gz)
and [manifest](https://github.com/changxuanfan/RoboFrontier/releases/download/development-fixtures-20261102/legacy-test-fixtures-v4.json)
from the separate development-fixture prerelease and verify them against the
independent pins above. Its checked installer, `scripts/install_historical_fixtures.py`,
was removed on 2026-11-10 with the release freeze; restore it from tag
`archive/pre-cleanup-20261110` to install the bundle (see the
[cleanup log](../cleanup-20261110.md)). The dated Relay source aliases under
`outputs/oracle/relay-edited-tracks-20261027/` are included only for the nine
registered source directories and their original metadata/assets. Other output
paths are rejected. The dated Mosaic review packages, design/coverage certificates,
protected original media and separately extracted frozen-builder provenance are
also included. Original source/recording bytes and qualification labels remain
unchanged; current static projection/caption compatibility has explicit receipts.

The development bundle does not include all raw Mosaic motion chunks. Default
package checks validate the original pinned reports/audits, stream indexes,
frozen controls/evaluators and public artifacts. An explicit
`--verify-recorded-chunks` additionally needs complete original motion trees.
A read-only local verification of those originals checked 72,141 chunks across
8,656,459 frames; that receipt does not claim the chunks were relocated into
this development archive. This bundle is a test dependency set, not a full
export of every historical experiment.

This is an explicit optional development bundle, not an automatic download in
the ordinary policy bootstrap. The separate release does not change that
bootstrap. The policy download alone does not reproduce full historical
discovery in a fresh clone.

## Filesystems and platform scope

Keep test databases, native homes, temporary executables and fixture outputs on
the same local operating-system filesystem. In Linux containers, use writable
local temporary directories for legacy fixture generation and Python bytecode;
read-only source alone is not a writable test environment. Do not open active
SQLite databases across a Docker/host boundary.

An existing dependency image with current source mounted or copied into it is
distinct from a newly built image containing that source. Linux CPU/Mesa checks
do not qualify NVIDIA/EGL, OPTIX, x86_64, real Slurm allocations, subscription
refresh or 36-task resource capacity. Keep those boundaries in every receipt.
