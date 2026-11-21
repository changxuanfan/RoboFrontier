"""A ground_truth run: the simulator's state instead of camera images, and the Dial code private."""

import hashlib
import json
import math
import os
import re
import tempfile
import time
import unittest
from pathlib import Path

import mujoco
import numpy as np

from fake_pipeline import FakeWorld, fake_capture
from roboteam.harness.shared.robot_mcp import RobotBridge
from roboteam.runtime.run import bootstrap
from roboteam.runtime.run.setup import prepare_case, prepare_run, verify_inputs
from roboteam.runtime.sandbox import access as policy_access
from roboteam.runtime.tools import ground_truth
from roboteam.runtime.tools.robot_ops import check_request
from roboteam.runtime.world.pipeline import World
from roboteam.runtime.world.service import RuntimeService
from roboteam.sim.hall.flat import BUILT
from roboteam.tasks import ground_truth as ground_truth_files
from roboteam.tasks import observation_mode, tools_mode
from roboteam.tasks.config import ROOT, load_run_settings, startup_protocol
from roboteam.tasks.evaluate import Monitor
from roboteam.tasks.task_types import RELEASE, dial_code, read

TEMPLATES = sorted((ROOT / 'prompts').rglob('*.md'))
IMAGES_SHA256 = json.loads(Path(__file__).with_name('images_prompt_sha256.json').read_text())
DIAL_CASES = [case['id'] for case in read(ROOT / RELEASE)['task_types']['dial']['policy']]
TEXT = ('.json', '.md', '.xml', '.txt', '.sh')


def run_settings(root, observation=None, harness='codex', system='single-agent'):
    cfg = load_run_settings()
    cfg.update(system=system, startup_protocol=startup_protocol(system), harness=harness)
    if observation:
        cfg['observation'] = observation
    path = Path(root) / ('settings-%s-%s-%s.json' % (harness, system, observation or 'unset'))
    path.write_text(json.dumps(cfg))
    return path


def public_texts(run):
    """Every text file a role can read in its run, by path."""
    return {
        path: path.read_text()
        for path in sorted((run / 'public').rglob('*'))
        if path.is_file() and path.suffix in TEXT
    }


