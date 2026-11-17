"""Observation rendering in its own process, so the world keeps running during a capture.

The owner sends the state of the capture moment and the image paths. A caller sees those
paths only after `wait` says the files exist. If the process dies, `failed_captures` hands
back what it did not finish, and the owner renders those itself.
"""
import itertools
import multiprocessing
import os
import pickle
import threading

import numpy as np

from .observation_image import save_observation
from .observation_look import DEFAULT_LOOK, display, look_model, set_colours

MAX_GEOM = 5000


def _graphics_context():
    """The same backend choice as the owner; a window here is never shown."""
    backend = os.environ.get('MUJOCO_GL', '').lower()
    if backend in ('osmesa', 'egl'):
        if backend == 'egl': from mujoco.egl import GLContext
        else: from mujoco.osmesa import GLContext
        context = GLContext(1280, 800)
        context.make_current()
        return context
    from roboteam.physics.cocoa import start_glfw
    glfw = start_glfw()
    glfw.window_hint(glfw.VISIBLE, False)
    window = glfw.create_window(1280, 800, 'RoboTeam observations', None, None)
    if not window: raise RuntimeError('GLFW window creation failed')
    glfw.make_context_current(window)
    return window


def apply_state(mujoco, model, data, state, look=DEFAULT_LOOK):
    """Pose and appearance of the capture moment; everything drawn derives from these.

    `model` is the copy that `look_model` made, never the world's own model."""
    data.qpos[:] = state['qpos']
    if model.nmocap:
        data.mocap_pos[:] = state['mocap_pos']
        data.mocap_quat[:] = state['mocap_quat']
    set_colours(model, state['geom_rgba'], look)
    mujoco.mj_kinematics(model, data)
    mujoco.mj_comPos(model, data)
    mujoco.mj_camlight(model, data)


def render_images(mujoco, Image, model, data, scene, options, context, request, look=DEFAULT_LOOK):
    """Write one capture's images from a state already applied to `data`."""
    width, height = request['width'], request['height']
    viewport = mujoco.MjrRect(0, 0, width, height)
    for camera_id, path in request['images']:
        camera = mujoco.MjvCamera()
        camera.type = mujoco.mjtCamera.mjCAMERA_FIXED
        camera.fixedcamid = camera_id
        mujoco.mjv_updateScene(model, data, options, None, camera, mujoco.mjtCatBit.mjCAT_ALL, scene)
        mujoco.mjr_render(viewport, scene, context)
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        mujoco.mjr_readPixels(rgb, None, viewport, context)
        # The display transform maps each pixel on its own, so it can run before the frame is flipped and reduced.
        save_observation(Image, display(rgb, look), path, request['format'], request['save_options'], request.get('output_size'))


def _serve(connection, model_bytes, look):
    import mujoco
    from PIL import Image
    model = look_model(pickle.loads(model_bytes), look)
    # Held for the life of the process: an EGL or OSMesa context object frees its context when
    # it is collected, and MjrContext then fails (gladLoadGL error).
    graphics = _graphics_context()
    data = mujoco.MjData(model)
    context = mujoco.MjrContext(model, mujoco.mjtFontScale.mjFONTSCALE_150)
    scene = mujoco.MjvScene(model, maxgeom=MAX_GEOM)
    options = mujoco.MjvOption()
    options.geomgroup[3] = 0
    mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN, context)
    connection.send('ready')
    while True:
        try: request = connection.recv()
        except EOFError: return
        if request is None: return
        try:
            apply_state(mujoco, model, data, request['state'], look)
            render_images(mujoco, Image, model, data, scene, options, context, request, look)
            connection.send((request['id'], None))
        except Exception as error:
            connection.send((request['id'], repr(error)))


class RenderWorker:
    def __init__(self, model, look=DEFAULT_LOOK, ready_timeout_s=120.):
        spawn = multiprocessing.get_context('spawn')
        self.connection, child = spawn.Pipe()
        self.process = spawn.Process(target=_serve, args=(child, pickle.dumps(model), look), daemon=True)
        self.process.start()
        child.close()
        if not self.connection.poll(ready_timeout_s) or self.connection.recv() != 'ready':
            self.process.terminate()
            raise RuntimeError('Observation renderer did not start')
        self.ids = itertools.count(1)
        self.lock = threading.Lock()
        self.changed = threading.Condition(self.lock)
        self.pending = {}
        self.failed = []
        self.local = set()  # failed captures the owner is rendering itself
        self.closed = False
        threading.Thread(target=self._read_replies, daemon=True).start()

    def _read_replies(self):
        try:
            while True:
                ident, error = self.connection.recv()
                with self.changed:
                    request = self.pending.pop(ident, None)
                    if error is not None and request is not None: self.failed.append(request)
                    self.changed.notify_all()
        except (EOFError, OSError):
            with self.changed:
                self.closed = True
                self.failed.extend(self.pending.values())
                self.pending.clear()
                self.changed.notify_all()

    def submit(self, request):
        """Queue one capture; False when the process is gone and the owner must render it."""
        with self.changed:
            if self.closed: return False
            request = dict(request, id=next(self.ids))
            self.pending[request['id']] = request
        try:
            self.connection.send(request)
        except (OSError, ValueError):
            with self.changed:
                self.pending.pop(request['id'], None)
                self.closed = True
            return False
        return True

    def failed_captures(self):
        """Hand failed captures to the owner, which renders them before `rendered_locally`."""
        with self.changed:
            requests, self.failed = self.failed, []
            # The owner renders one handed-back set at a time, so this replaces the last one.
            self.local = {request['id'] for request in requests}
        return requests

    def wait(self, timeout_s):
        """Whether every capture queued before this call has finished in time.

        A failed capture counts as unfinished until the owner has rendered it, including
        while the owner is still rendering it after taking it from `failed`."""
        with self.changed:
            limit = max(set(self.pending) | self.local, default=0)
            return self.changed.wait_for(
                lambda: not self.failed and not any(ident <= limit for ident in self.pending)
                and not any(ident <= limit for ident in self.local), timeout_s)

    def rendered_locally(self):
        with self.changed:
            self.local = set()
            self.changed.notify_all()

    def close(self):
        try: self.connection.send(None)
        except (OSError, ValueError): pass
        self.process.join(10)
        if self.process.is_alive(): self.process.terminate()


class LocalRenderer:
    """The same drawing in the owner's process, for captures the worker did not finish.

    It needs a current graphics context and draws to its own offscreen buffer."""
    def __init__(self, mujoco, model, look=DEFAULT_LOOK):
        self.look = look
        self.model = look_model(model, look)
        self.data = mujoco.MjData(self.model)
        self.context = mujoco.MjrContext(self.model, mujoco.mjtFontScale.mjFONTSCALE_150)
        self.scene = mujoco.MjvScene(self.model, maxgeom=MAX_GEOM)
        self.options = mujoco.MjvOption()
        self.options.geomgroup[3] = 0

    def render(self, mujoco, Image, request):
        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN, self.context)
        apply_state(mujoco, self.model, self.data, request['state'], self.look)
        render_images(mujoco, Image, self.model, self.data, self.scene, self.options, self.context, request, self.look)
