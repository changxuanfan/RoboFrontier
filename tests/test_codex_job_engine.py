import json
from pathlib import Path
import tempfile
import unittest

from robofrontier.codex.job_engine import build_manifest
from robofrontier.run_setup import write_json


class JobManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='rfe-', dir='/tmp')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.private, self.store = self.root/'engine', self.root/'credentials'
        self.jobs = []
        for i in range(2):
            run = self.root/'runs'/str(i)
            write_json(run/'private/inputs/models.json', {'models': []})
            write_json(run/'private/inputs/policy-access.json', {'network': False, 'filesystem': {
                '/': 'read', str(self.root): 'deny', str(run): 'read', str(run/'private'): 'deny',
                str(run/'workspace'): 'write', str(self.private): 'deny', str(self.store): 'deny',
                '/proc': 'deny', '/dev': 'deny'}})
            write_json(run/'private/inputs/codex.json', {'model': 'gpt-6-luna', 'provider': 'managed', 'effort': 'high',
                'model_catalog': str(run/'private/inputs/models.json'), 'tool_backend': 'landlock-v1',
                'profile': {'provider': 'openai', 'runner_backend': 'slurm-managed-v1'},
                'args': ['-c', 'model="gpt-6-luna"', '-c', 'default_permissions="robofrontier"',
                         '-c', 'permissions.robofrontier.filesystem={"/"="read"}',
                         '-c', 'model_catalog_json='+json.dumps(str(run/'private/inputs/models.json'))]})
            self.jobs.append({'run_directory': str(run)})

    def build(self):
        return build_manifest(self.jobs, self.private/'control', self.private, self.store)

    def test_shared_engine_has_independent_profiles_and_no_union_default(self):
        manifest = self.build()
        self.assertEqual(len({t['permissions'] for t in manifest['tasks']}), 2)
        self.assertIn('default_permissions="rf_closed"', manifest['args'])
        self.assertNotIn('default_permissions="robofrontier"', manifest['args'])
        self.assertTrue(all(t['model'] == 'gpt-6-luna' for t in manifest['tasks']))

    def test_readable_credential_control_device_or_other_task_path_blocks_admission(self):
        path = Path(self.jobs[0]['run_directory'])/'private/inputs/policy-access.json'
        original = json.loads(path.read_text())
        for forbidden in (str(self.private), str(self.store), '/proc', '/dev', self.jobs[1]['run_directory']):
            access = json.loads(json.dumps(original))
            access['filesystem'][forbidden] = 'read'
            write_json(path, access)
            with self.subTest(path=forbidden), self.assertRaises(ValueError):
                self.build()

    def test_mixed_model_catalogs_cannot_share_a_native_process(self):
        path = Path(self.jobs[1]['run_directory'])/'private/inputs/models.json'
        write_json(path, {'models': ['different']})
        with self.assertRaisesRegex(ValueError, 'one exact'):
            self.build()
