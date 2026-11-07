"""Regression: unspecified source PBR must not become glossy plastic."""
import unittest
import json
import numpy as np
from scripts.factory_blender_materials import resolve, robot_role, task_role


class MaterialChecks(unittest.TestCase):
    def test_relay_timber_is_painted_wood_at_every_level(self):
        for part in ('beam', 'beam_surface', 'beam_segment0', 'beam_segment1'):
            self.assertEqual(task_role(dict(name=f'relay-a08-d2__payload_01_{part}')), 'painted_wood')
        self.assertIsNone(task_role(dict(name='relay-a08-d3__payload_01_hinge_housing')))

    def test_recorded_pose_updates_each_changed_geom_independently(self):
        from types import SimpleNamespace
        from scripts.factory_blender_materials import apply_recorded_appearance
        def obj():
            return SimpleNamespace(material_slots=[SimpleNamespace(material='initial')])
        first, second, unchanged = obj(), obj(), obj()
        original = dict(material=4, rgba=[0., 0., 0., 1.])
        make = lambda spec: tuple(spec['rgba'])
        apply_recorded_appearance(first, original, [.1, .2, .3, 1.], make)
        apply_recorded_appearance(second, original, [.4, .5, .6, 0.], make)
        apply_recorded_appearance(unchanged, original, [0., 0., 0., 1.], make)
        self.assertEqual(first.material_slots[0].material, (.1, .2, .3, 1.))
        self.assertEqual(second.material_slots[0].material, (.4, .5, .6, 0.))
        self.assertEqual(unchanged.material_slots[0].material, 'initial')

    def test_replayed_numpy_colors_are_json_safe(self):
        source=dict(rgba=np.array([.12,.34,.56,0.],dtype=np.float32),roughness=np.float32(.58),metallic=np.float32(0.))
        for role in (None,'joint','shell','painted_wood'):
            result=resolve(source,role)
            self.assertEqual(json.loads(json.dumps(result))['rgba'][3],0.)
        np.testing.assert_array_equal(source['rgba'],np.array([.12,.34,.56,0.],dtype=np.float32))

    def test_unspecified_pbr_and_source_immutability(self):
        source = dict(rgba=[.25, .25, .25, 1], roughness=-1., metallic=-1.)
        result = resolve(source, robot_role(source))
        self.assertGreaterEqual(result['roughness'], .4)
        self.assertEqual(result['metallic'], 0.)
        self.assertLess(max(result['rgba'][:3]), .05)
        self.assertEqual(source['rgba'], [.25, .25, .25, 1])
        self.assertEqual(source['roughness'], -1.)

    def test_explicit_and_colored_materials_are_preserved(self):
        source = dict(rgba=[0., 1., 0., 1.], roughness=.7, metallic=.2)
        result = resolve(source, robot_role(source))
        self.assertEqual(result, source)

    def test_shell_is_separate_from_joint_and_palette_can_be_disabled(self):
        source = dict(rgba=[.90, .92, .93, 1.], roughness=-1., metallic=-1.)
        self.assertEqual(robot_role(source), 'shell')
        self.assertLess(max(resolve(source, 'shell')['rgba'][:3]), .8)
        self.assertEqual(resolve(source, 'shell', False)['rgba'], source['rgba'])

    def test_task_colors_increase_chroma_without_revealing_hidden_geoms(self):
        source=dict(rgba=[.84,.1,.08,0.],roughness=-1.,metallic=-1.)
        for name in ('relay-a08-d1__payload_01_beam','mosaic-a04-6x12-d1__A_stock01_geom'):
            self.assertEqual(task_role(dict(name=name)), 'painted_wood')
            result=resolve(source,task_role(dict(name=name)))
            self.assertEqual(result['rgba'][3],0.)
            self.assertGreater(max(result['rgba'][:3])-min(result['rgba'][:3]),max(source['rgba'][:3])-min(source['rgba'][:3]))
            self.assertGreater(result['roughness'],.5)
        self.assertIsNone(task_role(dict(name='transport-a04-d1__A_item1_blade0')))
        self.assertEqual(source['rgba'],[.84,.1,.08,0.])

    def test_task_palette_covers_families_and_preserves_neutral_white(self):
        for name in ('transport-a04-d1__A_item1_geom','relay-a08-d1__relay_direction_0_tip',
                     'dial-best5-n04-d1__D01_module_disk','mosaic-a04-6x12-d1__A_stock01_geom'):
            self.assertIsNotNone(task_role(dict(name=name)),name)
        source=dict(rgba=[.9,.9,.9,1.],roughness=.5,metallic=0.)
        self.assertEqual(resolve(source,'task_color')['rgba'],source['rgba'])

    def test_printed_labels_use_matte_nonmetallic_finish(self):
        for name in ('transport-a04-d1__A_label', 'dial-best5-n04-d1__score_title_geom',
                     'relay-a08-d1__payload_01_label'):
            self.assertEqual(task_role(dict(name=name)), 'print')
        result = resolve(dict(rgba=[1, 1, 1, 1], roughness=.2, metallic=.4), 'print')
        self.assertEqual(result['specular'], 0.)
        self.assertGreaterEqual(result['roughness'], .9)
        self.assertEqual(result['metallic'], 0.)