class TemplateTests(unittest.TestCase):
    def test_markers_select_one_wording_and_leave_shared_text(self):
        text = (
            'a\n<!-- observation:images -->\nsee\n<!-- /observation -->\n'
            '<!-- observation:ground_truth -->\nread\n<!-- /observation -->\nb\n'
        )
        self.assertEqual(observation_mode.render(text, 'images'), 'a\nsee\nb\n')
        self.assertEqual(observation_mode.render(text, 'ground_truth'), 'a\nread\nb\n')
        with self.assertRaises(ValueError):
            observation_mode.render('<!-- observation:images -->\nopen\n', 'images')
        with self.assertRaises(ValueError):
            observation_mode.render(text, 'depth')

    def test_the_images_rendering_of_every_template_is_what_it_was(self):
        """images_prompt_sha256.json holds each template's rendering from before the
        observation setting existed, per tool mode. Update it only with a deliberate change
        of what an images role is told."""
        self.assertEqual(sorted(IMAGES_SHA256), [str(p.relative_to(ROOT)) for p in TEMPLATES])
        for path in TEMPLATES:
            text = path.read_text()
            for tools, expected in IMAGES_SHA256[str(path.relative_to(ROOT))].items():
                rendered = observation_mode.render(tools_mode.render(text, tools), 'images')
                self.assertEqual(hashlib.sha256(rendered.encode()).hexdigest(), expected, (path, tools))
                self.assertNotIn('<!--', rendered, path)
                self.assertNotIn('ground-truth', rendered, path)
                self.assertNotIn('ground truth', rendered, path)

    def test_every_template_renders_in_both_modes_with_balanced_markers(self):
        marked = 0
        for path in TEMPLATES:
            text = path.read_text()
            self.assertEqual(
                len(re.findall(r'^<!-- observation:\w+ -->$', text, re.M)),
                len(re.findall(r'^<!-- /observation -->$', text, re.M)),
                path,
            )
            for tools in tools_mode.MODES:
                images, truth = (
                    observation_mode.render(tools_mode.render(text, tools), mode)
                    for mode in observation_mode.MODES
                )
                self.assertNotIn('<!--', truth, path)
                if tools == 'full':
                    marked += images != truth
                    # The passages that told an images role to look are in the other wording.
                    # (Shared reference text may still name RGB; the rules say what replaces it.)
                    for phrase in (
                        'camera_calibration',
                        'informative view',
                        'allowed RGB',
                        'timestamped RGB',
                        'selected RGB',
                        'objects with RGB',
                        'permitted views,',
                        '## Selected images',
                        'public_image',
                    ):
                        self.assertNotIn(phrase, truth, (path, phrase))
        truth_rules = observation_mode.render(
            tools_mode.render((ROOT / 'prompts/rules.md').read_text(), 'full'), 'ground_truth'
        )
        self.assertNotIn('permitted RGB', truth_rules)
        self.assertIn('speaks of RGB, images, cameras or views', truth_rules)
        self.assertGreaterEqual(marked, 7)


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.previous = os.environ.pop('ROBOTEAM_POLICY_ENV', None)

    def tearDown(self):
        if self.previous is not None:
            os.environ['ROBOTEAM_POLICY_ENV'] = self.previous
        self.tmp.cleanup()

    def test_an_images_run_is_prepared_as_before_the_mode_existed(self):
        unset = prepare_run(self.root / 'unset/run', run_settings_path=run_settings(self.root))
        images = prepare_run(self.root / 'images/run', run_settings_path=run_settings(self.root, 'images'))
        self.assertNotIn('observation', json.loads((unset / 'private/inputs/run.json').read_text()))
        for run in (unset, images):
            self.assertEqual(observation_mode.of_run(run), 'images')
            self.assertFalse((run / ground_truth_files.FOLDER).exists())
            task = json.loads((run / 'public/inputs/task.json').read_text())
            self.assertIn('cameras', task)
            self.assertNotIn('ground_truth', task)
            self.assertFalse(task['observation_contract']['live_object_truth_for_policy'])
            self.assertNotIn('observation', json.loads((run / 'private/inputs/manifest.json').read_text()))
            # The task guide is the checked-in one, in the images wording.
            source = ROOT / 'prompts/guides' / (task['task_type'] + '.md')
            self.assertEqual(
                (run / 'public/inputs/task/guide.md').read_text(),
                observation_mode.render(source.read_text(), 'images'),
            )
            first = (run / 'private/inputs/bootstrap/Controller.md').read_text()
            self.assertIn(bootstrap.HARNESS_LINES['codex'], first)
            self.assertNotIn('ground', first)
        names = sorted(
            str(p.relative_to(unset / 'public')) for p in (unset / 'public').rglob('*') if p.is_file()
        )
        self.assertEqual(
            names,
            sorted(
                str(p.relative_to(images / 'public')) for p in (images / 'public').rglob('*') if p.is_file()
            ),
        )
        for name in names:
            self.assertEqual(
                (unset / 'public' / name).read_bytes().replace(str(unset).encode(), b'RUN'),
                (images / 'public' / name).read_bytes().replace(str(images).encode(), b'RUN'),
                name,
            )

    def test_a_ground_truth_run_gets_the_task_and_its_scene_and_is_told_so(self):
        for harness in ('codex', 'claude'):
            run = prepare_run(
                self.root / harness / 'run',
                run_settings_path=run_settings(self.root, 'ground_truth', harness),
            )
            self.assertEqual(observation_mode.of_run(run), 'ground_truth')
            self.assertEqual(verify_inputs(run), [])
            folder = run / ground_truth_files.FOLDER
            self.assertEqual(sorted(p.name for p in folder.iterdir()), ['assets', 'scene.xml', 'task.json'])
            private = json.loads((run / 'private/inputs/task.json').read_text())
            definition = json.loads((folder / 'task.json').read_text())
            for key in ('objects', 'goals', 'mechanism', 'completion', 'arms', 'physics'):
                self.assertEqual(definition[key], private[key], key)
            self.assertTrue(all('position_m' in goal for goal in definition['goals']))
            self.assertFalse(set(definition) & set(ground_truth_files.DROPPED))
            self.assertEqual(definition['scene_asset'], 'scene.xml')
            # The scene is the task's own and loads from the role's folder by itself.
            self.assertEqual(
                (folder / 'scene.xml').read_bytes(), (run / 'private/inputs/scene/scene.xml').read_bytes()
            )
            model = mujoco.MjModel.from_xml_path(str(folder / 'scene.xml'))
            self.assertGreaterEqual(model.key('initial').id, 0)
            self.assertTrue(all(model.body(item['id']).id > 0 for item in definition['objects']))
            self.assertFalse([p for p in folder.rglob('*') if 'hall' in p.name.lower()])
            manifest = json.loads((run / 'private/inputs/manifest.json').read_text())
            self.assertEqual(manifest['observation'], 'ground_truth')
            self.assertIn(ground_truth_files.FOLDER + '/task.json', manifest['input_sha256'])
            self.assertIn(ground_truth_files.FOLDER + '/scene.xml', manifest['input_sha256'])
            task = json.loads((run / 'public/inputs/task.json').read_text())
            for key in ('cameras', 'camera_calibration', 'observation_image', 'initial_reference_images'):
                self.assertNotIn(key, task)
            self.assertFalse([name for name in task['task_materials'] if name.endswith('.png')])
            self.assertTrue(task['observation_contract']['live_object_truth_for_policy'])
            self.assertIs(task['observation_contract']['camera_images'], False)
            self.assertEqual(task['ground_truth']['task'], 'ground-truth/task.json')
            self.assertTrue((run / 'public/inputs' / task['ground_truth']['scene']).is_file())
            rules = (run / 'public/inputs/rules.md').read_text()
            self.assertIn('ground truth instead of camera images', rules)
            self.assertIn(str(run / ground_truth_files.FOLDER), rules)
            self.assertIn('`state {}`', (run / 'public/inputs/guide/tools.md').read_text())
            self.assertIn('ground truth', (run / 'public/inputs/roles/Controller.md').read_text())
            guide = (run / 'public/inputs/task/guide.md').read_text()
            self.assertIn('`state`', guide)
            first = (run / 'private/inputs/bootstrap/Controller.md').read_text()
            self.assertIn('This run has no camera images.', first)
            self.assertIn(str(run / 'public/inputs/ground-truth'), first)
            self.assertNotIn('view_image', first)
            self.assertNotIn('public_image', first)
            for text in (rules, guide, first, (run / 'public/inputs/guide/guide.md').read_text()):
                self.assertNotIn('<!--', text)
            self.assertNotIn('permitted RGB', rules)

    def test_ground_truth_with_the_robot_tool_alone_is_refused_before_anything_is_written(self):
        cfg = json.loads(run_settings(self.root, 'ground_truth').read_text())
        cfg['tools'] = 'robot_only'
        path = self.root / 'both.json'
        path.write_text(json.dumps(cfg))
        with self.assertRaisesRegex(ValueError, 'needs tools = "full"'):
            prepare_run(self.root / 'bad/run', run_settings_path=path)
        with self.assertRaisesRegex(ValueError, 'Unknown observation mode'):
            prepare_run(self.root / 'bad/run', run_settings_path=run_settings(self.root, 'depth'))
        self.assertFalse((self.root / 'bad/run').exists())

    def test_a_task_that_carried_a_code_would_not_be_published(self):
        task = json.loads((ROOT / 'benchmark/dial/dial-small-l1/task.json').read_text())
        ground_truth_files.task_definition(task)
        for extra in ({'code_symbols': [1, 2]}, {'mechanism': {'secret': 3}}, {'dials': [{'password': 1}]}):
            with self.assertRaisesRegex(ValueError, 'private code'):
                ground_truth_files.task_definition({**task, **extra})


