from types import SimpleNamespace
import unittest
import mujoco
from robofrontier.suite.evaluate import Monitor

BOX_ON_TABLE = '''<mujoco><option timestep="0.002"/><worldbody>
<geom name="table_top" type="plane" size="1 1 .1"/>
<body><freejoint/><geom type="box" size=".03 .03 .03" mass=".1" pos="0 0 .03"/></body>
</worldbody></mujoco>'''


def settled(sleep):
    model = mujoco.MjModel.from_xml_string(BOX_ON_TABLE)
    if sleep: model.opt.enableflags |= int(mujoco.mjtEnableBit.mjENBL_SLEEP)
    data = mujoco.MjData(model)
    for _ in range(1500): mujoco.mj_step(model, data)
    return SimpleNamespace(m=model, d=data)


class SceneContactTests(unittest.TestCase):
    def test_a_sleeping_body_keeps_its_support(self):
        monitor = settled(sleep=True)
        self.assertEqual(monitor.d.ntree_awake, 0)
        self.assertEqual(monitor.d.ncon, 0)
        contacts = Monitor.scene_contacts(monitor)
        self.assertGreater(len(contacts), 0)
        self.assertTrue(all(float(c.dist) <= .0002 for c in contacts))

    def test_a_world_without_sleep_reads_its_own_contacts(self):
        monitor = settled(sleep=False)
        contacts = Monitor.scene_contacts(monitor)
        self.assertEqual(len(contacts), monitor.d.ncon)
        self.assertEqual(int(contacts[0].geom1), int(monitor.d.contact[0].geom1))

    def test_contacts_follow_the_current_pose(self):
        monitor = settled(sleep=True)
        Monitor.scene_contacts(monitor)
        monitor.d.qpos[2] += .2
        monitor.d.time += .002
        self.assertEqual(len(Monitor.scene_contacts(monitor)), 0)


if __name__ == '__main__': unittest.main()
