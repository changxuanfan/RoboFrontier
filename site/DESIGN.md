# RoboTeam project page: design

The project page is `site/index.html` with `assets/` and `data/`, deployed to GitHub Pages by
`.github/workflows/site.yml` on pushes to `main` that touch `site/`.

## Audience and promise

The page is a demo, not a paper. A visitor should see agents controlling many robot arms
within seconds, then be able to watch any run of any model, and only then read how the
benchmark works and what the results are.

## Page structure

One long page with a section rail and a lightbox video player.

| Section | Content | Data |
| --- | --- | --- |
| Hero | Name, paper title, one paragraph, buttons (Watch, Code, BibTeX) and four live runs, one per task type; then one spec strip | `media.json` |
| Watch | Video wall: one tab per video set (the six models, then the Oracle), task-type and front/side switches, 36 tiles per set. A tile shows whether the run completed and how long it took when the results are published | `media.json`, results |
| Tasks | Per task type: what the levels and team sizes change, on the 3 × 3 grid of start images (`assets/atlas/`) | `tasks.json` |
| How it works | Real time, camera images only, one robot tool, code tools; the four agent systems and the adaptive system's fork-and-return diagram | static |
| Results | Three findings and the board of all 14 conditions (tasks completed, darker for sooner) | results |
| Cite | BibTeX and links | static |

No result is written in the HTML. Missing data renders an explicit pending state, never a
placeholder value.

## Video sets

`SOURCES` in `assets/js/site.js` lists the sets on the wall, in order: `gpt-6.1-sol`,
`opus-5.5`, `kimi-k3.1-pro`, `qwen3.8-flash`, `deepseek-v4.1-flash`, `glm-5.3-flash` and
`oracle`. A set shows "soon" until `data/media.json` lists it under the same key. The hero and
the Tasks grid play the first published set that has the task, models before the Oracle.

Videos live in one public media repository, `RoboTeam-media`, served by its own GitHub Pages,
so the main repository stays small. Each set is one folder there, named by the set's key, and
every set uses the task ids as file names. `media.json` lists every file URL, size, duration
and SHA-256.

The playback speed of each Oracle video is in
[`data/oracle-videos.json`](data/oracle-videos.json).

## Results data

Results are not kept in this repository. The page fetches `results.json` from the media
repository (`RESULTS_URL` in `assets/js/site.js`):

```json
{"schema": "roboteam.site-results.v1",
 "conditions": [{"key": "adaptive", "label": "Adaptive", "group": "Agent systems · gpt-6.1-sol, Codex",
                 "completed": 0, "within": {"3": 0, "6": 0, "12": 0, "24": 0},
                 "median_hours": 0.0, "median_input_tokens_m": 0.0, "atomic_failure": 0.0}],
 "outcomes": {"gpt-6.1-sol": {"mosaic-large-l3": {"completed": false, "hours": 24.0}}}}
```

`conditions` are drawn in the order given, grouped by `group`. `outcomes` is keyed by video
set and task.

## Visual style

- Light by default, with a Theme button for dark (stored under the `localStorage` key
  `roboteam-theme`).
- Fonts: Space Grotesk (display), IBM Plex Sans (body), JetBrains Mono (labels and data).
- One color per task type: light theme Transport `#3b7fc4`, Mosaic `#3f9440`, Relay `#d65b3c`,
  Dial `#b98a12`; dark theme `#8fc1ec`, `#9fdc8c`, `#ff9f87`, `#f2d46b`.
- Motion respects `prefers-reduced-motion`; videos load lazily; controls work from the keyboard;
  nothing shifts the layout.

## Media pipeline

- `scripts/site/site_media.py`: `encode` (CPU libx264, CRF 28, `+faststart`, no audio, 720p task
  videos, JPEG posters), `montage`, `stills` and `explainer`. Each output is checked for
  duration and frame count.
- `scripts/site/site_data.py`: `tasks` (writes `data/tasks.json` from the release and the public
  tasks, with the playback speed of each Oracle video from `data/oracle-videos.json`), `media` (writes `data/media.json` from
  the encode manifests) and `readme-gallery`.

## Files

```text
site/
  index.html
  assets/css/site.css  assets/js/site.js
  assets/img/          favicon, social image
  assets/atlas/        task start images
  data/tasks.json      36 public task facts
  data/oracle-videos.json  the playback speed of each Oracle video
  data/media.json      every video URL by set, task and view
  DESIGN.md            this file
```

## Links and local preview

- `#task=<case>[&view=side][&source=<set>]` opens one run.
- Preview with `python3 -m http.server -d site 8791`. Locally encoded media go in the ignored
  `site/_media/`, with `media.json` pointing at `_media/<set>/`.
- `?fixture=<file>` loads a results file from the ignored `site/_dev/`. Never publish a fixture.
