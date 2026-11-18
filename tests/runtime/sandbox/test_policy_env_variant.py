"""The policy environment variant with a simulator, which only a ground_truth run uses."""

import json
import os
import re
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roboteam.runtime.run.setup import prepare_run
from roboteam.runtime.sandbox import policy_env
from roboteam.tasks.config import ROOT, load_run_settings
from scripts.release import build_policy_env, check_policy_env


def locked(name):
    """Package names pinned by a lock file."""
    text = (policy_env.CONFIG / name).read_text()
    return {re.sub(r'[-_.]+', '-', n).lower() for n in re.findall(r'^([A-Za-z0-9_.-]+)==', text, re.M)}


def fake_environment(folder, variant=None, name='policy-env-fake'):
    root = Path(folder) / name
    (root / 'python/bin').mkdir(parents=True)
    (root / 'wheels').mkdir()
    (root / 'python/bin/python3').write_text('fake')
    manifest = {
        'schema': policy_env.SCHEMA,
        'id': root.name,
        'python': '3.12.16',
        'bin': 'python/bin',
        'core': ['numpy'],
        'store': ['networkx'],
        'packages': {'numpy': '2.5.4'},
        **({'variant': variant} if variant else {}),
    }
    manifest['tree_sha256'] = policy_env.tree_sha256(root)
    (root / policy_env.MANIFEST).write_text(json.dumps(manifest))
    policy_env.receipt_path(root).write_text(
        json.dumps(
            {
                'schema': policy_env.RECEIPT_SCHEMA,
                'passed': True,
                'tree_sha256': manifest['tree_sha256'],
                'checked': [],
            }
        )
    )
    return root


class LockTests(unittest.TestCase):
    def test_only_the_variant_lock_holds_the_simulator(self):
        self.assertIn('mujoco', locked('mujoco.lock'))
        for name in ('core.lock', 'all.lock'):
            self.assertFalse(locked(name) & set(build_policy_env.FORBIDDEN), name)
        self.assertEqual(build_policy_env.names(policy_env.CONFIG / 'mujoco.in'), ['mujoco'])

    def test_the_simulator_is_the_version_the_benchmark_runs_on(self):
        own = re.search(r'name = "mujoco"\nversion = "([^"]+)"', (ROOT / 'uv.lock').read_text()).group(1)
        self.assertIn('mujoco==' + own + ' ', (policy_env.CONFIG / 'mujoco.lock').read_text())
        self.assertIn('mujoco==' + own, (policy_env.CONFIG / 'mujoco.in').read_text())

    def test_every_variant_package_is_hash_locked_at_the_shared_versions(self):
        text = (policy_env.CONFIG / 'mujoco.lock').read_text()
        pins = re.findall(
            r'^([A-Za-z0-9_.-]+)==(\S+) \\\n((?:    --hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)', text, re.M
        )
        self.assertEqual(len(pins), len(re.findall(r'^\S+==', text, re.M)))
        shared = dict(
            re.findall(r'^([A-Za-z0-9_.-]+)==(\S+) \\$', (policy_env.CONFIG / 'all.lock').read_text(), re.M)
        )
        for name, version, _ in pins:
            if name in shared:
                self.assertEqual(version, shared[name], name)


class IdentityTests(unittest.TestCase):
    def test_the_ordinary_identity_does_not_depend_on_the_variant(self):
        before = policy_env.identity()
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'policy-env'
            shutil.copytree(policy_env.CONFIG, config)
            with patch.object(policy_env, 'CONFIG', config):
                self.assertEqual(policy_env.identity(), before)
                variant = policy_env.identity('mujoco')
                (config / 'mujoco.lock').write_text('changed\n')
                self.assertEqual(policy_env.identity(), before)
                self.assertNotEqual(policy_env.identity('mujoco'), variant)
                (config / 'mujoco.lock').unlink()
                (config / 'mujoco.in').unlink()
                self.assertEqual(policy_env.identity(), before)
        self.assertNotEqual(policy_env.identity('mujoco'), before)
        self.assertEqual(policy_env.folder_name(), 'policy-env-' + before)
        self.assertEqual(
            policy_env.folder_name('mujoco'), 'policy-env-mujoco-' + policy_env.identity('mujoco')
        )
        with self.assertRaisesRegex(ValueError, 'Unknown policy environment variant'):
            policy_env.identity('pybullet')

    def test_the_build_names_and_allows_only_the_variant_package(self):
        self.assertEqual(policy_env.variant_files(None), ())
        self.assertEqual(policy_env.variant_files('mujoco'), ('mujoco.in', 'mujoco.lock'))
        self.assertIn('mujoco', build_policy_env.FORBIDDEN)


