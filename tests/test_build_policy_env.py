import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

from robofrontier import policy_env
from scripts import build_policy_env


def fake_install(target):
    (target/'python').mkdir()
    time.sleep(0.3)  # Long enough for a concurrent build to arrive mid-install.
    (target/'python/file').write_text('x')
    (target/policy_env.MANIFEST).write_text(json.dumps({'built': True}))


def fake_verify(target):
    if not (Path(target)/'python/file').is_file():
        raise ValueError('incomplete environment')


class BuildPolicyEnvTests(unittest.TestCase):
    def test_concurrent_builds_of_one_identity_do_not_delete_each_other(self):
        with tempfile.TemporaryDirectory() as base, \
                mock.patch.object(build_policy_env, 'install', side_effect=fake_install) as install, \
                mock.patch.object(policy_env, 'verify', side_effect=fake_verify):
            results, errors = [], []
            def worker():
                try:
                    results.append(build_policy_env.build(base))
                except Exception as error:
                    errors.append(error)
            threads = [threading.Thread(target=worker) for _ in range(2)]
            for thread in threads:
                thread.start()
                time.sleep(0.05)
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(len(set(results)), 1)
            self.assertEqual(install.call_count, 1)

    def test_a_build_that_fails_verification_leaves_no_manifest(self):
        def broken(target):
            (target/policy_env.MANIFEST).write_text('{}')
        with tempfile.TemporaryDirectory() as base, \
                mock.patch.object(build_policy_env, 'install', side_effect=broken), \
                mock.patch.object(policy_env, 'verify', side_effect=fake_verify):
            with self.assertRaises(ValueError):
                build_policy_env.build(base)
            target = Path(base)/('policy-env-' + build_policy_env.identity())
            self.assertFalse((target/policy_env.MANIFEST).exists())


if __name__ == '__main__':
    unittest.main()
