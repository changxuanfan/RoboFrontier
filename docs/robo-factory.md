# Factory design, rendering and historical acceptance

For a new checkout, use the [unified Factory guide](factory.md). The native
[Linux/Slurm handoff](factory-server.md) documents `scripts.factory_server`.
Both freeze inputs from `configs/factory-assets.json`; the package uses Mosaic
R14. Policy assets and optional historical Factory playback data are separate.
New compressed recordings can be imported through the unified entry using their
own frozen scene and appearance events. Do not replace an old recording's physics
or colors with a newer task scene.

This page records visual design, lower-level rendering interfaces and dated
V9/V10 acceptance. Historical `outputs/` and `runs/` paths are local evidence
references, absent from a normal clone, and are not dependencies for a new
server. Historical render timings and devices are not current defaults or
hardware qualifications. The unified Linux default is Cycles OPTIX; native
macOS uses explicit METAL and CPU rendering must be selected explicitly.

## Layout and visual design

The Factory is 55 x 50 metres with four regions and 36 workstations. The build
configuration is `configs/backgrounds/robo_factory.json`; its historical layout
input is `configs/suites/frontier-current-oracle.json`. In the current layout
source, levels run from L1 to L3 from top to bottom in plan view, and workstation
sizes increase from left to right. Station labels sit above the actual desk
edge. Region labels are centered along the upper edge of each rectangle;
supply carts move clear of them and desk labels stay outside the tabletop's
plan projection. New layout source requires a new build: historical V10 scene
`outputs/robo-factory/v10-centered-labels/scene.xml` and old pointers do not
update themselves. The old static-image index is
`outputs/robo-factory/v10-centered-labels-review/README.md`.

The offline presentation model has no physical degrees of freedom or actuators.
[V7 acceptance](archive/history/robo-factory-v7-20261027.md) and the
[V6 design record](archive/history/robo-factory-before-integration-20261027.md) retain
their original scopes.

The design retains four walls, roof, structural beams, windows and doors, region
text, original task desks and camera capabilities. The north-wall ROBO FACTORY
lettering was removed. Transport uses blue-gray flooring, Mosaic gray-green,
Relay terracotta and Dial ochre. Region floors are flush and do not overlap;
cabinets and boundary lines share each region's palette. Gray cross aisles and
yellow safety lines connect the regions. Wooden tabletops, white arms, gray
structural elements and a painted-metal roof provide a consistent appearance.

Under-desk cabinets add labels, status lights and service coils while preserving
existing power and cable trays. Six rolling service/control racks occupy gaps,
and eight suspended tool-supply groups occupy corners. Racks avoid planned
station bounds with at least 0.4 m clearance. This is not certification against
all swept robot volumes. Mesh sharing, repeated materials/textures and static
batching are retained. A build uses assets inside its own output; source task
assets remain unchanged.

Fixed lighting and camera settings are in
`configs/backgrounds/robo_factory_lookdev.json` and
`configs/backgrounds/robo_factory_lookdev_camera.json`. Broad soft fill replaces
discrete pools of light. Low-angle warm sunlight enters actual window openings;
the exterior road was removed. Dark robot joints and shells, wooden task pieces
and printed tabletop elements have separately calibrated display materials.
These changes do not edit the source state.

The daytime exterior image was generated with the built-in image tool. Its
project asset is `assets/robo_factory/textures/exterior-daylight-v1.png`, with a
sibling `.prompt.txt` recording the prompt. Only the outdoor view uses this
image; the factory, robots and video are rendered from Blender geometry. Two
visual references and their prompts were retained locally under
`outputs/robo-factory/v8-study/references/`.

V10 retained 42 modeled light fixtures. Lighting uses broad diffuse ceiling
fill to avoid circular floor highlights, together with window-area lights,
low-angle sun and environment fill. Ceiling fill does not contribute specular
highlights. Cycles glass retains camera-ray reflection/transmission; shadow
rays use a thin-glass transmission approximation so sunlight passes through real
window openings. Tabletops and hard surfaces use flat normals, while robots
retain smooth shading. Incorrect smoothing must not make flat desks appear
wavy.

## Frozen sources, edits and independent loops

Historical V9/V10 bound each desk's scene, recording and edits through the then
current `benchmark/release.json`. The portable server handoff freezes
those inputs independently and does not depend on that file pointing into a
maintainer's Oracle cache.

The reviewed presentation speedups were Transport 20x, Mosaic 30x, Relay 20x and
Dial 10x. Output is 30 fps; original recordings were 60 Hz. Each desk independently
skips its reviewed unused intervals and loops from its original start after
completion. Every loop restores initial RGBA before applying the new cycle's
appearance events. All stations update before one Factory FK pass and one
render per output frame. The 2026-10-27 request for independent looping
superseded the older stop-after-all-finish presentation requirement.

