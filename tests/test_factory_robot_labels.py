import hashlib
import unittest

import mujoco
import numpy as np

from robofrontier.factory.labels import robot_label_moves, ROBOT_LABEL
from robofrontier.task_families import ROOT, resolve_case
from robofrontier.workstation import Workstation


class RobotLabelTests(unittest.TestCase):
    """Letter labels sit on their robot's outline seen from above, upright for the front view."""

    def check(self, case):
        source = ROOT/resolve_case(case)[2]['directory']
        before = hashlib.sha256((source/'scene.xml').read_bytes()).hexdigest()
        world = Workstation(source); world.frame()
        model, data = world.model, world.data
        moves = robot_label_moves(model, data)
        labels = [model.geom(g).name for g in range(model.ngeom) if ROBOT_LABEL.fullmatch(model.geom(g).name)]
        self.assertTrue(moves)
        for name, move in moves.items():
            base = data.xpos[model.body(move['robot']+'_link0').id][:2]
            start, end = np.asarray(move['from_xy'])-base, np.asarray(move['to_xy'])-base
            self.assertGreater(np.linalg.norm(end), np.linalg.norm(start))
            self.assertGreater(float(start@end/np.linalg.norm(start)/np.linalg.norm(end)), np.cos(np.radians(90.5)))
        self.assertEqual(set(moves), set(labels))
        # The spot is fixed: computing it again from the moved labels gives the same spots.
        for name, move in moves.items():
            model.geom_pos[model.geom(name).id][:2] = move['to_xy']
        world.frame()
        again = robot_label_moves(model, data)
        for name, move in moves.items():
            np.testing.assert_allclose(again[name]['to_xy'], move['to_xy'], atol=1e-9)
        self.assertEqual(len(labels), len(set(labels)))
        self.assertEqual(hashlib.sha256((source/'scene.xml').read_bytes()).hexdigest(), before)

    def test_a_run_places_its_labels_where_its_videos_do(self):
        from robofrontier.factory.labels import place_robot_labels
        case = resolve_case('mosaic-a04-6x12-d2')[2]
        world = Workstation(ROOT/case['directory']); world.frame()
        expected = robot_label_moves(world.model, world.data, avoid_objects=False)
        moved = place_robot_labels(world.model, world.data, dict(family='mosaic'))
        self.assertEqual(set(moved), set(expected))
        for name, move in expected.items():
            gid = world.model.geom(name).id
            np.testing.assert_allclose(world.data.geom_xpos[gid][:2], move['to_xy'], atol=1e-9)
            np.testing.assert_allclose(world.model.geom_quat[gid], move['quat_wxyz'], atol=1e-9)
            self.assertEqual(world.model.geom_contype[gid], 0)  # display only, no contact

    def test_block_letters_read_upright_in_videos_only(self):
        from robofrontier.factory.labels import apply_display_labels, item_print_turns, place_robot_labels
        source = ROOT/resolve_case('transport-a04-d2')[2]['directory']
        before = hashlib.sha256((source/'scene.xml').read_bytes()).hexdigest()
        world = Workstation(source); world.frame()
        model, data = world.model, world.data
        original = model.geom_quat.copy()
        place_robot_labels(model, data, dict(family='transport'))  # a run keeps its printed letters
        turns = item_print_turns(model)
        self.assertTrue(turns)
        self.assertTrue(all(name.endswith('_print1') for name in turns))
        for name in turns:
            np.testing.assert_allclose(model.geom_quat[model.geom(name).id], original[model.geom(name).id])
        apply_display_labels(model, data)
        for gid in range(model.ngeom):
            name = model.geom(gid).name
            if '_print' not in name or '_item' not in name:
                continue
            axes = np.zeros(9)
            mujoco.mju_quat2Mat(axes, model.geom_quat[gid])
            axes = axes.reshape(3, 3)
            if abs(axes[2, 2]) < .5:  # a side face: the letter's top is the block's top
                self.assertGreater(axes[2, 1], .5, name)
        self.assertEqual(item_print_turns(model), {})  # already upright, nothing left to turn
        self.assertEqual(hashlib.sha256((source/'scene.xml').read_bytes()).hexdigest(), before)

    def test_mosaic_labels_leave_the_robot_bases(self):
        self.check('mosaic-a04-6x12-d1')

    def test_transport_labels_turn_when_the_edge_is_near(self):
        self.check('transport-a04-d1')


if __name__ == '__main__':
    unittest.main()
