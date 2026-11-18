import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from roboteam.runtime.run import layout, segments


class EmptySegmentRestoreTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)
        (self.run / 'private/inputs').mkdir(parents=True)
        self.manifest = {**layout.manifest_record(), 'input_sha256': {}}
        self.save_manifest()
        self.pose = np.arange(9, dtype=float)

        class Reader:
            meta = {'frames': 1, 'case_id': 'fixture', 'source_scene_sha256': 'scene'}

            def selected_frames(inner, indices):
                for index in indices:
                    yield index, 12.5, self.pose

        self.reader = Reader()
        original = self.run / 'private/outputs/motion'
        original.mkdir(parents=True)
        (original / 'stream.json').write_text('{}')
        patcher = patch('roboteam.sim.motion_recording.MotionReader', return_value=self.reader)
        patcher.start()
        self.addCleanup(patcher.stop)

    def save_manifest(self):
        (self.run / 'private/inputs/manifest.json').write_text(json.dumps(self.manifest))

    def empty_segment(self, index, **changes):
        folder = segments.input_dir(self.run, index)
        folder.mkdir(parents=True)
        note = {
            'schema': segments.RESTORE_SCHEMA,
            'segment': index,
            'from_segment': index - 1,
            'source_frame': 0,
            'source_sim_s': 12.5,
            'source_scene_sha256': 'scene',
            'case_id': 'fixture',
            **changes,
        }
        (folder / 'restore-pose.json').write_text(json.dumps(note))
        np.save(folder / 'restore-pose.npy', self.pose, allow_pickle=False)
        for path in folder.iterdir():
            self.manifest['input_sha256'][str(path.relative_to(self.run))] = hashlib.sha256(
                path.read_bytes()
            ).hexdigest()
        self.save_manifest()
        return folder

    def test_empty_startup_segments_keep_the_verified_recorded_frame_without_creating_motion(self):
        self.empty_segment(1)
        self.empty_segment(2)
        reader, index, sim_s, pose = segments._last_frame(self.run, 2)
        self.assertIs(reader, self.reader)
        self.assertEqual((index, sim_s), (0, 12.5))
        np.testing.assert_array_equal(pose, self.pose)
        self.assertFalse((segments.output_dir(self.run, 2) / 'motion').exists())

    def test_changed_pose_or_a_bound_but_wrong_source_is_rejected(self):
        folder = self.empty_segment(1)
        np.save(folder / 'restore-pose.npy', self.pose + 1, allow_pickle=False)
        with self.assertRaisesRegex(ValueError, 'input changed'):
            segments._last_frame(self.run, 1)
        self.manifest['input_sha256'][str((folder / 'restore-pose.npy').relative_to(self.run))] = (
            hashlib.sha256((folder / 'restore-pose.npy').read_bytes()).hexdigest()
        )
        self.save_manifest()
        with self.assertRaisesRegex(ValueError, 'recorded source'):
            segments._last_frame(self.run, 1)

    def test_missing_restore_and_invalid_chain_do_not_skip_to_an_arbitrary_older_segment(self):
        self.assertIsNone(segments._last_frame(self.run, 1))
        self.empty_segment(1, from_segment=1)
        with self.assertRaisesRegex(ValueError, 'chain is invalid'):
            segments._last_frame(self.run, 1)


if __name__ == '__main__':
    unittest.main()
