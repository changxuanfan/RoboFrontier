"""Physical oracle regressions, separate from complete benchmark witnesses."""
import tempfile,unittest
from pathlib import Path
import numpy as np
import mujoco
from robofrontier.oracle.trial import Trial
from robofrontier.oracle.geometry import ROOT,catalog,case_directory,rz

def fixture():return case_directory(next(c for c in catalog()['cases'] if c['id']=='transport-a04-d2'))

class SuiteOracleContactTests(unittest.TestCase):
    def test_grasp_proximity_tolerance_handles_a_positive_gap_without_changing_physics(self):
        with tempfile.TemporaryDirectory() as temp:
            t=Trial(fixture(),Path(temp)/'trial',frames=False)
            try:
                arm=t.arms['A'];origin=t.data.body('A_item1').xpos.copy();rotation=np.array([[0,1,0],[1,0,0],[0,0,-1.]])
                q=t.screen_ik('A',origin+[0,0,.006],rotation);self.assertIsNotNone(q)
                t.data.qpos[arm.qids]=q
                for suffix in ('finger_joint1','finger_joint2'):t.data.joint('A_'+suffix).qpos[0]=.02
                for gap,expected in ((.0001,True),(.0004,False)):
                    t.data.joint('A_item1_free').qpos[:3]=origin+rotation[:,1]*gap;mujoco.mj_forward(t.model,t.data)
                    before=t.data.qpos.copy();control=t.data.ctrl.copy();margin=t.model.geom_margin.copy()
                    self.assertEqual('A' in t.monitor.bilateral(t.monitor.geoms['A_item1']),expected)
                    np.testing.assert_array_equal(t.data.qpos,before);np.testing.assert_array_equal(t.data.ctrl,control);np.testing.assert_array_equal(t.model.geom_margin,margin)
            finally:t.close({'passed':False,'scope':'Contact measurement regression only'})

    def test_quarter_turned_pegged_cube_stays_upright_and_can_be_picked_again(self):
        with tempfile.TemporaryDirectory() as temp:
            t=Trial(fixture(),Path(temp)/'trial',frames=False)
            try:
                t.wait(.6);origin=t.data.body('A_item1').xpos.copy();t.pick('A','A_item1');t.place('A',origin,rz(np.pi/2));t.wait(.6)
                body=t.data.body('A_item1');self.assertLess(np.linalg.norm(body.xpos-origin),.002)
                self.assertGreater(body.xmat.reshape(3,3)[2,2],.999)
                t.pick('A','A_item1');self.assertGreater(t.data.body('A_item1').xpos[2],origin[2]+.08)
            finally:t.close({'scope':'Quarter-turn support regression only','passed':False})


    def test_dense_flat_release_avoids_lateral_opening_between_neighbors(self):
        case=next(c for c in catalog()['cases'] if c['id']=='mosaic-a04-7x7-d2')
        with tempfile.TemporaryDirectory() as temp:
            t=Trial(case_directory(case),Path(temp)/'trial',frames=False)
            try:
                floor=.4;names=[o['id'] for o in t.task['objects'] if o['id']!='C_yellow_1'][:8]
                points=[np.array([x*.051,y*.051,floor+.02]) for x in (-1,0,1) for y in (-1,0,1) if x or y]
                for name,p in zip(names,points):t.data.joint(name+'_free').qpos[:]=np.r_[p,[1,0,0,0]]
                mujoco.mj_forward(t.model,t.data);t.wait(.6);t.pick('C','C_yellow_1',height=.020)
                t.place('C',[0,0,.42],np.eye(3),precise=True);t.wait(.8)
                b=t.data.body('C_yellow_1');self.assertLess(np.linalg.norm(b.xpos[:2]),.005);self.assertGreater(b.xmat.reshape(3,3)[2,2],.99)
                self.assertGreater(np.min(np.max(abs(b.xmat.reshape(3,3)),axis=0)),np.cos(np.radians(8)))
                for name,p in zip(names,points):self.assertLess(np.linalg.norm(t.data.body(name).xpos-p),.001)
                self.assertTrue(t.monitor.released(t.monitor.geoms['C_yellow_1']))
            finally:t.close({'scope':'Dense flat contact regression only','passed':False})

    def test_sideways_cube_uses_the_table_normal_for_release_and_withdrawal(self):
        case=next(c for c in catalog()['cases'] if c['id']=='mosaic-a04-7x7-d2')
        with tempfile.TemporaryDirectory() as temp:
            t=Trial(case_directory(case),Path(temp)/'trial',frames=False)
            try:
                from robofrontier.physics.robot_control import matrix_quat
                r=np.array([[0,0,1.],[0,1,0],[-1.,0,0]])
                t.data.joint('C_yellow_1_free').qpos[3:]=matrix_quat(r)
                mujoco.mj_forward(t.model,t.data);t.wait(.6);t.pick('C','C_yellow_1',height=.020)
                t.place('C',[0,0,.42],np.eye(3),precise=True);t.wait(.8)
                body=t.data.body('C_yellow_1');self.assertLess(np.linalg.norm(body.xpos-[0,0,.42]),.005)
                self.assertTrue(t.monitor.released(t.monitor.geoms['C_yellow_1']))
            finally:t.close({'passed':False,'scope':'Rotated body-frame regression only'})

if __name__=='__main__':unittest.main()
