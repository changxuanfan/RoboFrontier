import json
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np

from robofrontier.motion_recording import MotionReader, MotionWriter
from robofrontier.task_families import ROOT, RELEASE, resolve_case
from robofrontier.workstation import Workstation
from scripts import render_frontier_oracle as video


class PolicyVideoTests(unittest.TestCase):
    """A policy run's outputs render with stationary intervals cut at the family speedup."""

    def make_run(self, root):
        source = ROOT/resolve_case('transport-a04-d1')[2]['directory']
        world = Workstation(source)
        outputs = root/'private/outputs'; inputs = root/'private/inputs'
        outputs.mkdir(parents=True); inputs.mkdir(parents=True)
        writer = MotionWriter(outputs/'motion', source, world.model, world.data, hz=30, chunk_seconds=1)
        joint = world.model.joint('A_joint1').qposadr[0]
        start = float(world.data.qpos[joint])
        # 4 s: still, 1 s of visible jitter (0.02 rad, no net turn), 1 s of a directed turn, still.
        for step in range(1, 2001):
            world.data.time = step*.002
            if 500 < step <= 1000:
                world.data.qpos[joint] = start + .02*np.sin(step*.3)
            elif 1000 < step <= 1500:
                world.data.qpos[joint] = start + (step-1000)*.0005
            writer.capture(world.data)
        writer.close()
        (outputs/'evaluation.json').write_text(json.dumps(dict(task_success=False, matched_goals=1, total_goals=9)))
        (inputs/'task.json').write_text(json.dumps(dict(family='transport')))
        shutil.copyfile(ROOT/RELEASE, inputs/'family-release.json')
        return outputs

    def test_stationary_intervals_are_cut_and_the_family_speedup_is_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            outputs = self.make_run(Path(temporary))
            report, scene = video.trial_report(outputs)
            self.assertTrue(report['policy_run'])
            self.assertEqual(scene, outputs/'motion/source/scene.xml')
            self.assertEqual(video.policy_speedup(outputs), 20.)
            cut = json.loads(video.stationary_cut(outputs/'motion', Path(temporary)/'cut').read_text())
            reader = MotionReader(outputs/'motion')
            with np.load(Path(temporary)/'cut/stationary-cut.npz') as arrays:
                keep, times = arrays['keep'], arrays['source_time_s']
            self.assertEqual(len(keep), reader.meta['frames'])
            self.assertTrue(keep[0] and keep[-1])
            directed = (times > 2.05) & (times < 2.95)
            self.assertTrue(keep[directed].all())
            # Still time and jitter, however visible, are both cut.
            still = (times > .1) & (times < .4) | (times > 1.1) & (times < 1.4) | (times > 3.6) & (times < 3.9)
            self.assertFalse(keep[still].any())
            self.assertLess(cut['kept_source_frames'], cut['source_frames'])

    def test_a_dropped_video_frame_removes_the_states_it_stood_for(self):
        from robofrontier.motion_cut import refine_with_video
        from robofrontier.motion_timeline import sample_timeline
        keep = np.ones(600, dtype=bool)
        selected = sample_timeline(keep, 30, 30, 30)
        video_keep = np.ones(len(selected), dtype=bool); video_keep[5:8] = False
        refined = refine_with_video(keep, 30, 30, 30, video_keep)
        self.assertTrue(refined[0] and refined[-1])
        self.assertFalse(refined[selected[5]:selected[7]+1].any())
        self.assertTrue(refined[selected[4]] and refined[selected[8]])
        self.assertEqual(len(sample_timeline(refined, 30, 30, 30)), len(selected)-3)

    @unittest.skipUnless(shutil.which('ffmpeg'), 'ffmpeg is required to encode')
    def test_a_policy_run_renders_a_decodable_cut_video(self):
        with tempfile.TemporaryDirectory() as temporary:
            outputs = self.make_run(Path(temporary))
            target = Path(temporary)/'video'
            video.render(outputs, views=('global',), output=target)
            manifest = json.loads((target/'manifest.json').read_text())
            self.assertEqual(manifest['speedup'], 20.)
            self.assertTrue(manifest['views']['global']['decode_passed'])
            self.assertEqual(manifest['timeline'], str((target/'stationary-cut.json').resolve()))


if __name__ == '__main__':
    unittest.main()
