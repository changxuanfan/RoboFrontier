"""A controlled stop retains a final measured pose without another physics step."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier.configuration import ROOT
from robofrontier.media.motion_recording import MotionReader
from robofrontier.oracle.trial import Trial


class OracleStopRecordingTests(unittest.TestCase):
    def test_failed_operation_retains_its_measured_tail_without_marking_complete(self):
        scene=ROOT/'benchmark/transport/transport-a04-d1'
        with TemporaryDirectory() as directory:
            trial=Trial(scene,Path(directory)/'trial')
            trial.step()
            stamp=trial.time;state=trial.data.qpos.copy();control=trial.data.ctrl.copy()
            report={'passed':False,'error':'Finite placement route rejected'}
            with patch('mujoco.mj_step',side_effect=AssertionError('Closing must not advance dynamics')):
                trial.close(report)
            reader=MotionReader(trial.directory/'motion')
            frames=list(reader.frames());events=list(reader.events())
            self.assertEqual(reader.meta['status'],'failed')
            self.assertEqual(frames[-1][0],stamp)
            np.testing.assert_array_equal(frames[-1][1],state.astype(np.float32))
            np.testing.assert_array_equal(trial.data.qpos,state)
            np.testing.assert_array_equal(trial.data.ctrl,control)
            self.assertLessEqual(max(event['sim_time_s'] for event in events),frames[-1][0])
            self.assertFalse(report['passed'])

    def test_between_sample_stop_retains_actual_final_state_and_interrupted_status(self):
        scene=ROOT/'benchmark/transport/transport-a04-d1'
        with TemporaryDirectory() as directory:
            trial=Trial(scene,Path(directory)/'trial')
            trial.step()  # 2 ms lies before the next 60-Hz motion sample.
            stamp=trial.time;state=trial.data.qpos.copy();control=trial.data.ctrl.copy()
            report={'passed':False,'interrupted':True,'error':'Explicit owner stop'}
            with patch('mujoco.mj_step',side_effect=AssertionError('Closing must not advance dynamics')):
                trial.close(report)
            reader=MotionReader(trial.directory/'motion')
            frames=list(reader.frames());events=list(reader.events())
            self.assertEqual(reader.meta['status'],'interrupted')
            self.assertEqual(frames[-1][0],stamp)
            np.testing.assert_array_equal(frames[-1][1],state.astype(np.float32))
            np.testing.assert_array_equal(trial.data.qpos,state)
            np.testing.assert_array_equal(trial.data.ctrl,control)
            self.assertLessEqual(max(event['sim_time_s'] for event in events),frames[-1][0])
            self.assertFalse(report['passed'])

    def test_invalid_final_state_keeps_prefix_and_records_missing_tail_honestly(self):
        scene=ROOT/'benchmark/transport/transport-a04-d1'
        with TemporaryDirectory() as directory:
            trial=Trial(scene,Path(directory)/'trial')
            trial.step();trial.data.qpos[0]=float('nan')
            report={'passed':False,'interrupted':True,'error':'Owner stopped after invalid state'}
            trial.close(report)
            saved=json.loads((trial.directory/'report.json').read_text())
            self.assertEqual(saved['final_motion_capture_error'],'Nonfinite recording state')
            reader=MotionReader(trial.directory/'motion')
            self.assertEqual(reader.meta['status'],'interrupted')
            self.assertTrue(all(np.isfinite(state).all() for _,state in reader.frames()))
            self.assertFalse(saved['passed'])


if __name__=='__main__':unittest.main()
