# Engineering command index

Use the unified `robofrontier` command for new experiments. Start with the root
[README](../README.md), [configuration guide](../docs/unified-cli.md), and
[component map](../docs/engines/README.md#component-map). The unified CLI selects a native
Codex or Claude runner; it does not turn one engine into the other.

For a lower-level module, run `.venv/bin/python -m scripts.MODULE` from the
repository root. Keep existing module names when reproducing historical evidence.

| Entry | Purpose and scope |
| --- | --- |
| `robofrontier config/plan/bootstrap/prepare` | Resolve public TOML settings, select current released tasks, restore pinned assets, and freeze new inputs without calling a model |
| `robofrontier doctor/preflight/run/status/stop` | Check local prerequisites; explicitly authorize provider checks; execute and monitor the selected native engine; request an orderly stop |
| `robofrontier collect/archive/extract` | Collect stopped native sessions and task evidence, create a verified deduplicated ZIP, and verify/extract it |
| `robofrontier container` | Build committed source and execute with persistent local Docker volumes |
| `robofrontier slurm-submit` | Freeze a submission and optionally queue node-local execution with verified stage-out |
| `robofrontier factory/oracle` | Replay frozen motion in Factory, or explicitly run privileged reference execution; neither is a policy benchmark launch |
| `benchmark models/plan/preflight/prepare/run/status/stop` | Native Codex interface retained for compatibility, with model selection, task filters, provider checks, concurrency, and START-based task limits |
| `claude_benchmark` | Native Claude draft, provider-check, and explicitly unqualified engineering interface; see the [Claude guide](../docs/engines/claude-code.md) |
| `benchmark_handoff doctor/init-env/assets/restore` | Inspect handoff prerequisites, create a private local environment file, and export/restore assets with SHA verification |
| `check_codex_cli` | Exercise the real Codex CLI's tools, images, and forks against a local Responses stub, without external model calls |
| `curate_repository` | Plan and verify data cleanup while protecting frozen source recordings |
| `tasks list/check/prepare/prepare-batch` | Audit current release selection and inputs, or use the retained lower-level preparation interface |
| `factory build/video/poses` | Low-level scene construction, public pose export, and Cycles video; requires an explicitly matching source |
| `factory_server setup/doctor/prepare/submit/run/status/import-motion/project/edit-video` | Restore independent R14 Factory data, prepare Linux render arrays, import motion, edit source-bound camera/subtitle projects and verify movies; see the [server guide](../docs/factory/server.md) and [editorial guide](../docs/factory/editorial.md) |
| `restore_scene_assets` | Restore ignored historical scene assets by their original SHA; refuse to overwrite drifted files |
| `check_harness` | Run the offline Python, JavaScript, documentation, and protocol regression inventory; historical fixtures may require separate assets |
| `check_oracle_preservation` | Check the preservation manifest and frozen Oracle source bindings |
| `run_analysis extract/compute/dial-turns/atomic-v2/session-archive` | Offline analysis of archived runs: timing, outcomes and atomic-step failure rates (version 2 step rules in `robofrontier/run_analysis/atomic_v2.py`); data root, run list and outputs are arguments, and no run data lives in the repository |
| `export_factory_blender`, `render_factory_blender` | Export and render Cycles scenes, reuse fixed-camera frames, and compare sampled source poses |
| `check_factory_blender_instances` | Check actual Blender instance geometry, motion, and independent color changes |
| `build_task_atlas` | Build, verify, or package the public 36-task visual atlas without policy inference |
| `site_media encode/montage/stills/explainer` | Encode task videos to 720p with posters and a verified manifest, build the family montages, README stills and the README benchmark figure |
| `site_film short/film/web/banner` | Cut the film and its short teaser from the raw Robo World render with motion graphics in the page's style, and derive the page hero loop, README teaser and banner |
| `site_data tasks/media/readme-gallery` | Generate the project page's task and video indexes and fill the README task gallery |

## Every script

Run a Python module with `.venv/bin/python -m scripts.NAME` from the repository root. Each purpose below is the script's own docstring.

### Benchmark engines and runs

Native Codex and Claude hosts, preparation and provider checks. `robofrontier` calls these. The Codex batch runner and Node host (`codex_policy_host.js`, `codex_rpc.js`, `codex_preflight.js`, `codex_initialize.js`) are in `robofrontier/codex/`.

| Script | Purpose |
| --- | --- |
| `benchmark.py` | Entry point for `python -m scripts.benchmark`; the Codex engine lives in `robofrontier/codex/`. |
| `benchmark_handoff.py` | Inspect a checkout and transfer only the runtime assets needed by policy tasks. |
| `check_codex_broker.py` | Exercise the installed Codex tool inventory, denials and roles against a LOCAL stub. |
| `check_codex_cli.py` | Exercise installed Codex RPC, images, dynamic tools and forks against a LOCAL stub. |
| `check_codex_snapshot.py` | Exercise snapshot forks and per-child prompts with a local Responses stub. |
| `claude_benchmark.py` | Claude planning, offline readiness, and unscored engineering runs. |
| `claude_blocked_precheck.py` | Paid, bounded Claude fork precheck at a blocked synthetic robot tool call. |
| `claude_offline_probe.py` | Exercise Claude CLI against local simulated model and robot servers. |
| `claude_precheck.py` | Real Claude precheck for one model profile under an explicit spend cap. |
| `claude_readiness.py` | Compare Claude precheck receipts with current configuration. |
| `create_pipeline_run.py` | Prepare a run only: no GUI, model calls, session creation or robot actions. |
| `luna_cpu.py` | Headless GPT-6 Luna benchmark entrypoint. |
| `meta_dispatcher.js` | Loaded by Meta into functions.exec. |
| `build_policy_env.py` | Build the read-only Python environment and offline package store for policy scripts, once per host. |
| `check_policy_env.py` | Before a batch, check an environment and each engine's sandbox with stub models; no provider is contacted. |
| `portable_benchmark.py` | Submit one benchmark batch without an LLM supervisor (macOS or Linux CPU). |
| `role_tools.js` | Thin local adapter for a single Agent-selected operation. |
| `tasks.py` | List released tasks, audit their inputs, or prepare isolated policy runs. |

### Evidence, reports and viewers

Read finished runs; none starts a model or physics.

| Script | Purpose |
| --- | --- |
| `archive_policy_batch.py` | Losslessly archive stopped benchmark evidence. |
| `check_transport_cylinder_stability.py` | Check passive cylinder drift in prepared Transport runs, without model calls. |
| `collect_benchmark_batch.py` | Collect stopped Codex/Claude benchmark evidence without inference or source edits. |
| `communication_report.py` | Summarize recorded multi-role communication without inferring model intent. |
| `export_run_report.py` | Read-only audit of a finished v3 run. |
| `summarize_oracle_batch.py` | Read-only summary of complete Oracle results, pilots and ongoing attempts. |
| `verify_evidence_replay.py` | Compare restored evidence, all motion states/events and sampled renders. |
| `view_policy_batch.py` | Loopback, read-only batch viewer using existing JSON and images only. |

### Repository, assets and checks

| Script | Purpose |
| --- | --- |
| `build_task_atlas.py` | Build or verify an offline English atlas of current public policy tasks. |
| `site_media.py` | Encode project page videos, family montages and README stills. |
| `site_film.py` | Cut the RoboFrontier film and its short teaser from the raw Robo World render, with motion graphics drawn in the project page's style. |
| `site_data.py` | Generate `site/data/` indexes and the README task gallery. |
| `check_harness.py` | Offline checks: fake services, robot/contact physics and real encoder recovery. |
| `check_oracle_preservation.py` | Verify protected historical bytes with inode-aware hashing. |
| `curate_repository.py` | Plan/apply user-requested generated-data cleanup, with pinned-source guards. |
| `fetch_robot.py` | Download only the official Panda model and its referenced meshes. |
| `install_historical_fixtures.py` | Install an explicitly supplied, checksum-pinned optional historical test bundle. |
| `restore_scene_assets.py` | Restore ignored workstation assets by their recorded SHA256. |

### Factory, replay and video

Offline presentation of recorded motion; never steps task physics.

| Script | Purpose |
| --- | --- |
| `analyze_relay_motion.py` | Analyze recorded scene motion once. |
| `build_factory_workstations.py` | Compose frozen workstations for display. |
| `check_factory_blender_instances.py` | Blender integration checks for rigid instancing and isolated appearance events. |
| `check_factory_layout.py` | Check the four 3x3 grids and caption clearance in a composed factory. |
| `check_mosaic_edit_transfer.py` | Validate source-bound edits and sample rigid factory poses, without physics. |
| `edit_dial_recording.py` | Build dial-owned progress-aware edits. |
| `edit_transport_recordings.py` | Analyze Transport recordings directly. |
| `export_factory_blender.py` | Export compiled visual geometry for offline Blender. |
| `export_factory_recorded_pose.py` | Export one stored-motion frame for an existing Blender factory asset. |
| `export_mosaic_edit_timelines.py` | Export portable exact-frame and full-recording edit maps for all nine cases. |
| `export_relay_edited.py` | Freeze reusable edited 60Hz tracks. |
| `factory.py` | Build, view, audit or render all released Oracle workstations in one factory. |
| `factory_blender_materials.py` | Explicit presentation materials. |
| `factory_blender_objects.py` | Retain exact rigid body frames with shared meshes and isolated material slots. |
| `factory_desk_cameras.py` | Place each source workstation's inspection cameras in the factory. |
| `factory_mesh_rotation.py` | Compare animated mesh rotations in the exported asset's coordinate frame. |
| `factory_primitive_uv.py` | Match primitive face texture coordinates to MuJoCo. |
| `factory_capsule.py` | Build capsule geometry from MuJoCo's radius and half-length. |
| `factory_server.py` | Portable factory data, render plans, local execution and Slurm submission. |
| `factory_video_frames.py` | Discard reproducible animation PNGs only after successful video validation. |
| `mosaic_motion_mask.py` | Read-only whole-scene motion detection for editing audited replay videos. |
| `mosaic_visual_motion.py` | Detect visible scene changes while ignoring the replay's clock overlay. |
| `pipeline_camera_panel.py` | Read-only configured-camera panel for an already-running shared world. |
| `prepare_factory_edits.py` | Produce a new audited presentation release without altering historical edits. |
| `promo_preview.py` | Generate sampled factory-tour poses. |
| `render_dial_oracle.py` | Render R11 BEST5 configurations from their source-bound 60 Hz record. |
| `render_edited_dial_batch.py` | Render selected closed dial episodes in both backgrounds with shared edits. |
| `render_factory_blender.py` | Run with Blender --background --python SCRIPT -- --asset DIR --output DIR. |
| `render_frontier_oracle.py` | Render stored physical configurations, including the shared chunked format. |
| `render_policy_videos.py` | Render policy runs at 720p with only meaningful motion, checked frame by frame; writes the motion-cut.json Factory import reads. |
| `replay_dial_motion.py` | Verify immutable Dial source motion and a shared edit in the factory. |
| `replay_motion_in_factory.py` | Replay immutable source states and optional scene-independent cuts in a factory. |
| `slurm_factory.sbatch` | Invoked by scripts.factory_server submit. |
| `view_robo_factory.py` | Inspect or export the static Robo Factory without task simulation. |

### Task builders, previews and viewers

Build or inspect released scenes; names are kept for provenance.

| Script | Purpose |
| --- | --- |
| `build_best5_dials.py` | Nine versioned six-mark BEST scenes. |
| `build_dial_policy_package.py` | Build or check the dial-only policy review. |
| `build_floating_dial_puzzle.py` | Generate a separate eight-arm/four-free-module puzzle. |
| `build_floating_spring_dial.py` | Build a two-arm MuJoCo preview with one movable spring-dial module. |
| `build_frontier_v2.py` | Build simple v2 scenes only. |
| `build_mosaic.py` | Generate the four-arm shared-table mosaic environment. |
| `build_mosaic_local_colors.py` | Prepare R14 local stock colours and visual previews, leaving R13 immutable. |
| `build_mosaic_pitch.py` | Build Mosaic R15 (71 mm grid pitch, 60 mm cubes) from R14 into `benchmark/mosaic/` and update the release entries. |
| `build_spring_crank_dial.py` | Build a preserved-geometry fixed-dial scene with red graspable crank handles. |
| `build_spring_dial.py` | Generate four passive spring dials and four Panda arms. |
| `build_transport_policy_package.py` | Build Transport R14 static scenes and reviewable family inputs. |
| `check_dial_family.py` | Audit the dial family and recorded source cursors, without a runtime or physics. |
| `check_mosaic_coverage_r12.py` | Exhaustive item/cell coverage with finite sampled geometric witnesses. |
| `export_frontier_contact_sheets.py` | Export current initial scenes only: 72 renders and four readable contact sheets. |
| `generate_background_textures.py` | Create the deterministic, visual-only textures for the complex background. |
| `generate_cube_transport.py` | Generate offline 3..12-arm scenes, order seeds, references and RGB previews. |
| `mosaic.py` | Check or export the current Mosaic delivery. |
| `preview_mosaic_local_colors.py` | Exact colour/layout diagrams and zero-step MuJoCo previews for Mosaic R14. |
| `preview_suite_rockets.py` | Draft pixel targets only: no MuJoCo scene, robot motion or benchmark run. |
| `revise_relay_scenes.py` | Build and show only the current Relay revision. |

### Oracle runs and engineering

Privileged reference execution and its diagnostics. A name with `oracle`, `commission` or `probe` is never a scored policy entry.

| Script | Purpose |
| --- | --- |
| `benchmark_mosaic_contact_screen.py` | Read-only differential timing of a contact-loop prefilter in a scratch mirror. |
| `check_transport_schedule.py` | Exact, unit-duration resource model. |
| `commission_best5_dials.py` | Bounded mechanical commissioning only. |
| `commission_transport_contacts.py` | Isolated contact-candidate commissioning. |
| `diagnose_mosaic_live_replan.py` | Read-only reproduction of an older owner's next matching/cache generation. |
| `diagnose_relay_descent.py` | Read-only FK reproduction of an interrupted Relay terminal guard. |
| `dispatch_mosaic_units.py` | Bounded process pool for independent mosaic physics units, not agents. |
| `execute_mosaic_flat_pose_correction.py` | Finite observed-state correction of a slightly yawed, seated planar cube. |
| `execute_mosaic_remaining_review.py` | Finish reviewed unique jobs through finite native commands in the same world. |
| `execute_mosaic_repair_route.py` | Owner-selected same-world recovery via available, previously checked ports. |
| `execute_mosaic_repair_transfer.py` | Owner-authored finite recovery: observed pickup -> real lift -> reviewed goal. |
| `park_mosaic_review_robot.py` | Actuate an empty reviewed arm back to its original parked joint reference. |
| `plan_mosaic_repair_pick.py` | Private read-only observed-state planning, emitting ordinary repair commands. |
| `probe_mosaic_pick_place.py` | Independent real-dynamics pickup -> arbitrary central placement units. |
| `run_best5_dial_batch.py` | Frozen BEST5 blind batch, one pilot then at most two independent worlds. |
| `run_blind_dial_oracle.py` | One frozen R11 BEST5 physical Oracle. |
| `run_mosaic_oracle.py` | Frozen Mosaic Oracle with bounded live review. |
| `run_relay_live_oracle.py` | One continuous committed Relay Oracle with a live, typed recovery boundary. |
| `run_relay_nine_oracles.py` | Frozen Relay case queue with explicit concurrency and no total deadlines. |
| `run_transport_full_oracle.py` | Frozen R13 full-order transport Oracle, with exclusive physics ownership. |
| `simulate_dial_alphabets.py` | BEST feedback across alphabet sizes, with exact posterior beliefs. |
| `simulate_dial_feedback.py` | Exhaustive discrete-logic comparison. |
| `summarize_mosaic_parallel_phase.py` | Read-only observed overlap and fixed-plan critical-path diagnostics. |
| `supervise_mosaic_dropped_payloads.py` | Continue explicitly reviewed Mosaic payload and near-goal placement errors. |
| `supervise_mosaic_normal_routes.py` | Continue known frozen NoHover errors, with opt-in small flat pose repairs. |
| `verify_floating_dial_oracle.py` | Oracle engineering trial: one Panda holds the blue handle while another turns the red dial. |
| `verify_frontier_v2.py` | V2 preflight by default. |
| `verify_transport_objects.py` | Engineering-only known-pose grasp/place fixtures. |
| `verify_transport_parallel_unit.py` | Two qualified disjoint local jobs, one canonical world, serial or batched. |

`create_pipeline_run` remains a Legacy interface for historical tasks and
explicit configurations. `meta_dispatcher.js` executes frozen Meta operations;
it is not an autonomous task-solving agent.

Family builders, audits, and Oracle scripts keep their historical names for
provenance, tests, and reproducibility. A name containing `oracle`, `commission`,
or `probe` does not make that script a scored policy entry or select the current
released task version.

`prepare_factory_edits` creates new source edit versions without modifying the
original recording or previous edits. Do not modify frozen inputs or delete
source evidence merely to make a preparation or archive check pass.
