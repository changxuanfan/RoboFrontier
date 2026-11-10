"""A fast part of the release physics validation (scripts/validate_physics.py)."""
import unittest
from pathlib import Path

from scripts import validate_physics as vp

ASSETS = all((Path('benchmark')/family/case/'assets').is_dir() for family, case in
             (('transport', 'transport-a04-d1'), ('mosaic', 'mosaic-a04-6x12-d1'), ('relay', 'relay-a08-d2'),
              ('relay', 'relay-a08-d1'), ('dial', 'dial-best5-n04-d1')))


@unittest.skipUnless(ASSETS, 'Generated scene assets missing; run `python -m robofrontier.cli bootstrap`')
class ReleasePhysicsValidationTests(unittest.TestCase):
    def test_scenes_rest_without_drift_and_weights_stay_hung(self):
        for case in ('transport-a04-d1', 'mosaic-a04-6x12-d1', 'relay-a08-d2'):
            with self.subTest(case=case):
                result = vp.rest(case)
                self.assertTrue(result['passed'], result)
                self.assertLess(result['first_5s_mm'], .05, result)

    def test_a_held_cube_stays_put_and_a_released_cube_settles(self):
        result = vp.carry('transport-cube', ('joint1', .5))
        self.assertTrue(result['passed'], result)
        result = vp.place('transport-cube')
        self.assertTrue(result['passed'], result)

    def test_a_pushed_cube_stops_with_the_push(self):
        result = vp.push()
        self.assertTrue(result['passed'], result)

    def test_an_airborne_relay_handover_holds_the_timber(self):
        result = vp.relay(40.)
        self.assertTrue(result['passed'], result)

    def test_a_slowly_turned_dial_follows_the_hand(self):
        result = vp.dial('dial-best5-n04-d1', .3)
        self.assertTrue(result['passed'], result)


if __name__ == '__main__':
    unittest.main()
