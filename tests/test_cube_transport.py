"""Offline asset contracts; no agents, dispatcher or action server."""
from collections import Counter
import copy
import unittest

import mujoco
import numpy as np

from robofrontier.cube_transport import (ROOT, COLLECTION, layout, make_task, evaluate_placement_window,
                                        match_placement_sample, route)


class CubeTransportTests(unittest.TestCase):
    def test_inventory_and_topology_all_sizes(self):
        for n in range(3, 13):
            env = layout(n)
            self.assertEqual(len(env['stations']), n)
            self.assertEqual(len(env['objects']), 3*n)
            self.assertEqual(set(Counter(o['source'] for o in env['objects']).values()), {3})
            self.assertEqual(len(env['edges']), n if n > 3 else n-1)
            self.assertLessEqual(len({o['color'] for o in env['objects']}), 6)
            self.assertEqual(sum(o['shape'] == 'cylinder' for o in env['objects']), 3*max(0, n-6))
            self.assertTrue(all('pattern' not in o for o in env['objects']))
            adjacency = {frozenset(e['stations']) for e in env['edges']}
            for a in env['stations']:
                for b in env['stations']:
                    r = route(a['id'], b['id'], n, env['topology'])
                    self.assertEqual((r[0], r[-1]), (a['id'], b['id']))
                    self.assertEqual(len(r), len(set(r)))
                    self.assertTrue(all(frozenset(pair) in adjacency for pair in zip(r, r[1:])))

    def test_seed_reproducibility(self):
        env = layout(8)
        self.assertEqual(make_task(env, 2), make_task(env, 2))
        self.assertNotEqual(make_task(env, 1)['orders'], make_task(env, 2)['orders'])

    def test_loadable_reset_keyframe_at_both_scale_endpoints(self):
        for n in (3, 12):
            env = layout(n)
            model = mujoco.MjModel.from_xml_path(str(ROOT/f"configs/environments/{COLLECTION}/{env['id']}/scene.xml"))
            self.assertEqual(model.nu, 8*n)
            self.assertEqual(model.nq, 9*n+7*3*n)
            data = mujoco.MjData(model)
            mujoco.mj_resetDataKeyframe(model, data, model.key('initial').id)
            mujoco.mj_forward(model, data)
            for station in env['stations']:
                np.testing.assert_allclose(data.site(station['id']+'_tcp').xpos, station['home_tcp_m'], atol=.002)
            for obj in env['objects']:
                np.testing.assert_allclose(data.body(obj['id']).xpos, obj['initial_position_m'], atol=1e-9)

    def test_semantic_evaluator_accepts_swaps_and_rejects_held_or_wrong_type(self):
        env = layout(3); task = make_task(env, 0)
        states = {}
        pools = {}
        for obj in env['objects']:
            pools.setdefault((obj['color'], obj['shape']), []).append(obj['id'])
        for goals in task['orders'].values():
            for goal in goals:
                name = pools[tuple(goal['requires'][k] for k in ('color', 'shape'))].pop(0)
                states[name] = {'position_m': goal['position_m'], 'linear_velocity_m_s': [0, 0, 0],
                                'table_supported': True, 'released': True}
        self.assertEqual(match_placement_sample(env, task, states)['matched_goals'], 9)
        states['A_item1'], states['A_item3'] = states['A_item3'], states['A_item1']
        self.assertEqual(match_placement_sample(env, task, states)['matched_goals'], 9)
        states['A_item1']['released'] = False
        self.assertEqual(match_placement_sample(env, task, states)['matched_goals'], 8)
        states['A_item1']['released'] = True
        states['A_item1'], states['B_item1'] = states['B_item1'], states['A_item1']
        self.assertEqual(match_placement_sample(env, task, states)['matched_goals'], 7)

    def test_semantic_evaluator_never_counts_one_object_twice(self):
        env = layout(3); task = make_task(env, 0)
        goal = task['orders']['A'][0]
        duplicate = copy.deepcopy(goal); duplicate['goal_id'] = 'second_goal'
        task['orders'] = {'A': [goal, duplicate]}
        states = {'A_item2': {'position_m': goal['position_m'], 'linear_velocity_m_s': [0, 0, 0],
                              'table_supported': True, 'released': True}}
        self.assertEqual(match_placement_sample(env, task, states)['matched_goals'], 1)

    def test_stable_window_requires_duration_density_and_continuous_placement(self):
        env = layout(3); task = make_task(env, 0)
        goal = task['orders']['A'][0]; task['orders'] = {'A': [goal]}
        states = {'A_item2': {'position_m': goal['position_m'], 'linear_velocity_m_s': [0, 0, 0],
                              'table_supported': True, 'released': True}}
        samples = [{'time_s': i*.02, 'objects': copy.deepcopy(states)} for i in range(51)]
        self.assertTrue(evaluate_placement_window(env, task, samples)['complete'])
        self.assertFalse(evaluate_placement_window(env, task, samples[1:])['complete'])
        self.assertFalse(evaluate_placement_window(env, task, samples[::2])['complete'])
        samples[25]['objects']['A_item2']['released'] = False
        self.assertFalse(evaluate_placement_window(env, task, samples)['complete'])
        with self.assertRaises(ValueError):
            evaluate_placement_window(env, task, list(reversed(samples)))


if __name__ == '__main__':
    unittest.main()