class StateWorld(FakeWorld):
    """A fake executor that reports a ground-truth state, to see what the service passes on."""

    def ground_truth_state(self):
        return {'sim_time_s': self.time, 'objects': {}, 'joints': {}, 'evaluator': {'started': True}}


class ServiceTests(unittest.TestCase):
    observation = 'ground_truth'

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.previous = os.environ.pop('ROBOTEAM_POLICY_ENV', None)
        self.run = prepare_run(self.root / 'run', run_settings_path=run_settings(self.root, self.observation))
        self.captured = []

        def capture(cameras):
            self.captured.append(cameras)
            return fake_capture(cameras)

        self.service = RuntimeService(self.run, StateWorld, capture)
        self.n = 0
        self.call('Controller', 'ready')
        self.call('Meta', 'bind', {'actor': 'Controller', 'thread_id': 'parent'})
        self.service.store.observe_session('Controller', 'idle', 'ready', time.time(), 'codex.wait_threads')
        assert self.call('Meta', 'start')['started']

    def tearDown(self):
        if self.service.store:
            self.service.close()
        if self.previous is not None:
            os.environ['ROBOTEAM_POLICY_ENV'] = self.previous
        self.tmp.cleanup()

    def call(self, actor, op, data=None):
        self.n += 1
        if actor != 'Meta':
            check_request(op, data or {})  # As every harness's robot tool does first.
        job = self.service.accept(actor, op, data or {}, 'c' + str(self.n))
        self.service.pump()
        return job['result']

    def images(self):
        return sorted(p.name for p in (self.run / 'public/observations').iterdir())


