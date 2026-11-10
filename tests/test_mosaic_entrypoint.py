import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch


class EntrypointTests(unittest.TestCase):
    def test_selection_rejects_mismatched_catalog_task_or_scene_before_world_creation(self):
        from robofrontier.oracle import run_mosaic_oracle as entry
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);scene=root/'scene';scene.mkdir()
            xml=b'<mujoco/>';(scene/'scene.xml').write_bytes(xml)
            task={'id':'mosaic-example','family':'mosaic','scene_sha256':hashlib.sha256(xml).hexdigest(),
                  'scale':{'scene_revision':14}}
            catalog={'scene_revision':14,'cases':[{'id':task['id'],'family':'mosaic',
                      'scene_revision':14,'directory':'scene'}]}
            path=root/'catalog.json';path.write_text(json.dumps(catalog))
            (scene/'task.json').write_text(json.dumps(task))
            with patch.object(entry,'ROOT',root):
                self.assertEqual(entry.selected_scene(path,task['id'])[2],14)
                with self.assertRaisesRegex(ValueError,'known Mosaic'):
                    entry.selected_scene(path,'missing')
                for changed,pattern in [({'scene_sha256':'wrong'},'physical scene identity'),
                                        ({'scale':{'scene_revision':15}},'scene revisions')]:
                    (scene/'task.json').write_text(json.dumps({**task,**changed}))
                    with self.assertRaisesRegex(ValueError,pattern):
                        entry.selected_scene(path,task['id'])
                (scene/'task.json').write_text(json.dumps(task))
                catalog['scene_revision']=15;path.write_text(json.dumps(catalog))
                with self.assertRaisesRegex(ValueError,'selected scene revision'):
                    entry.selected_scene(path,task['id'])

    def test_script_imports_its_own_checkout_from_another_directory(self):
        root = Path(__file__).resolve().parents[1]
        env = dict(os.environ)
        env.pop('PYTHONPATH', None)
        script = root / 'robofrontier/oracle/run_mosaic_oracle.py'
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.check_output(
                [sys.executable, '-c',
                 'import runpy,sys; d=runpy.run_path(sys.argv[1]); print(d["ROOT"])',
                 str(script)], cwd=directory, env=env, text=True)
        self.assertEqual(Path(result.strip()), root)

    def test_physics_thread_pool_is_explicit_and_recorded(self):
        from robofrontier.oracle.run_mosaic_oracle import configure_physics_threads
        trial = SimpleNamespace(data=object())
        with patch('mujoco.mju_threadpool') as attach:
            self.assertEqual(configure_physics_threads(trial, 0)['engine_worker_threads'], 0)
            attach.assert_not_called()
            self.assertEqual(configure_physics_threads(trial, 4)['engine_worker_threads'], 4)
            attach.assert_called_once_with(trial.data, 4)
            with self.assertRaises(ValueError):
                configure_physics_threads(trial, -1)


if __name__ == '__main__':
    unittest.main()