The `robofrontier.station-edit.v2` review was retained under
`outputs/robo-factory/source-edits-v3-20261027/`. It reviews inactivity, jitter
and repeated passive oscillation over 2/8/32-second windows on top of historical
family edits. It protects directed slow movement, continuous rotation and source
context around actions, results, violations, failures, recovery and appearance
events. New edit tables bind selection, source stream and semantic-log hashes.
Original streams, edits and videos are not rewritten. Classification uses 10 Hz
review; source selection still uses original 60 Hz indices. Presentation frame
removal is not a contact-force measurement or physical acceptance result.

Stations undergo rigid translation and horizontal rotation. Robot and payload
scale is unchanged; playback performs no actions, IK or physics integration.
The historical Transport Oracle source was R13 and used a 0.5 display scale for
table openings. Its GPT R14 source already had half-size openings and used 1.0.
Display-only geometry edits are recorded separately from source collision
geometry, preventing the same reduction from being applied twice.

## Camera paths

The historical `camera-shots.json` begins with a six-second overview and a
six-second corner orbit, then visits Transport, Mosaic, Relay and Dial, with
L1/L2/L3 and workstation sizes within each family. The `orbit` camera defaults
to a gentle 60-degree interior arc; `--orbit-degrees 360` requests a full orbit.
Exports use a fixed 30 fps. Camera time is independent of each desk's source
clock. Fixed cameras and custom editing are supported.

Those camera paths were a filming basis; their dated acceptance did not include
a narrated, subtitled full presentation. The current
[editable English project](factory-editorial.md) now provides frozen camera
waypoints, SRT titles/subtitles, font/license and style, with verified CPU preview
and full historical-movie text processing. Full newly rendered current-source
movie acceptance remains separate. An existing historical MP4 alone does not
establish its scene identity or satisfy that delivery gate.

Production offline Factory rendering uses Cycles. The old Classic Factory-video
entry is retired; interactive inspection and simple policy observations still
use MuJoCo Classic. Task-object display materials have stronger chroma, while
source scenes, events and robot joints remain unchanged.

## Lower-level build, inspect and export

Use the unified or native handoff for new machines. The following interfaces
assume that matching local inputs already exist. `video` and `poses` require an
explicit `--release` with resolved paths for the selected scene. The batch's
`release.json` produced by `factory_server prepare` is one such input. Choose
new output directories; these examples do not bootstrap historical local paths.

```sh
.venv/bin/python -m scripts.factory build --output outputs/robo-factory/my-factory
.venv/bin/python -m scripts.factory video \
  --scene outputs/robo-factory/my-factory/scene.xml \
  --release RESOLVED_RELEASE_JSON --renderer cycles --camera orbit \
  --duration 8 --output outputs/robo-factory/my-cycles
```

`--scene` selects a scene, `--families` selects families and `--camera` accepts
`tour`, `orbit`, `desk-front` or a camera preset. The historical native workflow
used Cycles/Metal, `fast`, 64 samples, noise threshold 0.10, minimum samples 4,
adaptive sampling and GPU denoising. These are dated native settings; select the
device through the current unified configuration for portable operation.
`--samples`, `--noise-threshold` and `--min-samples` provide separate overrides.
CPU work handles source FK, files and scene updates. `--save-blend` preserves an
inspectable Blender scene. Install Blender and ffmpeg; the native Mac search
recognizes the application, or pass `--blender` explicitly.

Outputs include assets, poses, per-frame source mappings, PNG frames, MP4, logs
and a report. The workflow fully decodes the encoded video and checks frame
count and 30 fps. Intermediate animation PNGs are removed only after successful
encoding and decode/count checks; a failed export retains them. `--keep-frames`
retains the full sequence and `--no-encode` comparisons also retain frames.
Lossless PNG intermediates avoid an extra JPEG encoding stage; long-term video
storage uses MP4 plus source poses. `report.json` records removed counts and
bytes in `frame_storage`, and retained-image paths in
`views[].retained_file`. Playback fps is separate from rendering seconds/frame.

For a fixed desk-front view, the frozen task's `global` camera is placed in the
Factory using the station's rigid transform. Its original field of view is
preserved; the surrounding Factory and other stations remain visible:

```sh
.venv/bin/python -m scripts.factory video \
  --scene FACTORY_SCENE_XML --release RESOLVED_RELEASE_JSON \
  --camera desk-front --station transport-a04-d1 --duration 1 \
  --width 1920 --height 1080 --output outputs/robo-factory/my-desk-front
```

