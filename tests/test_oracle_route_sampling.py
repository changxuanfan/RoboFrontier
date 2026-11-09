"""A narrow forbidden interval between coarse samples must be caught by refinement."""
import unittest
from types import SimpleNamespace
from unittest.mock import Mock
import numpy as np
from robofrontier.suite.oracle import NoVerifiedJointIK,Trial,joint_edge_clear

class OracleRouteSamplingTests(unittest.TestCase):
    def test_finer_sampling_catches_between_sample_intersection(self):
        start=np.zeros(7);goal=np.array([.24,0,0,0,0,0,0])
        # Analogue of the observed collision at 82.5% of an admitted joint edge.
        clear=lambda q:not(.81<q[0]/.24<.84)
        self.assertTrue(joint_edge_clear(start,goal,clear))
        self.assertFalse(joint_edge_clear(start,goal,clear,.005))
    def test_invalid_resolution_rejected_and_fine_clear_edge_retained(self):
        for step in (0.,-.01,.03,float('nan')):
            with self.assertRaises(ValueError):joint_edge_clear(np.zeros(7),np.ones(7),lambda q:True,step)
        self.assertTrue(joint_edge_clear(np.zeros(7),np.ones(7),lambda q:True,.005))
    def test_empty_arm_without_joint_ik_takes_the_sampled_free_route(self):
        t=Trial.__new__(Trial);t.held={};t.move_free=Mock();t.execute=Mock()
        t.arms={'A':SimpleNamespace(site=0,qref=np.zeros(7),ik=SimpleNamespace(solve=lambda *a:(np.zeros(7),1.),pose=lambda q:(None,np.eye(3))))}
        t.home_q={'A':np.zeros(7)}
        t.data=SimpleNamespace(site_xmat=np.eye(3).reshape(1,9),site_xpos=np.zeros((1,3)))
        with self.assertRaises(NoVerifiedJointIK):t.pose_command('A',np.ones(3),np.eye(3),joints=True)
        t.move('A',np.ones(3),np.eye(3),label='approach')
        t.move_free.assert_called_once()
        t.execute.assert_not_called()

if __name__=='__main__':unittest.main()