class GroundTruthServiceTests(ServiceTests):
    def test_observe_returns_robot_feedback_and_no_image(self):
        result = self.call('Controller', 'observe')
        self.assertEqual(sorted(result['observation']), ['captured_at', 'robot', 'sim_time_s'])
        self.assertNotIn('images', json.dumps(result))
        self.assertIn(
            'no camera images', self.call('Controller', 'observe', {'cameras': ['global']})['error']
        )
        self.assertEqual(self.captured, [])
        self.assertEqual(self.images(), [])

    def test_actions_return_no_image_and_refuse_a_camera_selection(self):
        refused = self.call('Controller', 'gripper', {'robot': 'A', 'state': 'open', 'cameras': ['global']})
        self.assertIn('no camera images', refused['error'])
        self.assertEqual(self.service.world.executed, [])
        job = self.service.accept('Controller', 'gripper', {'robot': 'A', 'state': 'open'}, 'move-1')
        self.service.pump()
        self.service.world.complete('A')
        self.service.pump()
        observation = job['result']['observation']
        self.assertEqual(sorted(observation), ['captured_at', 'robot', 'sim_time_s'])
        self.assertEqual(self.captured, [])
        self.assertEqual(self.images(), [])

    def test_meta_gets_the_same_image_free_observation(self):
        result = self.call('Meta', 'observe', {'cameras': ['global']})
        self.assertNotIn('error', result)
        self.assertNotIn('images', result['observation'])
        self.assertEqual(self.captured, [])

    def test_public_image_is_refused_by_the_runtime_and_by_the_robot_tool(self):
        self.assertIn(
            'no camera images', self.call('Controller', 'public_image', {'names': ['task/x.png']})['error']
        )
        bridge = RobotBridge(
            self.run,
            self.run / 'private/state/connections/Controller.json',
            invoke=lambda *a, **k: self.fail('invoked'),
        )
        with self.assertRaisesRegex(ValueError, 'no camera images'):
            bridge.public_images({'names': ['task/x.png']})

    def test_state_returns_the_executors_reading_to_policy_roles_only(self):
        result = self.call('Controller', 'state')
        self.assertEqual(sorted(result['state']), ['evaluator', 'joints', 'objects', 'sim_time_s'])
        self.assertIn('error', self.call('Controller', 'state', {'robot': 'A'}))
        # Meta's `state` is still its administrative snapshot.
        snapshot = self.call('Meta', 'state')
        self.assertIn('lifecycle', snapshot)
        self.assertNotIn('state', snapshot)
        for op in ('bind', 'start', 'resume', 'shutdown'):
            job = self.service.accept('Controller', op, {}, 'admin-' + op)
            self.service.pump()
            self.assertEqual(job['result'].get('error'), 'Meta administrative operation')


class ImagesServiceTests(ServiceTests):
    observation = None

    def test_state_is_refused_and_observe_still_captures(self):
        self.assertEqual(self.call('Controller', 'state').get('error'), 'Unknown tool operation')
        self.assertIn('lifecycle', self.call('Meta', 'state'))
        result = self.call('Controller', 'observe', {'cameras': ['global']})
        self.assertIn('images', result['observation'])
        self.assertEqual(self.captured, [['global']])


