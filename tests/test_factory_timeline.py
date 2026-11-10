from copy import deepcopy
from pathlib import Path
import unittest
from unittest.mock import patch

import numpy as np

from robofrontier.task_families import ROOT,RELEASE,read
from robofrontier.factory.playback import StationTrack,FactoryTimeline,current_scene
from robofrontier.factory.cameras import shots,camera_at
from robofrontier.factory.bundle import resolved_release,read as read_bundle


def portable_data(test):
    folder=ROOT/'runs/factory-data/r14'
    if not (folder/'bundle.json').is_file():test.skipTest('Install factory data with robofrontier factory setup')
    release=resolved_release(folder)
    scene=folder/read_bundle(folder/'bundle.json')['scene']
    return release,scene


class FactoryTimelineTests(unittest.TestCase):
    def test_each_producer_rewinds_exact_states_and_resets_appearance(self):
        release,_=portable_data(self)
        with patch('mujoco.mj_step',side_effect=AssertionError('No replay physics')):
            for family in release['families'].values():
                track=StationTrack(family['oracle'][0],family['speedup'])
                try:
                    first=track.at(0)
                    self.assertTrue(first['appearance_reset'])
                    end=track.at(track.frame_count-1)
                    restart=track.at(track.frame_count)
                    self.assertEqual(restart['cycle'],1)
                    self.assertTrue(restart['appearance_reset'])
                    np.testing.assert_array_equal(first['qpos'],restart['qpos'])
                    self.assertEqual(first['source_time_s'],restart['source_time_s'])
                    self.assertEqual(restart['rgba'],first['rgba'])
                    self.assertGreater(end['source_time_s'],first['source_time_s'])
                    track.loop=False
                    a=track.at(track.frame_count+9)
                    np.testing.assert_array_equal(a['qpos'],end['qpos'])
                    self.assertTrue(a['completed'])
                finally:track.close()

    def test_two_different_clocks_commit_one_global_frame(self):
        release,scene=portable_data(self)
        release=deepcopy(release)
        release['families']={n:f for n,f in release['families'].items()if n in ('dial','transport')}
        for f in release['families'].values():f['oracle']=f['oracle'][:1]
        timeline=FactoryTimeline(scene,release)
        try:
            with patch('mujoco.mj_step',side_effect=AssertionError('No replay physics')),\
                    patch.object(timeline.play,'commit_frame',wraps=timeline.play.commit_frame)as commit:
                frame=max(t.frame_count for t in timeline.tracks)+5
                row=timeline.at(frame)
                self.assertEqual(commit.call_count,1)
                self.assertEqual(timeline.play.data.time,frame/30)
                self.assertEqual(len(row['stations']),2)
                self.assertTrue(all(r['cycle']>=1 for r in row['stations']))
                self.assertNotEqual(row['stations'][0]['source_time_s'],row['stations'][1]['source_time_s'])
        finally:timeline.close()

    def test_repeated_frame_preserves_cursor_and_appearance(self):
        release,_=portable_data(self)
        for family in release['families'].values():
            track=StationTrack(family['oracle'][0],family['speedup'])
            try:
                for frame in (0,1,track.frame_count-1):
                    first=track.at(frame);again=track.at(frame)
                    np.testing.assert_array_equal(first['qpos'],again['qpos'])
                    self.assertEqual(first['source_time_s'],again['source_time_s'])
                    self.assertEqual(first['rgba'],again['rgba'])
            finally:track.close()

    def test_camera_tour_keeps_task_order_and_has_independent_time(self):
        manifest=dict(placements=[dict(family='mosaic',case_id='mosaic-a04-6x12-d2',planning_bounds_xy_m=[0,0,4,4]),
                                  dict(family='mosaic',case_id='mosaic-a04-6x12-d1',planning_bounds_xy_m=[6,0,10,4])])
        plan=shots(manifest)
        self.assertTrue(plan[2]['id'].endswith('d1'))
        self.assertTrue(plan[3]['id'].endswith('d2'))
        self.assertEqual(camera_at(plan,0),camera_at(plan,sum(p['duration_s']for p in plan)))


class ReleasedRecordingTests(unittest.TestCase):
    def test_a_recording_missing_from_this_host_is_named(self):
        import tempfile
        from robofrontier.motion_recording import digest
        old='/Users/fanchangxuan/Repos/roomscript2/runs/oracle/relay-absent/relay-a08-d1/attempt-001/motion'
        with tempfile.TemporaryDirectory() as tmp:
            edit=Path(tmp)/'edit.json';edit.write_text('{}')
            spec=dict(id='relay-a08-d1',recording=old,directory=tmp,edit=str(edit),edit_sha256=digest(edit))
            with self.assertRaisesRegex(FileNotFoundError,'Released Oracle recording is not on this host: '+old):
                StationTrack(spec,10)


if __name__=='__main__':unittest.main()
