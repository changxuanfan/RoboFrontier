import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import numpy as np

from scripts import render_policy_videos as script


class RenderPolicyVideosTests(unittest.TestCase):
    def test_profiles_of_one_batch_get_distinct_targets(self):
        a = script.target_for('/out', '/runs/batch/claude-opus/transport-a04-d1/private/outputs')
        b = script.target_for('/out', '/runs/batch/codex-gpt/transport-a04-d1/private/outputs')
        self.assertEqual(a, Path('/out/batch/claude-opus/transport-a04-d1'))
        self.assertNotEqual(a, b)

    def test_summary_reports_the_cut_that_was_rendered(self):
        def write_cut(path, recording, times, keep, extra):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(dict(kept=int(keep.sum()))))
            path.with_suffix('.npz').write_bytes(b'')
            return path
        def render(outputs, views, speed, edit, folder, timeline, fps):
            (folder/'manifest.json').write_text(json.dumps(dict(views={v: dict(decode_passed=True) for v in views})))
            for view in views:
                (folder/f'{view}.mp4').write_bytes(b'')
        keep = np.ones(100, bool)
        def refine(keep, *args):  # Every refinement drops 10 more source frames.
            keep = keep.copy()
            keep[np.flatnonzero(keep)[-10:]] = False
            return keep
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(script, 'MotionReader') as reader, \
                mock.patch.object(script.simple, 'policy_speedup', return_value=10.), \
                mock.patch.object(script, 'meaningful_keep', return_value=(np.arange(100.), keep, np.ones(5, bool))), \
                mock.patch.object(script, 'write_cut', side_effect=write_cut), \
                mock.patch.object(script.simple, 'render', side_effect=render), \
                mock.patch.object(script, 'visible', return_value=np.zeros(30, bool)), \
                mock.patch.object(script, 'longest_still_seconds', return_value=5.), \
                mock.patch.object(script, 'visible_frame_selection'), \
                mock.patch.object(script, 'refine_with_video', side_effect=refine):
            reader.return_value.meta = dict(sample_hz=30)
            summary = script.render_run(Path(root)/'outputs', Path(root)/'video')
            self.assertEqual(len(summary['passes']), script.PASSES)
            self.assertEqual(summary['final_kept_source_frames'], summary['passes'][-1]['kept_source_frames'])
            self.assertEqual(json.loads((Path(root)/'video/motion-cut.json').read_text())['kept'],
                             summary['final_kept_source_frames'])


if __name__ == '__main__':
    unittest.main()
