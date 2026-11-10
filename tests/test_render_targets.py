import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from scripts import render_frontier_oracle


def policy_outputs(root):
    outputs = Path(root)/'run/private/outputs'
    (outputs/'motion').mkdir(parents=True)
    (outputs/'motion/stream.json').write_text(json.dumps({'case_id': 'transport-a04-d1', 'source_scene_sha256': 'x'}))
    (outputs/'evaluation.json').write_text(json.dumps({'task_success': False}))
    return outputs


class RenderTargetTests(unittest.TestCase):
    def test_a_policy_run_never_renders_inside_its_own_tree(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(render_frontier_oracle, 'stationary_cut') as cut:
            outputs = policy_outputs(root)
            for output in (None, outputs/'video', outputs.parents[1]/'video'):
                with self.assertRaisesRegex(ValueError, 'outside the policy run'):
                    render_frontier_oracle.render(outputs, output=output)
            cut.assert_not_called()
            self.assertFalse((outputs/'video').exists())

    def test_an_existing_view_stops_before_any_cut_or_encoder(self):
        with tempfile.TemporaryDirectory() as root, \
                mock.patch.object(render_frontier_oracle, 'stationary_cut') as cut, \
                mock.patch.object(render_frontier_oracle.subprocess, 'Popen') as popen:
            outputs, target = policy_outputs(root), Path(root)/'video'
            target.mkdir()
            (target/'global_rear.mp4').write_bytes(b'')
            with self.assertRaises(FileExistsError):
                render_frontier_oracle.render(outputs, views=('global', 'global_rear'), output=target)
            cut.assert_not_called()
            popen.assert_not_called()
            self.assertFalse((target/'global.mp4').exists())


if __name__ == '__main__':
    unittest.main()
