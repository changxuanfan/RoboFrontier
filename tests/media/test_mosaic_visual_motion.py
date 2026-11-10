import unittest

import numpy as np

from robofrontier.media.mosaic_visual_motion import VisibleMotionDetector, visible_frame_selection


class VisibleMotionTests(unittest.TestCase):
    def test_invisible_jitter_does_not_keep_a_seven_second_wait(self):
        detector = VisibleMotionDetector()
        active = []
        for i in range(210):
            frame = np.full((20, 20, 3), 80 + i % 2, dtype=np.uint8)
            active.append(detector.process(frame))
        self.assertEqual(int(visible_frame_selection(active).sum()), 2)

    def test_small_local_motion_is_kept(self):
        detector = VisibleMotionDetector()
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        self.assertFalse(detector.process(frame))
        frame[5:7, 5:7] = [30, 0, 0]
        self.assertTrue(detector.process(frame))

    def test_slow_visible_movement_accumulates_against_reference(self):
        detector = VisibleMotionDetector()
        frame = np.zeros((20, 20, 3), dtype=np.uint8)
        detector.process(frame)
        events = []
        for value in range(1, 30):
            frame[5:7, 5:7] = value
            events.append(detector.process(frame))
        self.assertEqual([i + 1 for i, event in enumerate(events) if event], [21])

    def test_all_visible_changes_and_boundary_frames_survive(self):
        active = np.zeros(300, dtype=bool)
        active[100:105] = True
        keep = visible_frame_selection(active)
        self.assertTrue(keep[99:106].all())
        self.assertTrue(keep[0] and keep[-1])
        self.assertFalse(keep[150])


if __name__ == '__main__':
    unittest.main()
