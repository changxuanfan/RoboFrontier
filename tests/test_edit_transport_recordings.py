import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from unittest import mock

from robofrontier.suite import transport_motion_edit
from scripts import edit_transport_recordings as script


class ReuseEditTests(unittest.TestCase):
    def edit(self, root, recording):
        module = Path(transport_motion_edit.__file__)
        target = Path(root)/'case'
        target.mkdir()
        (target/'edit.json').write_text(json.dumps(dict(
            source_recording=str(recording), settings=asdict(transport_motion_edit.Settings()),
            algorithm_sha256=transport_motion_edit.digest(module),
            signal_implementation_sha256=transport_motion_edit.digest(module.with_name('transport_motion_signals.py')))))
        return target

    def test_existing_edit_of_another_oracle_trial_is_refused(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(script, 'TransportEdit'):
            row = dict(case_id='c', oracle_trial=str(Path(root)/'new-trial'))
            target = self.edit(root, Path(root)/'old-trial/motion')
            with self.assertRaisesRegex(ValueError, 'source_recording'):
                script.reuse_edit(row, target)

    def test_existing_edit_of_the_same_trial_and_algorithm_is_reused(self):
        with tempfile.TemporaryDirectory() as root, mock.patch.object(script, 'TransportEdit'):
            row = dict(case_id='c', oracle_trial=str(Path(root)/'trial'))
            target = self.edit(root, Path(root)/'trial/motion')
            self.assertEqual(script.reuse_edit(row, target)['source_recording'], str(Path(root)/'trial/motion'))
            value = json.loads((target/'edit.json').read_text())
            value['algorithm_sha256'] = '0'*64
            (target/'edit.json').write_text(json.dumps(value))
            with self.assertRaisesRegex(ValueError, 'algorithm_sha256'):
                script.reuse_edit(row, target)


if __name__ == '__main__':
    unittest.main()
