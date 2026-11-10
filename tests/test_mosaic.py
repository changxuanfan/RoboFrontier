"""The Mosaic variant builder uses the selected grid geometry."""
from collections import Counter
import unittest

from robofrontier.mosaic import ROOT, runtime_task, scene_directory, specification


class MosaicTests(unittest.TestCase):
    def test_eight_by_eight_inventory_and_goal_geometry(self):
        env,draft=specification(8)
        counts={'blue':24,'yellow':26,'white':8,'red':6}
        self.assertEqual(Counter(o['color'] for o in env['objects']),counts)
        self.assertEqual(Counter(g['color'] for g in draft['goal_cells']),counts)
        self.assertEqual(len(draft['goal_cells']),64)
        self.assertEqual(draft['goal_cells'][0]['cube_center_world_m'],[-.14,.14,.42])
        self.assertEqual(draft['goal_cells'][-1]['cube_center_world_m'],[.14,-.14,.42])
        task=runtime_task(env,draft,'scene-hash')
        self.assertEqual(task['scene_asset'],str(scene_directory(8).relative_to(ROOT)))
        self.assertNotEqual(task['scene_asset'],str(scene_directory(10).relative_to(ROOT)))
        self.assertEqual(len({g['goal_id'] for g in task['shared_goals']}),64)
        self.assertEqual(task['completion'],runtime_task(*specification(10),'scene-hash')['completion'])

    def test_unsupported_size_is_rejected(self):
        with self.assertRaises(ValueError):specification(9)

    def test_seven_by_seven_rocket_has_independent_geometry_and_explicit_objective(self):
        env,draft=specification(7)
        counts={'white':18,'red':15,'blue':11,'yellow':5}
        self.assertEqual(Counter(o['color'] for o in env['objects']),counts)
        self.assertEqual(Counter(g['color'] for g in draft['goal_cells']),counts)
        self.assertEqual(len(draft['goal_cells']),49)
        self.assertEqual(draft['goal_cells'][0]['cube_center_world_m'],[-.12,.12,.42])
        self.assertEqual(draft['goal_cells'][-1]['cube_center_world_m'],[.12,-.12,.42])
        task=runtime_task(env,draft,'scene-hash')
        self.assertEqual(task['execution_objective'],draft['execution_objective'])
        self.assertEqual(task['scene_asset'],str(scene_directory(7).relative_to(ROOT)))
        self.assertEqual(task['completion'],runtime_task(*specification(10),'scene-hash')['completion'])

    def test_recessed_variant_keeps_stock_and_pattern_but_changes_real_goal_geometry(self):
        flat,old=specification(7);env,draft=specification(7,recessed=True)
        self.assertEqual(env['objects'],flat['objects'])
        self.assertEqual(draft['matrix_codes'],old['matrix_codes'])
        grid=env['grid'];fixture=grid['fixture']
        self.assertAlmostEqual(fixture['depth_m'],grid['cube_side_m']/3)
        self.assertAlmostEqual(grid['cell_side_m'],fixture['opening_side_m']+fixture['wall_thickness_m'])
        self.assertGreater(fixture['opening_side_m'],grid['cube_side_m'])
        for g in draft['goal_cells']:
            self.assertAlmostEqual(g['cube_center_world_m'][2],fixture['floor_z_m']+grid['cube_side_m']/2)
        task=runtime_task(env,draft,'scene-hash')
        self.assertEqual(task['scene_asset'],str(scene_directory(7,True).relative_to(ROOT)))
        self.assertNotEqual(task['id'],runtime_task(flat,old,'scene-hash')['id'])

    def test_six_by_six_reference_has_36_cubes_and_50mm_openings(self):
        env,draft=specification(6,True)
        self.assertEqual(draft['matrix_codes'],['WWRRWW','WRRRRW','WBRRBW','BBYYBB','BRYYRB','RYYYYR'])
        self.assertEqual(Counter(o['color'] for o in env['objects']),{'red':12,'blue':8,'yellow':8,'white':8})
        self.assertEqual(len(draft['goal_cells']),36)
        self.assertEqual(env['grid']['fixture']['opening_side_m'],.05)
        self.assertAlmostEqual(env['grid']['cell_side_m'],.051)
        self.assertEqual(draft['goal_cells'][0]['cube_center_world_m'][:2],[-.1275,.1275])
        self.assertEqual(draft['goal_cells'][-1]['cube_center_world_m'][:2],[.1275,-.1275])
        task=runtime_task(env,draft,'scene-hash')
        self.assertEqual(task['scene_asset'],str(scene_directory(6,True).relative_to(ROOT)))
        self.assertNotEqual(task['scene_asset'],str(scene_directory(7,True).relative_to(ROOT)))


if __name__=='__main__':unittest.main()
