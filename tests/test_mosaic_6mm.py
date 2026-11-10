from types import SimpleNamespace
import unittest

import numpy as np
from robofrontier.tasks.evaluate_v2 import mosaic_candidates


class MosaicSixMmTests(unittest.TestCase):
    def candidate(self, offset, completion=None, color='cream', stable=True):
        task={'family':'mosaic', 'level':2, 'cube_size_m':.06,
              'completion':completion or {}, 'goals':[{'goal_id':'r6c8',
              'position_m':[0,0,.83], 'requires':{'color':'cream'}}]}
        mon=SimpleNamespace(task=task, names=['cube'], objects=[{'id':'cube','color':color}],
                            bodies=[0], m=None, d=SimpleNamespace(xmat=np.eye(3).ravel()[None,:]))
        return bool(mosaic_candidates(mon,np.array([[offset[0],offset[1],.83]]),[stable])[0,0])

    def test_versioned_threshold_and_legacy_default(self):
        rule={'xy_center_tolerance_m_inclusive':.006}
        self.assertFalse(self.candidate((.005077,0)))
        self.assertTrue(self.candidate((.005077,0),rule))
        self.assertTrue(self.candidate((.006,0),rule))
        self.assertFalse(self.candidate((.006001,0),rule))
        self.assertFalse(self.candidate((.0043,.0043),rule))

    def test_color_and_stability_remain_required(self):
        rule={'xy_center_tolerance_m_inclusive':.006}
        self.assertFalse(self.candidate((0,0),rule,color='navy'))
        self.assertFalse(self.candidate((0,0),rule,stable=False))

    def test_invalid_threshold_fails_closed(self):
        with self.assertRaises(ValueError):
            self.candidate((0,0),{'xy_center_tolerance_m_inclusive':float('nan')})


if __name__=='__main__': unittest.main()