@unittest.skipUnless((BUILT / 'hall.json').exists(), 'The built hall is not here (roboteam bootstrap)')
class StateTests(unittest.TestCase):
    """`state` on the real world of a prepared Transport and a prepared Relay case."""

    CASES = ('transport-small-l1', 'relay-small-l1')

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name).resolve()
        previous = os.environ.pop('ROBOTEAM_POLICY_ENV', None)
        try:
            cls.worlds = {}
            for case in cls.CASES:
                run = prepare_case(case, root / case, run_settings(root, 'ground_truth'))
                world = World(run, json.loads((run / 'private/inputs/task.json').read_text()))
                # The evaluator as START attaches it, without the run's recorders.
                world.suite_sampler = Monitor(world)
                # Set everything moving (a test may write the state; `state` never does).
                rng = np.random.default_rng(7)
                world.data.qvel[:] = 0.05 * rng.standard_normal(world.model.nv)
                for _ in range(5):
                    world.step()
                cls.worlds[case] = world
        finally:
            if previous is not None:
                os.environ['ROBOTEAM_POLICY_ENV'] = previous

    @classmethod
    def tearDownClass(cls):
        for world in cls.worlds.values():
            world.close()
        cls.tmp.cleanup()

    def test_objects_are_the_simulators_poses_and_velocities(self):
        for case, world in self.worlds.items():
            model, data = world.model, world.data
            reply = world.ground_truth_state()
            self.assertEqual(reply['sim_time_s'], float(data.time))
            self.assertEqual(sorted(reply['objects']), sorted(o['id'] for o in world.task['objects']))
            for name, item in reply['objects'].items():
                body = model.body(name).id
                velocity = np.zeros(6)
                mujoco.mj_objectVelocity(model, data, mujoco.mjtObj.mjOBJ_BODY, body, velocity, 0)
                self.assertEqual(item['position_m'], data.xpos[body].tolist(), (case, name))
                self.assertEqual(item['quaternion_wxyz'], data.xquat[body].tolist(), (case, name))
                self.assertEqual(item['linear_velocity_m_s'], velocity[3:].tolist(), (case, name))
                self.assertEqual(item['angular_velocity_rad_s'], velocity[:3].tolist(), (case, name))
                # A free body's pose is also its joint's position.
                free = reply['joints'][name + '_free']
                self.assertEqual(free[0][:3], item['position_m'], (case, name))
                self.assertEqual(len(free[0]), 7)
                self.assertEqual(len(free[1]), 6)

    def test_joints_are_the_simulators_by_name(self):
        for case, world in self.worlds.items():
            model, data = world.model, world.data
            reply = world.ground_truth_state()
            # Every joint of the task scene, and none of the hall's.
            self.assertEqual(
                sorted(reply['joints']), sorted(model.joint(j).name for j in range(world.task_scene.njnt))
            )
            moving = 0
            for name, value in reply['joints'].items():
                joint = data.joint(name)
                if len(joint.qpos) == 1:
                    self.assertEqual(value, [float(joint.qpos[0]), float(joint.qvel[0])], (case, name))
                    moving += abs(value[1]) > 1e-4
                else:
                    self.assertEqual(value, [joint.qpos.tolist(), joint.qvel.tolist()], (case, name))
            self.assertGreater(moving, 7, case)
            for robot, arm in world.arms.items():
                for k, address in enumerate(arm.qids):
                    self.assertEqual(reply['joints'][f'{robot}_joint{k + 1}'][0], float(data.qpos[address]))

    def test_the_evaluator_part_is_what_the_evaluator_tracks(self):
        for case, world in self.worlds.items():
            tracked = world.suite_sampler.result()
            shown = world.ground_truth_state()['evaluator']
            self.assertIs(shown['started'], True)
            for key in ('all_goals_met', 'task_success', 'violations', 'process_compliant'):
                self.assertEqual(shown[key], tracked[key], (case, key))
            for key in ('matched_goals', 'total_goals', 'assignments', 'payloads', 'completed_payloads'):
                if key in tracked:
                    self.assertEqual(shown[key], tracked[key], (case, key))
            json.dumps(world.ground_truth_state(), allow_nan=False)
        self.assertIn('assignments', self.worlds['transport-small-l1'].ground_truth_state()['evaluator'])
        self.assertIn('payloads', self.worlds['relay-small-l1'].ground_truth_state()['evaluator'])

    def test_before_start_there_is_no_evaluator_reading(self):
        world = self.worlds['transport-small-l1']
        monitor, world.suite_sampler = world.suite_sampler, None
        try:
            self.assertEqual(world.ground_truth_state()['evaluator'], {'started': False})
        finally:
            world.suite_sampler = monitor

    def test_reading_changes_nothing_in_the_world(self):
        for case, world in self.worlds.items():
            model, data = world.model, world.data
            size = mujoco.mj_stateSize(model, mujoco.mjtState.mjSTATE_INTEGRATION)
            before, after = np.zeros(size), np.zeros(size)
            mujoco.mj_getState(model, data, before, mujoco.mjtState.mjSTATE_INTEGRATION)
            arrays = (
                'qpos',
                'qvel',
                'act',
                'ctrl',
                'qacc',
                'xpos',
                'xquat',
                'cvel',
                'qfrc_applied',
                'xfrc_applied',
            )
            kept = {name: getattr(data, name).copy() for name in arrays}
            colors, t, contacts = model.geom_rgba.copy(), float(data.time), int(data.ncon)
            first = world.ground_truth_state()
            self.assertEqual(world.ground_truth_state(), first, case)
            mujoco.mj_getState(model, data, after, mujoco.mjtState.mjSTATE_INTEGRATION)
            np.testing.assert_array_equal(before, after, case)
            for name, value in kept.items():
                np.testing.assert_array_equal(getattr(data, name), value, (case, name))
            np.testing.assert_array_equal(model.geom_rgba, colors, case)
            self.assertEqual((float(data.time), int(data.ncon)), (t, contacts), case)


