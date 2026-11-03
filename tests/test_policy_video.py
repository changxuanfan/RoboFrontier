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
        start = float(world.data.qpos[0])
        for step in range(1, 1501):  # 3 s: still, moving from 1 s to 2 s, still
            world.data.time = step*.002
            if 500 < step <= 1000:
                world.data.qpos[0] = start + (step-500)*.0005
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
            cut = json.loads(video.stationary_cut(outputs, Path(temporary)/'cut').read_text())
            reader = MotionReader(outputs/'motion')
            with np.load(Path(temporary)/'cut/stationary-cut.npz') as arrays:
                keep, times = arrays['keep'], arrays['source_time_s']
            self.assertEqual(len(keep), reader.meta['frames'])
            self.assertTrue(keep[0] and keep[-1])
            moving = (times > 1.05) & (times < 1.95)
            self.assertTrue(keep[moving].all())
            still = (times > .1) & (times < .4) | (times > 2.6) & (times < 2.9)
            self.assertFalse(keep[still].any())
            self.assertLess(cut['kept_source_frames'], cut['source_frames'])

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
