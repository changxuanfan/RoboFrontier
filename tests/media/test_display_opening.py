"""Videos show the run's own table; only R13 Transport recordings show the opening halved (PR 7)."""
import unittest

from robofrontier.media.table_presentation import display_opening_scale


class DisplayOpeningTests(unittest.TestCase):
    def test_only_r13_transport_recordings_are_halved(self):
        self.assertEqual(display_opening_scale({'family': 'transport', 'scale': {'scene_revision': 13}}), .5)
        self.assertEqual(display_opening_scale({'family': 'transport', 'scale': {'scene_revision': 14}}), 1.)
        self.assertEqual(display_opening_scale({'family': 'mosaic', 'scale': {'scene_revision': 5}}), 1.)
        self.assertEqual(display_opening_scale(None), 1.)


if __name__ == '__main__':
    unittest.main()