def code_patterns(task, code):
    """The code, and the dial positions that are right for it, as a role could meet them in
    text: the symbols in order, and their angles in degrees and radians, with any separators."""
    step = 360 / (task['mechanism']['feedback']['symbol_count'] + 1)
    degrees = [symbol * step for symbol in code]
    signed = [(angle + 180) % 360 - 180 for angle in degrees]

    def whole(values):
        return [re.escape(str(int(round(v)))) + r'(?:\.0+)?' for v in values]

    def fraction(values):
        return [re.escape('%.3f' % (math.floor(abs(v) * 1000) / 1000)) + r'\d*' for v in values]

    sequences = [
        [str(symbol) for symbol in code],
        whole(degrees),
        whole(signed),
        fraction([math.radians(v) for v in degrees]),
        fraction([math.radians(v) for v in signed]),
    ]
    separator = r'[\s,;"\'\[\]]+-?'
    return [re.compile(r'(?<![\d.])' + separator.join(sequence) + r'(?![\d.])') for sequence in sequences]


@unittest.skipUnless((BUILT / 'hall.json').exists(), 'The built hall is not here (roboteam bootstrap)')
class DialSecrecyTests(unittest.TestCase):
    """No role of any run can read a Dial case's code: not in its files, not through `state`,
    not through its sandbox."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name).resolve()
        self.previous = os.environ.pop('ROBOTEAM_POLICY_ENV', None)

    def tearDown(self):
        if self.previous is not None:
            os.environ['ROBOTEAM_POLICY_ENV'] = self.previous
        self.tmp.cleanup()

    def assert_code_absent(self, case, texts, patterns):
        for where, text in texts.items():
            for word in ('code_symbols', 'dial_codes', 'suite-code', 'secret'):
                self.assertNotIn(word, text, (case, where, word))
            for pattern in patterns:
                found = pattern.search(text)
                self.assertIsNone(
                    found, (case, str(where), found and text[max(0, found.start() - 60) : found.end() + 20])
                )

    def test_the_patterns_find_a_code_written_any_usual_way(self):
        task = json.loads((ROOT / 'benchmark/dial/dial-small-l2/task.json').read_text())
        patterns = code_patterns(task, [4, 2, 5, 4])
        for text in (
            '[4, 2, 5, 4]',
            '{"x": [\n  4,\n  2,\n  5,\n  4\n]}',
            'code="4 2 5 4"',
            '[240.0, 120.0, 300.0, 240.0]',
            '[-120, 120, -60, -120]',
            json.dumps([math.radians(v) for v in (240, 120, 300, 240)]),
            json.dumps([math.radians(v) for v in (-120, 120, -60, -120)]),
        ):
            self.assertTrue(any(p.search(text) for p in patterns), text)
        for text in ('[4, 2, 5, 3]', 'rgba="0.4 2 5 4"', '[14, 2, 5, 4]', '4 2 5 40'):
            self.assertFalse(any(p.search(text) for p in patterns), text)

    def test_no_public_file_state_reply_or_readable_path_holds_the_code(self):
        self.assertEqual(len(DIAL_CASES), 9)
        for case in DIAL_CASES:
            code = dial_code(case)
            for observation in ('ground_truth', 'images'):
                run = prepare_case(case, self.root / observation / case, run_settings(self.root, observation))
                task = json.loads((run / 'private/inputs/task.json').read_text())
                patterns = code_patterns(task, code)
                stored = json.loads((run / 'private/inputs/suite-code.json').read_text())
                self.assertEqual(stored, {'code_symbols': code})
                self.assertTrue(any(p.search(json.dumps(stored)) for p in patterns))
                texts = public_texts(run)
                self.assertIn(run / 'public/inputs/task.json', texts)
                self.assertEqual(
                    (run / ground_truth_files.FOLDER / 'task.json') in texts, observation == 'ground_truth'
                )
                self.assert_code_absent(case, texts, patterns)
                # Nothing under public/ is, or points at, a private file.
                for path in (run / 'public').rglob('*'):
                    self.assertFalse(path.is_symlink(), path)
                    self.assertNotIn(path.name, ('suite-code.json', 'release.json'), path)
                # The sandbox: the code's two homes and the run's private folder are closed.
                table = json.loads((run / 'private/inputs/policy-access.json').read_text())['filesystem']
                for closed in (
                    run / 'private/inputs/suite-code.json',
                    run / 'private/inputs/release.json',
                    run / 'private/inputs/task.json',
                    ROOT / RELEASE,
                ):
                    self.assertEqual(policy_access.mode(table, closed), 'deny', (case, closed))
                self.assertEqual(policy_access.mode(table, run / 'public/inputs/task.json'), 'read')
                if observation != 'ground_truth':
                    continue
                world = World(run, task)
                try:
                    world.suite_sampler = Monitor(world, secret=code)
                    for _ in range(3):
                        world.step()
                    reply = world.ground_truth_state()
                    for dial in task['dials']:
                        self.assertEqual(
                            reply['joints'][dial['id'] + '_hinge'][0],
                            float(world.data.joint(dial['id'] + '_hinge').qpos[0]),
                        )
                    self.assertEqual(
                        reply['evaluator']['display'],
                        {'value': 0, 'mode': 'best_so_far', 'status': 'invalid'},
                    )
                    self.assert_code_absent(
                        case,
                        {'state': json.dumps(reply), 'state indented': json.dumps(reply, indent=2)},
                        patterns,
                    )
                finally:
                    world.close()

    def test_state_shows_the_display_and_nothing_that_depends_on_which_dial_is_right(self):
        case = 'dial-small-l1'
        run = prepare_case(case, self.root / case, run_settings(self.root, 'ground_truth'))
        task = json.loads((run / 'private/inputs/task.json').read_text())
        world = World(run, task)
        try:
            step = math.radians(360 / (task['mechanism']['feedback']['symbol_count'] + 1))
            guess = [1, 2, 3, 4]
            replies = []
            # Two codes that agree with the guess on one dial each, a different dial.
            for code in ([1, 5, 5, 5], [5, 5, 5, 4]):
                world.suite_sampler = monitor = Monitor(world, secret=code)
                world.step()
                for k in range(30):  # Held long enough to count as one valid trial.
                    monitor.game.update(
                        float(world.data.time) + 0.02 * k, [s * step for s in guess], [0] * 4, True
                    )
                self.assertEqual((monitor.game.best, monitor.game.queries), (1, 1))
                replies.append(ground_truth.evaluator(world))
            for reply in replies:
                reply.pop('sim_time_s')
            self.assertEqual(replies[0], replies[1])
            self.assertEqual(replies[0]['display'], {'value': 1, 'mode': 'best_so_far', 'status': 'ready'})
            self.assertIs(replies[0]['solved'], False)
            # Exactly these fields; a new one has to be added on purpose.
            self.assertEqual(
                sorted(replies[0]),
                sorted(
                    [
                        'started',
                        'display',
                        'solved',
                        'valid_trials',
                        'process_compliant',
                        'violations',
                        'inter_robot_contacts',
                        'self_contacts',
                        'support_ready',
                        'red_hold_ready',
                        'clearance_m',
                    ]
                ),
            )
            text = json.dumps(world.ground_truth_state())
            for word in ('private', 'secret', 'input_symbols', 'best_count', 'correct'):
                self.assertNotIn(word, text)
        finally:
            world.close()


if __name__ == '__main__':
    unittest.main()
