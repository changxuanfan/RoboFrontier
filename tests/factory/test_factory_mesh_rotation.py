import unittest
import numpy as np
from robofrontier.factory.blender.factory_mesh_rotation import asset_frame_rotation

class MeshRotationChecks(unittest.TestCase):
    def test_cross_platform_mesh_axis_flip_is_compared_in_asset_frame(self):
        local=np.array([[0,-.70710678118655,-.70710678118655],[0,.70710678118655,-.70710678118655],[1,0,0]])
        recorded=local@np.diag([1,-1,-1])
        actual,adjusted=asset_frame_rotation(7,np.eye(3),local,recorded)
        self.assertTrue(adjusted)
        np.testing.assert_allclose(actual,local,atol=1e-6)
    def test_non_mesh_or_arbitrary_rotation_is_not_hidden(self):
        local=np.eye(3);flip=np.diag([1,-1,-1])
        self.assertFalse(asset_frame_rotation(6,np.eye(3),local,flip)[1])
        angle=.25;arbitrary=np.array([[np.cos(angle),-np.sin(angle),0],[np.sin(angle),np.cos(angle),0],[0,0,1]])
        self.assertFalse(asset_frame_rotation(7,np.eye(3),local,arbitrary)[1])
