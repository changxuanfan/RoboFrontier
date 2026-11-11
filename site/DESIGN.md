# RoboFrontier project page and README: design

The project page is `site/index.html` with `assets/` and `data/`, deployed to GitHub Pages by
`.github/workflows/site.yml` on pushes to `main` that touch `site/`.

## Audience and promise

A visitor should understand in 30 seconds what RoboFrontier is (multimodal agents controlling
up to 16 robot arms in Robo World, one physical simulation), see it working and find the
headline result. A researcher should then be able to drill into every task, every video and
every metric.

## Page structure

One long page with a chapter rail and a lightbox video player.

| Section | Content | Data |
| --- | --- | --- |
| Hero | Title, the question, buttons (Code, Film, Task data, BibTeX), the Robo World hero loop, one spec strip (36 tasks, 4 families, 4–16 arms, 3 levels, 24 h per run) | `assets/video/hero.mp4` |
| 01 Overview | Agents, the one robot tool, Robo World; the shared contract | static |
| 02 Benchmark | Family cards; per-family explainer of levels × team sizes from the task initial states (`assets/atlas/`); the Robo World map drawn from `tasks.json`; the adaptive protocol diagram | `tasks.json` |
| 03 Videos | Video wall: source tabs (Oracle, then each model), family and front/side switches; each Oracle video states its provenance | `media.json` |
| 04 Results | Failures per model, completion over time, tokens over time, metric definitions | `results.json` |
| 05 Studies | Skills (with and without `skills.md`), communication (single, controller-worker, worker-worker, adaptive), cameras (own arms vs every camera) | `results.json` |
| 06 Cite | BibTeX | static |

No number is hard-coded in HTML. Missing data renders an explicit "pending" state or an empty
chart frame, never a placeholder value.

## Visual style

- A white paper page, light by default, with a Theme button for dark (stored under the
  `localStorage` key `rf-theme`).
- Fonts: Space Grotesk (display, as in the film titles), IBM Plex Sans (body), JetBrains Mono
  (labels).
- Signature elements: the Robo World map (`plan()` in `assets/js/site.js`), floor-signage plates
  as section labels and the one spec strip.
- Family colors: light theme Transport `#3b7fc4`, Mosaic `#3f9440`, Relay `#d65b3c`, Dial
  `#b98a12`; dark theme `#8fc1ec`, `#9fdc8c`, `#ff9f87`, `#f2d46b`.
- Motion respects `prefers-reduced-motion`; videos load lazily; controls work from the keyboard;
  nothing shifts the layout.

## README

GitHub plays inline video only from uploaded attachments (`github.com/user-attachments/...`),
so every inline video is an attachment.

1. `docs/media/readme/banner.png`, title, paper title, links and family-colored badges, then
   `docs/media/readme/teaser.webp`, an animated image linking to the film (GitHub never
   autoplays video).
2. What it is, with `docs/media/readme/benchmark.jpg` (initial states at Levels 1–3).
3. One inline montage per family between `<!-- media:* -->` markers: its nine Oracle tasks
   in a 3 × 3 grid (rows are levels, columns team sizes), 1080p, each under 10 MB.
4. A 36-task gallery linking to page deep links `#task=<id>`.
5. Quick start, repository map, citation, license. No results table.

The Oracle provenance (which runs were operator-assisted, which scene revision each was
recorded on, that they are not model results) is stated wherever Oracle videos appear; the
facts are in the [Oracle guide](../docs/oracle/README.md#published-reference-videos).

## Media pipeline and hosting

- `scripts/site_media.py`: `encode` (CPU libx264, CRF 28, `+faststart`, no audio, 720p task
  videos, JPEG posters), `montage`, `stills` and `explainer`. Each output is checked for
  duration and frame count.
- `scripts/site_film.py`: `short`, `film`, `web` (hero MP4 and teaser WebP) and `banner`, drawn
  over a raw Robo World render; `assets/robo_factory/film-project.json` holds the film's titles.
- `scripts/site_data.py`: `tasks` (writes `data/tasks.json` from the release and the public
  tasks, including each Oracle row's provenance), `media` (writes `data/media.json` from the
  encode manifests) and `readme-gallery`.
- Videos live in one public media repository per set, served by its own GitHub Pages
  (`RoboFrontier-media-oracle`; one `RoboFrontier-media-<model>` per model), so the main
  repository stays small. `media.json` lists every file URL, size, duration and SHA-256.
  Model sets use the same keys as the Oracle set.

## Results data

`data/results.json` (schema `robofrontier.site-results.v1`) holds one row per run and is empty
until runs are exported; no script in the repository writes it yet. The page computes every
aggregate, so one file serves Results and Studies. Fields the page reads:

```json
{"schema": "robofrontier.site-results.v1",
 "runs": [{"model": "...", "model_label": "...", "engine": "codex", "topology": "adaptive",
           "skills": true, "camera_access": "all", "case": "mosaic-a08-12x24-d3",
           "success": false, "progress": 0.41, "wall_s": 86400,
           "failed_actions": 0, "retries": 0, "tokens_in": 0, "tokens_out": 0,
           "collisions": 0, "messages": 0, "parallel_efficiency": 0.0,
           "progress_curve": [[0, 0.0]], "completion_curve": [[0, 0.0]],
           "token_curve": [[0, 0]]}]}
```

`topology` is one of `single`, `controller-worker`, `worker-worker`, `adaptive`;
`camera_access` is `ego` or `all`.

## Files

```text
site/
  index.html
  assets/css/site.css  assets/js/site.js
  assets/img/          favicon, posters, social image
  assets/atlas/        task initial-state images
  assets/video/        hero loop
  data/tasks.json      36 public task facts
  data/media.json      every video URL by set, task and view
  data/results.json    benchmark results
  DESIGN.md            this file
docs/media/readme/     README banner, teaser, benchmark image, task stills
```

## Links and local preview

- `#film` opens the film; `#task=<case>[&view=side][&source=<set>]` opens one run.
- Preview with `python3 -m http.server -d site 8765`. Locally encoded media go in the ignored
  `site/_media/`, with `media.json` pointing at `_media/<set>/`.
- `?fixture=<file>` loads a results file from the ignored `site/_dev/` to test charts. Never
  publish a fixture.
