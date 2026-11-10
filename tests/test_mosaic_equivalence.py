import json
from pathlib import Path
import tempfile
import unittest
import mujoco
from robofrontier.media.mosaic_equivalence import check,compare_models,check_prefix_candidate

ROOT=Path(__file__).resolve().parents[1]
SOURCE=ROOT/'benchmark/mosaic/mosaic-a04-6x12-d2'
TARGET=ROOT/'benchmark/mosaic/mosaic-a04-6x12-d3'


class MosaicEquivalenceTests(unittest.TestCase):
    def test_same_case_changed_stock_colours_rejects_source_commands(self):
        with tempfile.TemporaryDirectory() as temporary:
            target=Path(temporary)
            (target/'scene.xml').write_bytes((SOURCE/'scene.xml').read_bytes())
            (target/'assets').symlink_to(SOURCE/'assets',target_is_directory=True)
            task=json.loads((SOURCE/'task.json').read_text())
            task['objects'][0]['color']='different-stock-colour'
            (target/'task.json').write_text(json.dumps(task))
            result=check_prefix_candidate(SOURCE,target)
            self.assertFalse(result['equivalent_for_command_candidate'])
            self.assertFalse(result['checks']['complete_same_case_task'])

    def test_same_case_prefix_gate_requires_identical_compiled_inputs(self):
        result=check_prefix_candidate(SOURCE,SOURCE)
        self.assertTrue(result['equivalent_for_command_candidate'])
        self.assertTrue(result['checks']['complete_same_case_task'])

    def test_visual_grid_difference_does_not_hide_physical_difference(self):
        self.assertTrue(check(SOURCE,TARGET)['equivalent_for_command_candidate'])
        a=mujoco.MjModel.from_xml_path(str(SOURCE/'scene.xml'))
        b=mujoco.MjModel.from_xml_path(str(TARGET/'scene.xml'))
        b.opt.timestep*=2
        self.assertFalse(compare_models(a,b)['option.timestep'])
        b.geom_friction[0,0]+=.1
        self.assertFalse(compare_models(a,b)['physical.geom_friction'])

    def test_other_level_pairs_are_not_silently_accepted(self):
        with self.assertRaises(ValueError):check(TARGET,SOURCE)


if __name__=='__main__':unittest.main()
