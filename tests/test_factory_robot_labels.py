import hashlib
import unittest

import numpy as np

from robofrontier.factory.labels import robot_label_moves, ROBOT_LABEL
from robofrontier.task_families import ROOT, resolve_case
from robofrontier.workstation import Workstation


class RobotLabelTests(unittest.TestCase):
    """Letter labels sit 5 cm outside their robot's outline seen from above, for display only."""

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

    def test_mosaic_labels_leave_the_robot_bases(self):
        self.check('mosaic-a04-6x12-d1')

    def test_transport_labels_turn_when_the_edge_is_near(self):
        self.check('transport-a04-d1')


if __name__ == '__main__':
    unittest.main()
