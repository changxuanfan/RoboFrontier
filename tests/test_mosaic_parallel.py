import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import mujoco
import numpy as np

from robofrontier.physics.robot_control import PandaArm
from robofrontier.oracle import mosaic_parallel, placement as placement_oracle
from robofrontier.oracle.mosaic import goal_endpoint_candidates, pickup_endpoint_candidates


class ParallelCoverageTests(unittest.TestCase):
    def test_worker_initialization_failure_is_reported_by_the_work_item(self):
        mosaic_parallel._initialize('/nonexistent/mosaic-scene.xml', {}, {})
        with self.assertRaisesRegex(RuntimeError, 'worker initialization failed'):
            mosaic_parallel._screen({'goal_id': 'example'})

    def test_parallel_matches_original_nominal_coverage_on_r14_scene(self):
        root=Path(__file__).resolve().parents[1]
        folder=root/'benchmark/mosaic/mosaic-a04-6x12-d1'
        if not (folder/'assets').exists():
            self.skipTest('R14 scene assets not materialized')
        task=json.loads((folder/'task.json').read_text())
        env=json.loads((folder/'environment.json').read_text())
        model=mujoco.MjModel.from_xml_path(str(folder/'scene.xml'))
        data=mujoco.MjData(model)
        mujoco.mj_resetDataKeyframe(model,data,model.key('initial').id)
        mujoco.mj_forward(model,data)
        arms={name:PandaArm(model,data,name) for name in task['arms']}
        home={name:arm.qref.copy() for name,arm in arms.items()}
        mosaic_parallel._initialize(str(folder/'scene.xml'),task,
                                    {name:arm.qref.tolist() for name,arm in arms.items()},
                                    env,data.qpos.copy(),home)
        expected=placement_oracle.goal_coverage(mosaic_parallel._scratch)
        expected_pickups=pickup_endpoint_candidates(mosaic_parallel._scratch)
        with TemporaryDirectory() as temp:
            directory=Path(temp)
            (directory/'scene.xml').symlink_to(folder/'scene.xml')
            (directory/'assets').symlink_to(folder/'assets',target_is_directory=True)
            trial=SimpleNamespace(task=task,env=env,data=data,home_q=home,arms=arms,directory=directory,
                                  check_stop=Mock(),_heartbeat=Mock())
            actual=mosaic_parallel.nominal_goal_coverage(trial,4)
            self.assertEqual(expected,actual)
            status=json.loads((directory/'planning-status.json').read_text())
            self.assertEqual(status['phase'],'goal_endpoints')
            self.assertEqual(status['state'],'complete')
            self.assertEqual(status['completed'],len(task['goals']))
            self.assertEqual(expected_pickups,mosaic_parallel.pickup_coverage(trial,4))
            status=json.loads((directory/'planning-status.json').read_text())
            self.assertEqual(status['phase'],'pickup_endpoints')
            self.assertEqual(status['state'],'complete')
            self.assertEqual(status['completed'],len(env['objects']))
            self.assertIn(status['last_completed_item'],{item['id'] for item in env['objects']})
            self.assertTrue(np.array_equal(data.qpos,model.key_qpos[model.key('initial').id]))

    def test_nominal_failure_reuses_original_fallback(self):
        trial=SimpleNamespace(mosaic_planning_workers=4,task={'goals':[]},arms={})
        with patch('robofrontier.oracle.mosaic_parallel.nominal_goal_coverage',return_value=None), \
             patch('robofrontier.oracle.mosaic.helpers.goal_coverage') as coverage:
            self.assertEqual(goal_endpoint_candidates(trial),{})
            coverage.assert_not_called()


if __name__=='__main__':unittest.main()
