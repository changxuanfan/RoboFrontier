# Public task atlas

Open [the current atlas](../task-atlas/index.html) in a browser. The tracked directory
contains all 36 current policy tasks, two real static initial views per case,
English public rules, completion criteria, release/source identities and public
JSON downloads. Family, difficulty, arm-count and ID filters work without a
server. Camera buttons switch between top and front views. On a phone the task
cards become one column. There are no external fonts, analytics or JavaScript
libraries.

For browsing from GitHub, [download the verified offline atlas ZIP](https://github.com/changxuanfan/RoboFrontier/releases/download/development-fixtures-20261102/robofrontier-task-atlas-20261102.zip),
unzip it and open `index.html`. This avoids GitHub's source-code view of HTML.
The download contains the same tracked page, public records and original images;
it requires no account, local server, API call or simulator. The separate large
historical test-fixture archive on that release is optional for developers.

These are engineering initial-state renders, not successful task demonstrations.
Qualification labels preserve the release's source claims; rendering does not
upgrade them. Mosaic uses the current R14 source. Neither Oracle solutions nor a
Dial private code are included. The atlas applies the same reviewed public
projection and terminal-outcome overlay as newly prepared policy tasks, so old
process-compliance vetoes do not reappear in its task descriptions.

## Verify or distribute

From a repository checkout with locked Python dependencies installed:

```sh
.venv/bin/python -m scripts.build_task_atlas verify
.venv/bin/python -m scripts.build_task_atlas zip \
  --zip outputs/exports/robofrontier-task-atlas.zip
```

Choose a new ZIP path each time. The command refuses to overwrite a delivered
archive. It checks every file hash and JPEG, every local HTML link, the generator
and template identities, and equality with the current public task contracts.
The ZIP uses deterministic metadata and relative paths. Unzip it into an empty
directory and open `index.html`; no credential, installation, API or server is
required to browse it. Validate an extracted package with:

```sh
.venv/bin/python -m scripts.build_task_atlas verify --output /path/to/extracted-atlas
```

Verification needs the matching source checkout, because it compares against
its released contracts. Browsing the package needs only a browser. Editing the
release or generator makes the old artifact stale; do not update manifest hashes
to conceal that mismatch. Rebuild scenes when inputs change, or use the verified
presentation-only refresh below when all public contracts and captures still match.

The primary artifact is `docs/task-atlas/`; `web/task-atlas/` contains its editable
HTML/CSS/JavaScript sources. `tasks.json` collects all public records, `tasks/`
provides individual records, and `atlas-manifest.json` binds each delivered file
to the release and generator. Generated runtime recordings, credentials and local
machine paths do not belong in this directory.

## Update page text without rendering again

`refresh` regenerates HTML/CSS/JavaScript while copying all 72 original JPEGs
and public task records byte for byte. It creates no MuJoCo model or RGB context,
steps no physics and invokes no model. It requires a new output directory and
the full commit ID of the source publication. That commit must contain the exact
incoming `docs/task-atlas/atlas-manifest.json` and its generator/templates.
The existing contracts, complete file inventory, JPEG decoding and hashes must
pass before any output is created. A changed/rehashed image or task contract
cannot be relabeled as an unchanged original capture.

Before editing presentation sources, record the publication commit. After editing
`web/task-atlas/`, use that full ID, for example:

```sh
# Save this ID before editing the presentation sources.
ATLAS_SOURCE_REVISION=$(git rev-parse HEAD)

# After editing, choose a fresh output directory.
.venv/bin/python -m scripts.build_task_atlas refresh \
  --source docs/task-atlas --source-revision "$ATLAS_SOURCE_REVISION" \
  --output outputs/task-atlas/text-update
.venv/bin/python -m scripts.build_task_atlas verify \
  --output outputs/task-atlas/text-update
```

Creation requires the source commit in local Git history; fetch it first if using
a shallow clone. The refreshed v2 manifest separately retains the original v1
capture manifest, its SHA-256 and source commit. It binds the new presentation to
current sources while preserving original renderer, release, image profile and
capture identities. Verification checks that retained image/task hashes still
match the original capture. It does not need the historical Git objects or a
renderer; it does still need the matching current source checkout and contracts.
Existing v1 artifacts remain supported by their matching source.

Review the new page before replacing the tracked publication. Refresh never
overwrites or adds files inside the source publication, and never changes its
scene fingerprint or qualification. Later refreshes retain the first capture
proof rather than recursively duplicating presentation history. Changed release,
public contracts or image bytes require a separate rebuild/review.

## Regenerate from the current release

Bootstrap the exact policy assets first. Rendering is a separate explicit step
and never invokes a model or advances physics. The renderer resets each source
scene to its declared `initial` keyframe and runs forward kinematics. Images use
896 x 560 JPEG quality 85. Each scene's actual OpenGL backend is checked; a
requested NVIDIA/CPU backend cannot silently fall back.

Use a new output directory, for example on macOS:

```sh
.venv/bin/robofrontier bootstrap
.venv/bin/python -m scripts.build_task_atlas build --render native \
  --output outputs/task-atlas/review-candidate
```

On Linux use `--render nvidia` for NVIDIA EGL or `--render cpu` for Mesa OSMesa.
The CPU path requires the same system libraries as benchmark CPU rendering.
Inspect the output and run its verifier before replacing the tracked publication
through ordinary Git review. Preserve the previous published artifact in Git
history; do not reuse old screenshots with a new scene fingerprint.

## Optional GitHub Pages publication

The `Task atlas` workflow validates the tracked atlas on relevant pull requests
and manual runs. Its default manual action only validates. An authorized
maintainer can select `publish=true` in a manual run after enabling GitHub Actions
as the repository's Pages source. Only the verified `docs/task-atlas/` artifact is
uploaded; the repository, ignored experiment data and private state are not.

The deployment job is separate, requires `github-pages` environment approval/rules
when configured, and requests Pages/OIDC permissions only for that job. There is
no automatic publication on push. A checked-in workflow is not evidence that a
live site has been deployed. Setup follows GitHub's official
[custom Pages workflow guide](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages).

The optional readonly run dashboard is a different feature. This static atlas
never reads live benchmark databases, native session directories or supervisor
snapshots, and cannot start/stop robot tasks.
