"""A released task runs at its desk in the hall, and the hall changes nothing about the task."""

import copy
import json
import tempfile
import unittest
from pathlib import Path

import mujoco
import numpy as np

from roboteam.runtime.world.pipeline import World
from roboteam.sim.hall.flat import BUILT, HALL_GROUP
from roboteam.sim.hall.world import HALL_BODY, has_desk, task_copy, task_geoms
from roboteam.tasks.task_types import prepare

CASES = ('transport-small-l1', 'mosaic-small-l1', 'relay-small-l2', 'dial-small-l2')


def drive(model, data, steps=300, seed=3):
    """The same changing commands for every model with these actuators."""
    random = np.random.default_rng(seed)
    low, high = model.actuator_ctrlrange.T
    for step in range(steps):
        if step % 25 == 0:
            data.ctrl[:] = np.clip(0.9 * data.ctrl + 0.1 * random.uniform(low, high), low, high)
        mujoco.mj_step(model, data)
    return data.qpos.copy(), data.qvel.copy(), int(data.ncon)


@unittest.skipUnless((BUILT / 'hall.json').exists(), 'The built hall is not here (roboteam bootstrap)')
class HallWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.worlds = {}
        for case in CASES:
            run = Path(cls.tmp.name) / case
            prepare(case, run)
            cls.worlds[case] = World(run, json.loads((run / 'private/inputs/task.json').read_text()))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_every_released_task_has_a_desk(self):
        desks = json.loads((BUILT / 'hall.json').read_text())['desks']
        self.assertEqual(len(desks), 36)
        self.assertTrue(all(has_desk(case) for case in CASES))
        self.assertFalse(has_desk('no-such-task'))

    def test_the_task_scene_keeps_every_index(self):
        for case, world in self.worlds.items():
            model, plain = world.model, world.task_scene
            self.assertEqual(model.body(HALL_BODY).id, plain.nbody, case)
            self.assertEqual(task_geoms(model), plain.ngeom, case)
            self.assertEqual(world.task_geoms, plain.ngeom, case)
            for count in ('nq', 'nv', 'nu', 'ncam', 'njnt'):
                self.assertEqual(getattr(model, count), getattr(plain, count), (case, count))
            self.assertEqual(
                [model.geom(g).name for g in range(plain.ngeom)],
                [plain.geom(g).name for g in range(plain.ngeom)],
                case,
            )
            self.assertTrue(np.array_equal(model.cam_pos, plain.cam_pos), case)
            self.assertEqual(model.stat.extent, plain.stat.extent, case)

    def test_hall_shapes_touch_nothing(self):
        for case, world in self.worlds.items():
            hall = slice(world.task_geoms, world.model.ngeom)
            self.assertGreater(world.model.ngeom - world.task_geoms, 10000, case)
            self.assertFalse(world.model.geom_contype[hall].any(), case)
            self.assertFalse(world.model.geom_conaffinity[hall].any(), case)
            self.assertTrue((world.model.geom_group[hall] == HALL_GROUP).all(), case)
            own = [
                g
                for g in range(*hall.indices(world.model.ngeom))
                if (case + '__') in world.model.geom(g).name
            ]
            self.assertEqual(own, [], case)

    def test_the_motion_is_the_same_with_and_without_the_hall(self):
        for case, world in self.worlds.items():
            with_hall, alone = copy.copy(world.model), task_copy(world.model, world.task_scene)
            results = []
            for model in (with_hall, alone):
                data = mujoco.MjData(model)
                mujoco.mj_resetDataKeyframe(model, data, model.key('initial').id)
                results.append(drive(model, data))
            self.assertTrue(np.array_equal(results[0][0], results[1][0]), case)
            self.assertTrue(np.array_equal(results[0][1], results[1][1]), case)
            self.assertEqual(results[0][2], results[1][2], case)

    def test_the_planning_copy_carries_the_worlds_settings(self):
        world = self.worlds['transport-small-l1']
        arm = next(iter(world.arms.values()))
        before = world.model.actuator_biasprm[arm.grip].copy()
        try:
            world.model.actuator_biasprm[arm.grip, 2] = -12.5
            twin = world.task_model()
            self.assertEqual(twin.ngeom, world.task_geoms)
            self.assertEqual(twin.actuator_biasprm[arm.grip, 2], -12.5)
            self.assertEqual(int(twin.opt.enableflags), int(world.model.opt.enableflags))
            twin.actuator_biasprm[arm.grip, 2] = 0  # a copy: the world keeps its own
            self.assertEqual(world.model.actuator_biasprm[arm.grip, 2], -12.5)
        finally:
            world.model.actuator_biasprm[arm.grip] = before


if __name__ == '__main__':
    unittest.main()
