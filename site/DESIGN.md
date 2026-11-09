# RoboFrontier project page and README: design plan

Status: direction A (Control room) chosen on 2026-11-05 and implemented in `index.html`,
`assets/` and `data/`. Replaces the task-atlas page style entirely.

## Audience and promise

A visitor should understand in 30 seconds what RoboFrontier is (multimodal agents
controlling up to 16 robot arms in one physical world), see it working, and find
the headline result. A researcher should then be able to drill into every task,
every video and every metric.

## Project page: information architecture

One long page with a sticky chapter rail, plus a lightbox video player. Five chapters:

| # | Chapter | Content | Data source |
| --- | --- | --- | --- |
| 0 | Hero | Full-bleed muted loop cut from the 3.5 min promo; title, one-line claim; buttons: Watch film, Paper, Code, Data; four counters (36 tasks, 4 families, up to 16 arms, N models) | `media.json` |
| 1 | Benchmark | Four families as large cards (hover/scroll plays the Oracle clip); the 3 x 3 grid of scale x difficulty per family; what the policy sees and does (tools, cameras, rules); the adaptive protocol as an animated diagram (Controller spawns and retires delegates); how scoring works (terminal outcome, process events) | `tasks.json` (from the task atlas) |
| 2 | Watch | Video wall: family tabs, a 3 x 3 grid per family, source switch (Oracle / each model), front/side toggle, lightbox with task facts. Sources that are not rendered yet show "coming soon" | `media.json` |
| 3 | Results | Leaderboard of all models on the adaptive protocol: completion per family/level, then failures and failure rate, retries and retry rate, wall/simulation time, input/output tokens, collisions, parallel efficiency. Metric switcher, sortable table, family x level heatmap per model | `results.json` |
| 4 | Analysis | (a) Multi-agent communication: Single vs Controller-Worker vs Worker-Worker vs Adaptive (GPT only): success, time, tokens, parallelism, collisions, message volume and an animated message-flow view. (b) Skills: runs that write `skills.md` vs not: progress-over-time curves, late-run retry counts. (c) Parallel efficiency: concurrency timelines | `results.json` |
| 5 | Footer | BibTeX, license (code MIT, data/media CC BY 4.0), links | static |

Multi-agent communication is chapter 4a with its own sub-navigation and a
deep link (`#communication`). A separate page is not needed now; the chapter can be
promoted to `communication.html` later without changing data.

No number is ever hard-coded in HTML. Missing data renders an explicit
"pending" state, never a placeholder value.

## README: a static project page

GitHub strips `<video>` tags except for uploaded attachments
(`github.com/user-attachments/...`, up to 100 MB with Pro), so every inline video is
an attachment uploaded through the GitHub web editor.

1. Title, one-line claim, badges (project page, paper, license).
2. **Promo film** inline (1080p, about 25-30 MB, H.264, faststart).
3. **Four family montages** inline: one 1920 x 1080 video per family, a 3 x 3
   grid of its nine Oracle tasks (rows = difficulty, columns = scale), each tile
   720p-sourced, labeled, time-aligned and sped up. Four videos show all 36 tasks.
4. A 36-cell poster table (one row per family) linking each task to its
   full-length 720p video on the project page.
5. When model videos exist: one montage per model in a collapsible `<details>`.
6. What the agents do (short), the four topologies (one diagram), quick start,
   repository map, citation, license. No benchmark result tables (those live on
   the project page; the README links to them).

## Media pipeline and hosting

- Encoding: CPU libx264, preset slow, CRF 28, `-movflags +faststart`, no audio,
  720p for task videos, 1080p for the promo and montages; JPEG posters at 1280 px.
  Verify each output (duration, frames, SSIM against source on samples).
- Hosting: a public media repository per video set, served by its own GitHub
  Pages (`RoboFrontier-media-oracle`, later `RoboFrontier-media-<model>`), so the
  main repository stays small and each site stays under the 1 GB Pages limit.
  `media.json` in the main site lists every file URL, size, duration and SHA-256.
- Oracle sources: Transport/Relay L1-L2 `server-l12-20261028`, all L3
  `server-l3-429372-429373` (Transport, Relay), Mosaic `server-mosaic-r14-427182`,
  Dial `dial-corrected-429851` (supersedes earlier Dial renders). 36 tasks x front/side.
- Model sources: simple-background renders now; Factory renders replace them later
  under the same `media.json` keys.

## Results pipeline

`scripts/site/export_results.py` reads collected run exports (batch `evaluation.json`,
host metrics, runtime events) and writes `site/data/results.json`:

```json
{"schema": "robofrontier.site-results.v1", "generated_at": "...",
 "runs": [{"model": "gpt-6.1-sol", "engine": "codex", "topology": "adaptive",
           "skills": true, "case": "mosaic-a08-12x24-d3",
           "success": false, "progress": 0.41, "wall_s": 86400,
           "actions": 0, "failed_actions": 0, "retries": 0,
           "tokens_in": 0, "tokens_out": 0, "collisions": 0,
           "messages": 0, "delegations": 0, "peak_parallel_arms": 0,
           "progress_curve": [[0, 0.0]]}]}
```

Aggregates are computed in the page, so the same file serves results and analysis.

## File layout

```text
site/                    project page source, deployed by GitHub Actions to Pages
  index.html
  assets/css/ assets/js/ assets/img/   (posters only; no videos)
  data/tasks.json        36 public task facts (generated from the task atlas)
  data/media.json        every video URL by set, task and view
  data/results.json      generated benchmark results
  DESIGN.md              this plan
scripts/site/            encode_videos.py, make_montage.py, export_results.py, build_tasks.py
docs/media/              README stills (posters for the 36-cell table)
```

`docs/task-atlas` and `web/task-atlas` are retired once the Benchmark chapter covers
them (the downloadable atlas ZIP stays in its release).

## Links and local preview

- `#film` opens the film; `#task=<case>[&view=side][&source=<set>]` opens one run. The README
  gallery links every thumbnail this way.
- Preview: `python3 -m http.server -d site 8765`. Locally encoded media lives in the ignored
  `site/_media/`; `media.json` then points at `_media/<set>/`.
- `?fixture=<file>` loads a results file from the ignored `site/_dev/` to test charts. Never
  publish a fixture.

## Visual direction

Three directions were prototyped in `site/_directions/` (ignored, not deployed); A was chosen:

- **A: Control room.** Near-black, cinematic full-bleed video, monospace telemetry,
  one electric accent, live counters and scan lines.
- **B: Editorial lab.** White paper, very large serif display type, black ink, one
  saturated accent; magazine pacing with scroll-driven reveals.
- **C: Factory floor.** Warm concrete and safety yellow from the Factory renders,
  condensed grotesk, blueprint lines and hazard stripes.

All three: motion that respects `prefers-reduced-motion`, lazy video loading,
light/dark readability, keyboard-accessible controls, no layout shift.
