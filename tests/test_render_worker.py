import tempfile
import time
import unittest
from pathlib import Path

import glfw
import mujoco
import numpy as np
from PIL import Image

from robofrontier.physics.render_worker import RenderWorker, apply_state, render_images

SCENE = '''<mujoco><visual><global offwidth="1280" offheight="800"/></visual><worldbody>
<light pos="0 0 2"/><camera name="front" pos="0 -1 .5" xyaxes="1 0 0 0 .4 .9"/><geom type="plane" size="1 1 .1" rgba=".4 .5 .6 1"/>
<body name="box" pos="0 0 .1"><freejoint/><geom name="box" type="box" size=".05 .05 .05" rgba=".9 .1 .1 1"/></body>
</worldbody></mujoco>'''


def request(model, data, path):
    return {'state': {'qpos': data.qpos.copy(), 'geom_rgba': model.geom_rgba.copy()},
            'images': [(model.camera('front').id, str(path))], 'width': 320, 'height': 200,
            'format': 'PNG', 'save_options': {}}


class RenderWorkerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name)
        self.model = mujoco.MjModel.from_xml_string(SCENE)
        self.data = mujoco.MjData(self.model)
        self.data.qpos[:3] = [.1, .05, .2]
        mujoco.mj_forward(self.model, self.data)
        try: self.worker = RenderWorker(self.model)
        except RuntimeError as error: self.skipTest(str(error))

    def tearDown(self):
        self.worker.close()
        self.tmp.cleanup()

    def local_image(self, source_model, source_data, path):
        if not glfw.init(): self.skipTest('No GLFW here')
        glfw.window_hint(glfw.VISIBLE, False)
        window = glfw.create_window(1280, 800, 'test', None, None)
        if not window: self.skipTest('No window here')
        glfw.make_context_current(window)
        data = mujoco.MjData(source_model)
        context = mujoco.MjrContext(source_model, mujoco.mjtFontScale.mjFONTSCALE_150)
        scene = mujoco.MjvScene(source_model, maxgeom=5000)
        options = mujoco.MjvOption()
        options.geomgroup[3] = 0
        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN, context)
        job = request(source_model, source_data, path)
        apply_state(mujoco, source_model, data, job['state'])
        render_images(mujoco, Image, source_model, data, scene, options, context, job)
        glfw.destroy_window(window)

    def test_worker_draws_what_the_owner_would(self):
        apart, here = self.folder/'worker.png', self.folder/'here.png'
        self.assertTrue(self.worker.submit(request(self.model, self.data, apart)))
        self.assertTrue(self.worker.wait(30))
        self.local_image(self.model, self.data, here)
        self.assertTrue(np.array_equal(np.asarray(Image.open(apart)), np.asarray(Image.open(here))))

    def test_image_shows_the_capture_moment_not_later_changes(self):
        path = self.folder/'moment.png'
        job = request(self.model, self.data, path)
        self.model.geom_rgba[self.model.geom('box').id] = [0, 1, 0, 1]
        self.data.qpos[0] = 5
        self.assertTrue(self.worker.submit(job))
        self.assertTrue(self.worker.wait(30))
        pixels = np.asarray(Image.open(path)).astype(int)
        self.assertTrue(((pixels[..., 0] > pixels[..., 1]+60) & (pixels[..., 0] > pixels[..., 2]+60)).any())

    def test_wait_covers_every_earlier_capture(self):
        paths = [self.folder/f'{i}.png' for i in range(3)]
        for path in paths: self.worker.submit(request(self.model, self.data, path))
        self.assertTrue(self.worker.wait(30))
        self.assertTrue(all(path.exists() for path in paths))

    def test_death_hands_back_unfinished_captures(self):
        self.worker.process.terminate()
        self.worker.process.join(10)
        deadline = time.monotonic()+10
        while not self.worker.closed and time.monotonic() < deadline: time.sleep(.01)
        job = request(self.model, self.data, self.folder/'gone.png')
        self.assertFalse(self.worker.submit(job))



class LocalRenderWaitTests(unittest.TestCase):
    """The readiness gate without a renderer process: replies are simulated."""
    def worker(self):
        import threading
        worker = object.__new__(RenderWorker)
        worker.lock = threading.Lock(); worker.changed = threading.Condition(worker.lock)
        worker.pending, worker.failed, worker.local, worker.closed = {}, [], set(), False
        return worker

    def test_a_capture_rendered_by_the_owner_is_unfinished_until_written(self):
        worker = self.worker()
        worker.pending = {1: {'id': 1}, 2: {'id': 2}}
        with worker.changed:  # capture 1 fails in the worker
            worker.failed.append(worker.pending.pop(1)); worker.changed.notify_all()
        handed = worker.failed_captures()
        self.assertEqual([r['id'] for r in handed], [1])
        with worker.changed:  # another capture's reply arrives during the owner's local render
            worker.pending.pop(2); worker.changed.notify_all()
        self.assertFalse(worker.wait(.05))
        worker.rendered_locally()
        self.assertTrue(worker.wait(.05))

    def test_a_wait_that_began_before_the_hand_back_still_covers_it(self):
        import threading
        worker = self.worker()
        worker.pending = {1: {'id': 1}}
        answers = []
        waiter = threading.Thread(target=lambda: answers.append(worker.wait(5)))
        waiter.start(); time.sleep(.05)
        with worker.changed:
            worker.failed.append(worker.pending.pop(1)); worker.changed.notify_all()
        worker.failed_captures()
        with worker.changed: worker.changed.notify_all()
        time.sleep(.05)
        self.assertEqual(answers, [])
        worker.rendered_locally(); waiter.join(5)
        self.assertEqual(answers, [True])


if __name__ == '__main__': unittest.main()