class SelectionTests(unittest.TestCase):
    def setUp(self):
        # Outside /tmp, where Linux refuses a run with an environment.
        outside = (
            '/var/tmp'
            if Path(tempfile.gettempdir()).resolve().is_relative_to(Path('/tmp').resolve())
            else None
        )
        folder = tempfile.TemporaryDirectory(dir=outside)
        self.addCleanup(folder.cleanup)
        self.tmp = Path(folder.name).resolve()

    def test_the_default_of_each_kind_of_run_is_its_own_build(self):
        ordinary = fake_environment(self.tmp, name=policy_env.folder_name())
        simulator = fake_environment(self.tmp, 'mujoco', name=policy_env.folder_name('mujoco'))
        with patch.object(policy_env.os, 'environ', {policy_env.BASE_VAR: str(self.tmp)}):
            self.assertEqual(policy_env.default_root(), ordinary)
            self.assertEqual(policy_env.default_root('mujoco'), simulator)
        environment = {policy_env.BASE_VAR: str(self.tmp)}
        with patch.object(policy_env.os, 'environ', environment):
            self.assertEqual(policy_env.apply_default('mujoco'), simulator)
            self.assertEqual(environment[policy_env.ENV_VAR], str(simulator))

    def test_a_missing_variant_build_names_its_build_command(self):
        fake_environment(self.tmp, name=policy_env.folder_name())
        with patch.object(policy_env.os, 'environ', {policy_env.BASE_VAR: str(self.tmp)}):
            with self.assertRaisesRegex(ValueError, 'not built.*--variant mujoco'):
                policy_env.default_root('mujoco')

    def test_an_environment_of_the_other_kind_is_refused(self):
        ordinary = fake_environment(self.tmp, name='ordinary')
        simulator = fake_environment(self.tmp, 'mujoco', name='simulator')
        policy_env.require_variant(ordinary, None)
        policy_env.require_variant(simulator, 'mujoco')
        with self.assertRaisesRegex(ValueError, 'needs the mujoco variant'):
            policy_env.require_variant(ordinary, 'mujoco')
        with self.assertRaisesRegex(ValueError, 'needs the ordinary environment'):
            policy_env.require_variant(simulator, None)

    def test_only_the_variant_searches_the_folder_its_import_needs(self):
        ordinary = fake_environment(self.tmp, name='ordinary')
        simulator = fake_environment(self.tmp, 'mujoco', name='simulator')
        run = self.tmp / 'run'
        self.assertEqual(
            policy_env.variables(ordinary, run)['PATH'], str(ordinary / 'python/bin') + ':/usr/bin:/bin'
        )
        self.assertEqual(
            policy_env.variables(simulator, run)['PATH'],
            str(simulator / 'python/bin') + ':/usr/bin:/bin:/usr/sbin',
        )

    def prepare(self, environment, observation):
        cfg = load_run_settings()
        if observation:
            cfg['observation'] = observation
        path = self.tmp / ('run-%s.json' % observation)
        path.write_text(json.dumps(cfg))
        target = self.tmp / ('%s-%s' % (environment.name, observation)) / 'run'
        with patch.dict(os.environ, {policy_env.ENV_VAR: str(environment)}):
            return prepare_run(target, run_settings_path=path)

    def test_preparing_a_run_admits_only_its_own_kind(self):
        ordinary = fake_environment(self.tmp, name='ordinary')
        simulator = fake_environment(self.tmp, 'mujoco', name='simulator')
        with self.assertRaisesRegex(ValueError, 'needs the mujoco variant'):
            self.prepare(ordinary, 'ground_truth')
        with self.assertRaisesRegex(ValueError, 'needs the ordinary environment'):
            self.prepare(simulator, None)
        for environment, observation in ((ordinary, None), (simulator, 'ground_truth')):
            run = self.prepare(environment, observation)
            access = json.loads((run / 'private/inputs/policy-access.json').read_text())
            self.assertEqual(access['policy_env']['root'], str(environment))


class CheckTests(unittest.TestCase):
    def test_the_simulator_must_work_only_in_the_variant(self):
        good = {
            **dict.fromkeys(check_policy_env.MUST_WORK, 'ok'),
            **dict.fromkeys(check_policy_env.MUST_FAIL, 'denied'),
        }
        self.assertEqual(check_policy_env.differences(good), [])
        self.assertEqual(
            check_policy_env.differences(good, variant='mujoco'),
            ['import_mujoco should work', 'mujoco_simulates should work'],
        )
        simulator = {**good, 'import_mujoco': 'ok', 'mujoco_simulates': 'ok'}
        self.assertEqual(check_policy_env.differences(simulator, variant='mujoco'), [])
        self.assertEqual(
            check_policy_env.differences(simulator),
            ['import_mujoco should be denied', 'mujoco_simulates should be denied'],
        )
        # The variant still installs nothing that is not in its store, and stays as closed.
        self.assertEqual(
            check_policy_env.differences({**simulator, 'pip_install_absent_package': 'ok'}, variant='mujoco'),
            ['pip_install_absent_package should be denied'],
        )
        self.assertEqual(
            check_policy_env.differences({**simulator, 'read_private': 'ok'}, variant='mujoco'),
            ['read_private should be denied'],
        )
        self.assertNotEqual(check_policy_env.ABSENT_PACKAGE['mujoco'], 'mujoco')


if __name__ == '__main__':
    unittest.main()
