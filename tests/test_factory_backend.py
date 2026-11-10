"""The legacy replay tool retains verification but cannot emit Classic factory video."""
import unittest

from scripts.replay_motion_in_factory import replay


class FactoryBackendTests(unittest.TestCase):
    def test_legacy_factory_video_requests_are_rejected_before_reading_inputs(self):
        with self.assertRaisesRegex(ValueError, 'Cycles'):
            replay('missing', 'missing', 'missing', render=True)


if __name__ == '__main__':
    unittest.main()