`poses` supports the same `--camera desk-front --station CASE_ID` selection.
A 2026-10-28 Transport A04-D1 test rendered ten consecutive 1080p frames with
64/0.10/4 sampling. The nine warm frames averaged 3.444 s/frame (0.290 fps),
P95 3.647 s; the first frame including preparation took 10.337 s. PNG writing
was included and encoding measured separately. That test retained three review
images; the current default removes animation PNGs after verification. All 36
source `global` cameras were confirmed present, but actual picture/FK checks in
that test covered A04-D1 only, without a per-desk occlusion qualification.
The then current `current.json.presentation.desk_front_preview` indexed the
video, images and receipt; raw evidence is under
`runs/engineering/factory-desk-front-10frames-20261028/`.

Reuse the same poses for sample-count comparisons by separating export steps:

```sh
.venv/bin/python -m scripts.export_factory_blender \
  --scene outputs/robo-factory/v9-workstations/scene.xml \
  --output outputs/robo-factory/my-blender
.venv/bin/python -m scripts.factory poses \
  --scene outputs/robo-factory/v9-workstations/scene.xml \
  --release RESOLVED_RELEASE_JSON --duration 8 --camera orbit \
  --output outputs/robo-factory/my-poses
/Applications/Blender.app/Contents/MacOS/Blender --background \
  --python-exit-code 1 --python scripts/render_factory_blender.py -- \
  --asset outputs/robo-factory/my-blender \
  --animation outputs/robo-factory/my-poses/animation.json \
  --output outputs/robo-factory/my-cycles --engine cycles \
  --device METAL --profile fast --samples 24
```

Keep asset/animation fixed and use separate outputs for comparisons.
`--benchmark-frames 3 --views interior_diagonal` samples cold/warm frames at a
fixed view. `--frame-indices 0 1 96 97 192 193 288 289 384 385 --no-encode`
compares ten identical animation states; the full camera path still determines
fixed LOD. `--metalrt ON` requests Metal hardware ray tracing.
`--png-compression 0` reduces lossless compression work at greater disk cost,
without changing pixels. Reports separate scene preparation, first frame,
warm mean/median/P95/slowest frame and encoding. Animation timing includes pose
updates and PNG writing. AGX measurements describe whole-machine utilization,
including desktop/other processes, rather than Blender-exclusive usage.

Fast mode uses three robot-appearance LOD levels, fixed by the nearest camera
position over the entire path to prevent popping. Original meshes remain
available and `--profile reference` disables LOD. Task fixtures, openings,
payloads, source trajectories and physics inputs are not simplified. Geometry
is merged per rigid body and shared with Geometry Nodes instances. Position and
orientation update in batches; color changes switch only the affected instance
materials. Instance clouds without material-index changes do not refresh static
meshes unnecessarily. Motion and source appearance events still update.
Color changes use cached material copies bound to mesh data; object-level
material overrides do not establish correct instance colors. Blender checks
inspect evaluated face materials, independent color changes, moved positions
and immediate reset. State and source mappings have hash checks; initial and
first/middle/last animation samples audit rigid transforms to approximately one
micrometre. This is a visualization export, not an Isaac/USD dynamics conversion.

## Historical V10 full-orbit acceptance

- Video: `outputs/robo-factory/v10-orbit16-cycles/factory.mp4`, 16 seconds,
  480 frames, 30 fps, 1920 x 1080 and a complete 360-degree orbit.
- Cycles Metal GPU, MetalRT ON, 24 samples, GPU denoising. All 36 station sources
  loop independently; source physics and actions are unchanged.
- Apple M5 Pro, 16-core GPU: 479 warm frames averaged 2.126 s/frame,
  P95 2.279 s. Scene preparation was 4.913 s, first-frame rendering 3.120 s,
  process start to first frame 8.290 s, encoding 5.568 s and total 1,037.374 s.
  Per-frame timings include updates, denoising and PNG; encoding is separate.
- The same ten frames comparing 64 to 24 samples plus update/write improvements
  decreased from 2.517 to 2.121 s/frame (15.72%), with mean SSIM 0.99694.
  The full 480-frame video was rendered once, without resizing or interpolation.
- Whole-machine AGX utilization averaged 94.79%, peaking at 100%, including
  desktop and other processes.
- Full decode, 480 PNGs, duration/fps/count, 480 source-pose hashes and
  first/middle/last FK passed at acceptance time.
- Receipts: `outputs/robo-factory/v10-orbit16-cycles/README.md` and
  `runs/engineering/factory-orbit360-20261027/final-validation.json`.

