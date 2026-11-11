# Editable English Factory presentation

The full Factory tour is 210.5 seconds, 30 fps and 6,315 frames. Its English
titles, task subtitles, camera waypoints, typography and source fingerprints are
editable files. The checked-in project starts at
[`assets/robo_factory/tour-project.json`](../../assets/robo_factory/tour-project.json).
It targets the pinned 36-station R14 Factory bundle. The font and its SIL Open
Font License are already in the repository; rendering does not download a font.

The published full tour (1080p, 30 fps, 210.5 seconds) is the GitHub release
[`factory-tour-media-20261102`](https://github.com/changxuanfan/RoboFrontier/releases/tag/factory-tour-media-20261102),
with its checksums. It shows Oracle reference recordings, not model results.

Read the [Factory installation guide](replay.md) first. Offline video uses
Blender Cycles, ffmpeg and ffprobe with libass and libx264. It is independent of
policy image size, model credentials and benchmark task timing.

## Create a working project

Create a new editable copy from the configured Factory data:

```sh
.venv/bin/robofrontier factory project --output runs/factory/tour-project
```

The command installs the pinned data if needed, verifies the complete bundle,
and publishes a new directory only after validating its project. It does not
run Blender, call a model, or advance physics. Existing project directories are
never overwritten. A different verified data bundle can be selected explicitly
with `--source imported --data-root /path/to/bundle`; a full tour requires all 36
workstations and all three scales at each family/level.

```text
tour-project/
  project.json             # Timing, style, file names and source hashes
  camera-plan.json         # Camera position/target/FOV at each waypoint
  titles.srt               # Opening title and family headings
  subtitles.srt            # Family descriptions and actual task/level/arm labels
  fonts/
    BarlowCondensed-SemiBold.ttf
    OFL.txt                # Keep the font license with the project
```

The shipped project uses `tour-` file names in the existing asset directory to
share that directory's font without duplicating it. The generated working copy
uses the layout above. Both have the same editable interface.

## Edit text and typography

Edit `titles.srt` and `subtitles.srt` in a text or subtitle editor. For example:

```srt
1
00:00:00,000 --> 00:00:10,000
RoboFrontier
Can Multimodal Agents Work Together
on Long Physical Tasks?
```

Each track must have numbered, chronologically ordered, nonoverlapping cues,
with positive intervals entirely inside the project duration. Title and subtitle
tracks may overlap each other. Text is plain English; ASS formatting directives
are escaped rather than executed. An empty track is permitted. Cues after an
explicit diagnostic preview's endpoint are naturally absent from that preview;
the full project is still preserved.

`project.json` contains a `style` object:

```json
{
  "title_size": 64,
  "subtitle_size": 40,
  "title_margin": 60,
  "subtitle_margin": 64,
  "horizontal_margin": 90,
  "color": "#FFFFFF"
}
```

Sizes and vertical margins scale from a 1080-pixel-high reference; horizontal
margins scale from a 1920-pixel-wide reference. Titles are centered at the top,
subtitles at the bottom, with an outline and shadow. Font family is read from
the actual retained font file. Integer dimensions must be positive. Unknown
fields fail validation instead of silently doing nothing.

The task subtitles are derived from the actual source inspection cameras and
task metadata, not inferred from task naming alone or from a success claim.
They are independent editable editorial text: after changing camera timing or
order, update subtitle timing/labels to match the new shots. Changing the camera
does not automatically rewrite an existing SRT file.

## Edit cameras

Each entry in `camera-plan.json` has exactly these fields:

```json
{
  "t": 0.0,
  "label": "opening",
  "camera": {
    "position_m": [0.0, -6.0, 4.0],
    "target_m": [0.0, 0.0, 0.8],
    "vertical_fov_deg": 48.0
  }
}
```

The example illustrates the format; keep the generated coordinates for the real
Factory layout unless deliberately changing a shot. Coordinates are world-space
meters. Times increase strictly from zero through the full project duration,
with at least four waypoints. Position must differ from target. FOV must be
between 1 and 179 degrees. Native tour interpolation handles the opening and
subsequent transitions; roof visibility is derived from camera height. Do not
add opaque native camera masks to this editable format.

Camera changes require exporting new pose frames and rendering again. They do
not rerun robot actions. Independent station clocks and explicit reset events
remain part of the native replay. Editing a camera does not change source
motion, colors, scoring, or physical contact parameters.

## Freeze and render a new movie

Use the shipped project directly, or point `--project` at your working copy:

```sh
.venv/bin/robofrontier factory prepare --mode promo \
  --project assets/robo_factory/tour-project.json \
  --output runs/factory/full-tour
.venv/bin/robofrontier factory run runs/factory/full-tour/plan.json --index 0
.venv/bin/robofrontier factory status runs/factory/full-tour/plan.json
```

Omitting `--project` generates the default English project in the new render
plan. Preparation freezes all six project files, resolved settings, code hashes
and bundle identity. The project must match the selected bundle/scene/camera/
release fingerprints. The default is the full 210.5 seconds; no alternate short
cut is substituted. A deliberate `--duration-s 0.1` produces a three-frame
diagnostic preview. A cap above the full project duration is rejected.

Project duration must be finite and represent a whole number of 30-fps frames.
For a deliberate full-duration edit, update camera endpoints and SRT intervals
as well. A changed operator project leaves an already prepared plan intact;
prepare a new output directory to apply the changes. Modifying a frozen project
invalidates execution. Changes during rendering also prevent successful sealing.

The attempt retains:

```text
jobs/promo/attempt-.../
  poses/                   # Frame poses, camera plan, clocks and reset events
  render/
    factory.mp4            # Original Cycles movie, without editorial text
    report.json
  editorial/
    factory.mp4            # Final movie with English titles/subtitles
    report.json            # Media validation and source/project/output hashes
    editorial.ass         # Generated compositor input
    project/              # Editable, frozen project with font and license
  render.log
  attempt.json
```

`factory status` returns `video` for the final captioned movie and `source_video`
for the original Cycles movie. A completion marker requires both media reports,
both movie hashes, the correct frozen project and complete video decoding. A
caption encoder failure cannot leave the raw render marked as a completed new
tour. Attempts without a completion seal remain available for diagnosis.

## The project-page film style (v2)

[`assets/robo_factory/film-project.json`](../../assets/robo_factory/film-project.json) is the
published film's project. Its schema `robofrontier.factory-editorial.v2` replaces `font` and
`font_license` with `fonts` (`display`, `mono`) and `font_licenses`, and uses a palette style:
sizes (`display_size`, `deck_size`, `label_size`, `caption_size`), margins, `panel_alpha`
(percent opacity), `ink`, `dim`, `accent`, `panel` and one color per family. Cue meaning:

- A **title** cue is a heading line and optional deck lines: a top-left card on a translucent
  panel. A heading that names a family takes that family's color bar.
- A **subtitle** cue that starts with a task identifier (`relay-a16-d1  ·  Level 1  ·  16 arms`)
  is a bottom-left label chip with the family's color square; any other subtitle is a caption.
- Panels are sized from the fonts' real advance widths. libass, like GDI, maps the font size
  to `usWinAscent + usWinDescent`, and matches `\fn` against the full name (such as
  `JetBrains Mono Medium`), so both are read from the font files.

Version 1 projects (`tour-project.json`) render as described above. Render a quick draft by
downscaling the raw movie first; the timeline and every check are unchanged.

## Revise text without rerendering Cycles

For a title, subtitle or style change, reuse the original uncaptioned movie:

```sh
.venv/bin/robofrontier factory edit-video \
  --project runs/factory/tour-project/project.json \
  --input /path/to/attempt/render/factory.mp4 \
  --output runs/factory/revised-titles
```

This command needs FFmpeg and the project, not Blender or the Factory data
download. It copies the editable project into a new output, verifies source and
input immutability, checks dimensions/frame rate/frame count, and fully decodes
the final movie. The original movie is retained. Output is H.264/yuv420p at CRF
18; input audio, if present and MP4-compatible, is copied. Existing output
directories are rejected. Use the raw Cycles movie as input to avoid burning
new captions over old captions.

This operation verifies media post-production only. It does not establish that
an arbitrary input movie depicts the project's declared scene, current physics,
correct task outcomes, or edited camera plan. Its report states that limitation.
It does not generate a Factory render-plan completion marker. Source-qualified
camera changes must go through `prepare` and `run`.

## Plans without a project

A desk-mode plan has no editorial project: each job completes on its raw video and gets no
captions. `status` works on any plan; `run` needs the plan's own source code, or a newly
prepared plan.
