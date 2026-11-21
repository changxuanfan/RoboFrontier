import io
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import mujoco
import numpy as np
from PIL import Image

from roboteam.runtime.run.setup import prepare_run, verify_inputs, write_json
from roboteam.runtime.world.pipeline import Service
from roboteam.sim.render.image import (
    DEFAULT_PROFILE,
    LOW_RESOLUTION_PROFILE,
    observation_profile,
    save_observation,
)
from roboteam.tasks.config import load_run_settings


class ObservationImageTests(unittest.TestCase):
    def test_frozen_default_and_invalid_model_entry(self):
        with self.assertRaises(ValueError):
            observation_profile({})
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            new = prepare_run(root / 'new')
            cfg = json.loads((new / 'private/inputs/run.json').read_text())
            public = json.loads((new / 'public/inputs/task.json').read_text())
            self.assertEqual(cfg['observation_image_profile'], DEFAULT_PROFILE)
            self.assertEqual(
                public['observation_image'], {'width': 1280, 'height': 800, 'format': 'JPEG', 'quality': 90}
            )
            self.assertEqual(verify_inputs(new), [])
            cfg = load_run_settings()
            cfg['observation_image_profile'] = 'not-a-profile'
            write_json(root / 'invalid.json', cfg)
            with self.assertRaises(ValueError):
                prepare_run(root / 'invalid', run_settings_path=root / 'invalid.json')
            self.assertFalse((root / 'invalid').exists())

    def test_capture_saves_a_valid_image(self):
        model = mujoco.MjModel.from_xml_string(
            "<mujoco><visual><global offwidth='1280' offheight='800'/></visual><worldbody><camera name='top' pos='0 0 2'/><geom type='sphere' size='.1'/></worldbody></mujoco>"
        )
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        with tempfile.TemporaryDirectory() as tmp, mujoco.Renderer(model, width=1280, height=800) as renderer:
            root = Path(tmp)
            (root / 'public/observations').mkdir(parents=True)
            world = SimpleNamespace(model=model, data=data, time=0, arms={}, task_geoms=model.ngeom)
            # No worker here, so the owner draws the capture itself; it needs only a current graphics context.
            service = SimpleNamespace(
                obs=0,
                directory=root,
                world=world,
                context=renderer._mjr_context,
                offscreen_context=True,
                perf={'capture_wall_s': 0.0, 'captures': 0},
            )
            service.capture_request = lambda cameras: Service.capture_request(service, cameras)
            service.render_here = lambda request: Service.render_here(service, request)
            for name, size, fmt, suffix in ((DEFAULT_PROFILE, (1280, 800), 'JPEG', '.jpg'),):
                service.observation_image = observation_profile({'observation_image_profile': name})
                result = Service.capture(service, ['top'])
                path = Path(result['images']['top'])
                self.assertEqual(path.suffix, suffix)
                with Image.open(path) as image:
                    image.load()
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.format, fmt)

    # The rendered pixels, encoded.
    @staticmethod
    def as_rendered(rgb, profile, size=None):
        image = Image.fromarray(rgb[::-1])
        if size:
            image = image.resize(size, Image.BOX)
        data = io.BytesIO()
        image.save(data, format=profile['format'], **Service.image_save_options(profile))
        return data.getvalue()

    def scene(self):
        # Thin stripes and a small sphere: detail a lower resolution removes.
        return mujoco.MjModel.from_xml_string(
            "<mujoco><visual><global offwidth='1280' offheight='800'/></visual>"
            "<asset><texture name='t' type='2d' builtin='checker' rgb1='1 1 1' rgb2='0 0 0' width='64' height='64'/>"
            "<material name='m' texture='t' texrepeat='40 40'/></asset><worldbody><light pos='0 0 3'/>"
            "<camera name='top' pos='0 0 2'/><geom type='plane' size='1 1 .1' material='m'/>"
            "<geom type='sphere' size='.05' pos='.2 .1 .05' rgba='1 0 0 1'/></worldbody></mujoco>"
        )

    def rendered(self, model, data, renderer, width, height):
        viewport = mujoco.MjrRect(0, 0, width, height)
        cam = mujoco.MjvCamera()
        cam.type = mujoco.mjtCamera.mjCAMERA_FIXED
        cam.fixedcamid = model.camera('top').id
        mujoco.mjr_setBuffer(mujoco.mjtFramebuffer.mjFB_OFFSCREEN, renderer._mjr_context)
        mujoco.mjv_updateScene(
            model, data, mujoco.MjvOption(), None, cam, mujoco.mjtCatBit.mjCAT_ALL, renderer._scene
        )
        mujoco.mjr_render(viewport, renderer._scene, renderer._mjr_context)
        rgb = np.empty((height, width, 3), dtype=np.uint8)
        mujoco.mjr_readPixels(rgb, None, viewport, renderer._mjr_context)
        return rgb

    def test_the_default_profile_encodes_the_rendered_pixels_unchanged(self):
        from roboteam.sim.render.image import reduced_size, render_size

        rgb = np.random.default_rng(7).integers(0, 256, (800, 1280, 3), dtype=np.uint8)
        with tempfile.TemporaryDirectory() as tmp:
            for name, size in ((DEFAULT_PROFILE, (1280, 800)),):
                profile = observation_profile({'observation_image_profile': name})
                path = Path(tmp) / ('x' + profile['extension'])
                self.assertIsNone(reduced_size(profile))
                self.assertEqual(render_size(profile), size)
                save_observation(Image, rgb, path, profile['format'], Service.image_save_options(profile))
                self.assertEqual(path.read_bytes(), self.as_rendered(rgb, profile))

    def test_capture_reduces_only_under_the_low_resolution_profile_on_both_render_routes(self):
        from roboteam.sim.render.image import render_size

        model = self.scene()
        data = mujoco.MjData(model)
        mujoco.mj_forward(model, data)
        sharp_profile = observation_profile({'observation_image_profile': DEFAULT_PROFILE})
        low_profile = observation_profile({'observation_image_profile': LOW_RESOLUTION_PROFILE})
        # Drawn exactly as the default camera, then one pixel for every 10 x 10.
        self.assertEqual(render_size(low_profile), (1280, 800))
        self.assertEqual((low_profile['width'], low_profile['height']), (128, 80))
        self.assertEqual(
            (low_profile['format'], low_profile['quality'], low_profile['extension']), ('JPEG', 95, '.jpg')
        )
        with tempfile.TemporaryDirectory() as tmp, mujoco.Renderer(model, width=1280, height=800) as renderer:
            root = Path(tmp)
            (root / 'public/observations').mkdir(parents=True)
            world = SimpleNamespace(model=model, data=data, time=0, arms={}, task_geoms=model.ngeom)
            service = SimpleNamespace(
                obs=0,
                directory=root,
                world=world,
                context=renderer._mjr_context,
                offscreen_context=True,
                perf={'capture_wall_s': 0.0, 'captures': 0},
                render_worker=None,
            )
            service.capture_request = lambda cameras: Service.capture_request(service, cameras)
            service.render_here = lambda request: Service.render_here(service, request)

            class Queue:  # A render worker that keeps the request instead of drawing it.
                def submit(self, request):
                    self.request = request
                    return True

            written = {}
            for profile in (sharp_profile, low_profile):
                service.observation_image = profile
                service.render_worker = None
                # The owner draws the capture itself, the same way twice.
                first = Path(Service.capture(service, ['top'])['images']['top']).read_bytes()
                again = Path(Service.capture(service, ['top'])['images']['top']).read_bytes()
                self.assertEqual(first, again)
                # The capture a render worker receives: drawn at the default size, reduced only under the low profile.
                service.render_worker = Queue()
                path = Path(Service.capture(service, ['top'])['images']['top'])
                request = service.render_worker.request
                self.assertEqual((request['width'], request['height']), (1280, 800))
                self.assertEqual(request.get('output_size'), [128, 80] if profile is low_profile else None)
                # Drawn from that request, it is the same file as the owner's own capture.
                service.render_worker = None
                Service.render_here(service, request)
                self.assertEqual(path.read_bytes(), first)
                written[profile['width']] = first
            with Image.open(io.BytesIO(written[128])) as low, Image.open(io.BytesIO(written[1280])) as sharp:
                self.assertEqual((low.size, low.format), ((128, 80), 'JPEG'))
                # Each pixel is the mean of its 10 x 10 block of the sharp frame.
                mean = (
                    np.asarray(sharp.convert('RGB'), dtype=float)
                    .reshape(80, 10, 128, 10, 3)
                    .mean(axis=(1, 3))
                )
                self.assertLess(np.abs(np.asarray(low.convert('RGB'), dtype=float) - mean).mean(), 6)

    def test_low_resolution_run_states_its_size_and_keeps_every_other_public_input(self):
        from roboteam.configuration import load_configuration

        self.assertEqual(load_configuration()['render']['observation_profile'], DEFAULT_PROFILE)
        self.assertEqual(
            load_configuration(overrides={'render': {'observation_profile': LOW_RESOLUTION_PROFILE}})[
                'render'
            ]['observation_profile'],
            LOW_RESOLUTION_PROFILE,
        )
        from roboteam.runtime.run.setup import prepare_case

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = load_run_settings()
            for name in (DEFAULT_PROFILE, LOW_RESOLUTION_PROFILE):
                cfg['observation_image_profile'] = name
                write_json(root / (name + '.json'), cfg)

            # (The rules name the run's own folder, which differs between any two runs.)
            def files(run):
                return {
                    str(p.relative_to(run / 'public')): p.read_bytes().replace(str(run).encode(), b'<run>')
                    for p in sorted((run / 'public').rglob('*'))
                    if p.is_file()
                }

            for case in ('mosaic-small-l3', 'dial-small-l3'):
                sharp = prepare_case(case, root / case / 'sharp', root / (DEFAULT_PROFILE + '.json'))
                low = prepare_case(case, root / case / 'low', root / (LOW_RESOLUTION_PROFILE + '.json'))
                self.assertEqual(
                    json.loads((sharp / 'private/inputs/run.json').read_text())['observation_image_profile'],
                    DEFAULT_PROFILE,
                )
                self.assertEqual(
                    json.loads((low / 'private/inputs/run.json').read_text())['observation_image_profile'],
                    LOW_RESOLUTION_PROFILE,
                )
                before, after = files(sharp), files(low)
                # The task states the size its images have; a calibration that names a size follows it.
                task_sharp, task_low = (
                    json.loads(before.pop('inputs/task.json')),
                    json.loads(after.pop('inputs/task.json')),
                )
                self.assertEqual(
                    task_low['observation_image'],
                    {'width': 128, 'height': 80, 'format': 'JPEG', 'quality': 95},
                )
                self.assertEqual(
                    {k: v for k, v in task_low.items() if k != 'observation_image'},
                    {k: v for k, v in task_sharp.items() if k != 'observation_image'},
                )
                if task_low.get('camera_calibration'):
                    name = 'inputs/' + task_low['camera_calibration']
                    cal_sharp, cal_low = json.loads(before.pop(name)), json.loads(after.pop(name))
                    self.assertEqual(
                        (cal_sharp['image_size_pixel'], cal_low['image_size_pixel']), ([1280, 800], [128, 80])
                    )
                    self.assertEqual(
                        {k: v for k, v in cal_low.items() if k != 'image_size_pixel'},
                        {k: v for k, v in cal_sharp.items() if k != 'image_size_pixel'},
                    )
                # Rules, roles, reference pictures and every other public file are those of a default run.
                self.assertEqual(after, before)
                self.assertEqual(verify_inputs(low), [])
            self.assertIn('camera_calibration', task_low)

    def test_dial_calibration_copy_keeps_frozen_original(self):
        from roboteam.runtime.run.setup import prepare_case

        with tempfile.TemporaryDirectory() as tmp:
            run = prepare_case('dial-small-l1', Path(tmp) / 'dial')
            public = json.loads((run / 'public/inputs/task.json').read_text())
            # The policy sees one calibration sized for this run; the signed original is private.
            original = json.loads(
                (run / 'private/inputs/release-materials/camera-calibration.json').read_text()
            )
            derived = json.loads((run / 'public/inputs' / public['camera_calibration']).read_text())
            self.assertEqual(original['image_size_pixel'], [1280, 800])
            self.assertEqual(derived['image_size_pixel'], [1280, 800])
            self.assertEqual(derived['cameras'], original['cameras'])
            self.assertEqual(verify_inputs(run), [])


if __name__ == '__main__':
    unittest.main()
