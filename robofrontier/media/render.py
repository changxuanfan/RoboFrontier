"""Render policy runs on the simple background with only meaningful motion.

For each run's private/outputs:
1. cut the recording to meaningful motion (robofrontier.media.motion_cut);
2. render that cut at 720p and the family speedup;
3. drop every frame in which no view visibly changes, map the drops back to the
   recording's states, and render again, until no still stretch is longer than
   two frames (at most four passes).
The final cut, motion-cut.json, is what Factory import reads (--timeline), so
both backgrounds show the same states. The recording is never changed.
"""
import argparse
import json
from pathlib import Path
import shutil

import numpy as np

from robofrontier.media.motion_cut import meaningful_keep, refine_with_video, write_cut
from robofrontier.media.motion_recording import MotionReader
from robofrontier.runtime.setup import write_json
from robofrontier.media import render_frontier_oracle as simple
from robofrontier.media.mosaic_visual_motion import longest_still_seconds, visible_frame_selection, visual_mask

VIEWS = ('global', 'global_rear')
FPS = 30.
MAX_STILL_FRAMES = 2
PASSES = 4


def visible(folder, views=VIEWS):
    """Frames in which any view changes visibly, ignoring the caption band."""
    return np.logical_or.reduce([visual_mask(folder/f'{view}.mp4', overlay_height=80, width=640, height=320)
                                 for view in views])


def render_run(outputs, target, views=VIEWS):
    outputs, target = Path(outputs).resolve(), Path(target)
    if target.exists():
        raise FileExistsError(target)
    recording = outputs/'motion'
    hz = MotionReader(recording).meta['sample_hz']
    speed = simple.policy_speedup(outputs)
    times, keep, moving = meaningful_keep(recording)
    passes = []
    for number in range(1, PASSES+1):
        folder = target/f'pass-{number}'
        cut = write_cut(folder/'motion-cut.json', recording, times, keep,
                        dict(pass_number=number, moving_windows=int(moving.sum()), windows=len(moving)))
        simple.render(outputs, views, speed, None, folder, timeline=cut, fps=FPS)
        active = visible(folder, views)
        still = longest_still_seconds(active, FPS)
        passes.append(dict(pass_number=number, kept_source_frames=int(keep.sum()), video_frames=len(active),
                           visibly_changing_frames=int(active.sum()), longest_still_s=still))
        if still*FPS <= MAX_STILL_FRAMES+1e-9 or number == PASSES:
            break  # The last pass is final: never report a refinement that was not rendered.
        keep = refine_with_video(keep, hz, speed, FPS, visible_frame_selection(active))
    final = target/f'pass-{number}'
    for earlier in range(1, number):
        for view in views:
            (target/f'pass-{earlier}'/f'{view}.mp4').unlink()
    shutil.copyfile(final/'motion-cut.json', target/'motion-cut.json')
    shutil.copyfile(final/'motion-cut.npz', target/'motion-cut.npz')
    manifest = json.loads((final/'manifest.json').read_text())
    summary = dict(schema='robofrontier.policy-video.v1', outputs=str(outputs), speedup=speed, fps=FPS,
                   resolution=[1280, 720], source_frames=len(times), moving_windows=int(moving.sum()),
                   final_kept_source_frames=int(keep.sum()), passes=passes, final=str(final),
                   timeline=str((target/'motion-cut.json').resolve()),
                   video_seconds=passes[-1]['video_frames']/FPS, longest_still_s=passes[-1]['longest_still_s'],
                   no_still_stretch_over_frames=MAX_STILL_FRAMES if passes[-1]['longest_still_s']*FPS <= MAX_STILL_FRAMES+1e-9 else None,
                   decode_passed=all(view['decode_passed'] for view in manifest['views'].values()))
    write_json(target/'summary.json', summary)
    return summary


def target_for(output, outputs):
    """<output>/<batch>/<profile>/<case> for a run's private/outputs: profiles of one batch never collide."""
    run = Path(outputs).resolve().parents[1]
    return Path(output)/run.parent.parent.name/run.parent.name/run.name


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('outputs', type=Path, nargs='+', help="Runs' private/outputs folders")
    parser.add_argument('--output', type=Path, required=True, help='One folder per run is created inside')
    args = parser.parse_args()
    for outputs in args.outputs:
        run = outputs.resolve().parents[1]
        result = render_run(outputs, target_for(args.output, outputs))
        print(json.dumps(dict(run=str(run), video_seconds=result['video_seconds'], longest_still_s=result['longest_still_s'],
                              passes=len(result['passes']), decode_passed=result['decode_passed'])), flush=True)
