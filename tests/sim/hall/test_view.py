"""An image draws only the hall shapes that can show in it, and that leaves the image as it was."""

import json
import tempfile
import unittest
from pathlib import Path

import mujoco
import numpy as np

from roboteam.runtime.world.pipeline import World
from roboteam.sim.hall.flat import BUILT, HALL_GROUP
from roboteam.sim.hall.world import HALL_BODY
from roboteam.sim.render.look import HIDDEN_GROUP, HallView, look_model
from roboteam.sim.render.worker import LocalRenderer
from roboteam.tasks.task_types import prepare

CASE = 'transport-small-l1'
CAMERAS = ('global', 'global_rear', 'global_side', 'top', 'A_front', 'B_side')


@unittest.skipUnless((BUILT / 'hall.json').exists(), 'The built hall is not here (roboteam bootstrap)')
class HallViewTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        run = Path(cls.tmp.name) / CASE
        prepare(CASE, run)
        cls.world = World(run, json.loads((run / 'private/inputs/task.json').read_text()))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_hall_lights_the_scene_and_is_its_floor(self):
        model = self.world.model
        visual = look_model(model)
        hall = visual.body(HALL_BODY).id
        for light in range(visual.nlight):
            self.assertEqual(bool(visual.light_active[light]), int(visual.light_bodyid[light]) == hall)
        casting = [
            light
            for light in range(visual.nlight)
            if visual.light_castshadow[light] and visual.light_active[light]
        ]
        self.assertEqual(len(casting), 1)
        self.assertEqual(int(visual.geom_group[visual.geom('floor').id]), HIDDEN_GROUP)
        # The world's own model is left alone: its floor still catches what falls.
        self.assertNotEqual(int(model.geom_group[model.geom('floor').id]), HIDDEN_GROUP)
        self.assertTrue(
            model.geom_contype[model.geom('floor').id] or model.geom_conaffinity[model.geom('floor').id]
        )

    def test_each_camera_draws_a_small_part_of_the_hall(self):
        visual = look_model(self.world.model)
        data = mujoco.MjData(visual)
        mujoco.mj_resetDataKeyframe(visual, data, visual.key('initial').id)
        mujoco.mj_forward(visual, data)
        view = HallView(visual)
        for name in CAMERAS:
            view.select(visual, data, visual.camera(name).id, 1280, 800)
            groups = visual.geom_group[view.first :]
            self.assertTrue(np.isin(groups, (HALL_GROUP, HIDDEN_GROUP)).all(), name)
            self.assertLess((groups == HALL_GROUP).sum(), 0.25 * view.count, name)
            self.assertGreater((groups == HALL_GROUP).sum(), 10, name)
        view.everything(visual)
        self.assertTrue((visual.geom_group[view.first :] == HALL_GROUP).all())

    def test_the_selection_leaves_the_image_as_it_was(self):
        import glfw

        from roboteam.sim.render.cocoa import start_glfw

        try:
            start_glfw()
        except RuntimeError:
            self.skipTest('No GLFW here')
        glfw.window_hint(glfw.VISIBLE, False)
        window = glfw.create_window(1280, 800, 'test', None, None)
        if not window:
            self.skipTest('No window here')
        glfw.make_context_current(window)
        try:
            renderer = LocalRenderer(mujoco, self.world.model)
            select = renderer.hall.select
            for name in CAMERAS:
                camera = self.world.model.camera(name).id
                renderer.hall.select = select
                chosen = renderer.frame(mujoco, self.world, camera, 640, 400)
                renderer.hall.select = lambda visual, *rest: renderer.hall.everything(visual)
                everything = renderer.frame(mujoco, self.world, camera, 640, 400)
                # Antialiasing may round a handful of pixels one level apart; nothing else may differ.
                apart = np.abs(chosen.astype(int) - everything.astype(int))
                self.assertLessEqual(int(apart.max()), 1, name)
                self.assertLessEqual(int(apart.any(axis=2).sum()), 16, name)
                self.assertGreater(len(np.unique(chosen.reshape(-1, 3), axis=0)), 50, name)
        finally:
            glfw.destroy_window(window)


if __name__ == '__main__':
    unittest.main()