## Historical 64-sample preview and storage review

`outputs/robo-factory/v10-orbit4-cycles64/factory.mp4` contains the first four
seconds of the preceding 16-second trajectory: 120 frames, native 1080p,
GPU 64 samples and inherited adaptive threshold 0.15. Warm frames averaged
2.476 s/frame, P95 2.884 s. Full decode preceded removal of 117 PNGs. The
16-second video also had 477 PNGs removed. Each retained first/middle/last
lossless images, releasing approximately 4.94 GB in total. This dated
three-image retention differs from the current remove-all-animation-PNG default.

The direct-encoding experiment is under
`runs/engineering/factory-samples64-4s-20261027/`. On the same ten frames, the
PNG path averaged 2.539 s/frame and Blender's native FFmpeg path 2.441 s/frame,
a 3.83% reduction. Native encoding used CRF17 versus CRF18 for the original
path; the small test does not establish the same long-video improvement.
Source pixels and AgX were checked. Direct encoding remains experimental;
production keeps validated encode-then-cleanup. The directory's README and
`native17-comparison.json` record quality metrics and limitations.

## Historical V9 acceptance

- V9 contained 34,583 visual geoms and approximately 392 shared rigid meshes.
  Orbit LOD reduced about 43.9 million appearance triangles to 7.25 million.
- Both engines used identical 36-station poses, camera paths and source edits.
  Only GPU execution was tested.
- Final delivery was `v2`, correcting Geometry Nodes instance material
  propagation; older videos were retained as superseded.
- Cycles: `outputs/robo-factory/v9-orbit-cycles-v2/factory.mp4`.
  Eevee: `outputs/robo-factory/v9-orbit-eevee-v2/factory.mp4`. Their reports are
  the authoritative dated performance receipts.
- Both videos were eight seconds, 240 frames and 30 fps. Timing includes pose
  updates and PNG writes; encoding is separate.
- Apple M5 Pro 16-core GPU: Cycles 24 samples averaged 1.38 s/frame,
  P95 1.74 s; Eevee 4 samples averaged 1.43 s/frame, P95 1.56 s.
  Preparation was 4.37/4.58 s, first render 2.13/2.09 s and process start to
  first usable frame including updates 6.85/6.99 s. System shader caches
  remained populated. Whole-machine GPU utilization averaged about 93%/69%.
- Conservative boxes for the six added racks did not overlap source-task geom
  boxes at any of the 240 sampled frames. This is not continuous collision
  certification between frames.
- The clip contained 353 source Dial RGBA changes. Other families had none
  during that interval.
- Performance, geometry/appearance isolation and source-binding audits:
  `runs/engineering/factory-v9-20261027/`.
- 1,008 offline tests, evaluated Blender independent-color/immediate-reset
  checks, 217,184 protected historical files and 36 source bindings passed.
- Comparison images, a texture-packed Blender file and index:
  `outputs/robo-factory/v9-review/`.
- All 36 tasks were prepared again under
  `runs/policy/prepared-factory-v9-20261027/`, with zero model calls and no
  simulation start. Later execution-source changes require a new preparation;
  old prepared inputs remain retained.

## Historical cleanup and delivery pointers

`outputs/final/factory/` provided links to the then current top/side images and
orbit MP4. Its scene, Blender export, lighting configuration, 36 source streams
and v3 edits were retained. Earlier study renders and encoded PNG caches were
cleaned according to retention policy. Dated decode/frame-count receipts do not
prove those PNG caches still exist. Later independent render outputs were
outside that cleanup. A new machine should use the pinned portable bundle,
not attempt to resolve those maintainer-local delivery pointers.

## Static per-desk front and side views

For an already built scene, export Blender assets and desk cameras:

```sh
.venv/bin/python -m scripts.export_factory_blender --scene SCENE/scene.xml --output ASSET
.venv/bin/python -m scripts.factory_desk_cameras --scene SCENE/scene.xml --output desk-cameras.json
blender --background --python-exit-code 1 --python scripts/render_factory_blender.py -- \
  --asset ASSET --output DESK_OUTPUT --desk-cameras desk-cameras.json \
  --width 1280 --height 800 --samples 16 --profile fast
```

The default exports front and side perspective views of each desk inside the
Factory. Front follows the simple scene's `global` camera direction; side faces
the station's lateral axis. Station labels sit on the floor below desks. Front
framing includes the label with tighter margins to keep the desk large; side
prioritizes the equipment without requiring visible label text. Distance and
center adapt to each desk's initial geometry bounds for a 16:10 image.
`--views top` adds the older overhead view. These are static initial poses,
not coverage of every pose during execution.
