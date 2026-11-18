import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import numpy as np

from roboteam.sim.motion_recording import MotionReader, MotionWriter
from roboteam.sim.workstation import Workstation
from roboteam.tasks.task_types import ROOT, resolve_case


class MotionRecordingTests(unittest.TestCase):
    def setUp(self):
        self.source = ROOT / resolve_case('transport-a04-d1')[2]['directory']
        self.w = Workstation(self.source)

    def test_float32_exact_roundtrip_events_and_bounded_chunks(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'motion'
            writer = MotionWriter(path, self.source, self.w.model, self.w.data, hz=60, chunk_seconds=0.05)
            captured = [np.asarray(self.w.data.qpos, dtype=np.float32).copy()]
            times = [0.0]
            for step in range(1, 151):
                self.w.data.time = step * 0.002
                self.w.data.qpos[0] = step * 0.00017
                if step == 30:
                    self.w.model.geom_rgba[0, 0] = 0.123
                if writer.capture(self.w.data):
                    captured.append(self.w.data.qpos.astype(np.float32))
                    times.append(self.w.data.time)
                self.assertLess(len(writer.states), writer.limit)
            writer.close()
            reader = MotionReader(path)
            frames = list(reader.frames())
            np.testing.assert_array_equal(np.asarray([q for _, q in frames]), captured)
            np.testing.assert_allclose([t for t, _ in frames], times)
            indices = [0, 2, len(frames) - 1]
            selected = list(reader.selected_frames(indices))
            self.assertEqual([i for i, _, _ in selected], indices)
            for i, t, q in selected:
                self.assertEqual(t, frames[i][0])
                np.testing.assert_array_equal(q, frames[i][1])
            for invalid in [[-1], [len(frames)], [2, 1], [0, 0], []]:
                with self.assertRaises(ValueError):
                    list(reader.selected_frames(invalid))
            self.assertTrue(any(e['event'] == 'rgba' for e in reader.events()))
            portable = Workstation(path / 'source')
            self.assertEqual(portable.manifest['scene_sha256'], self.w.manifest['scene_sha256'])
            # Frozen files are clones of the shared cache, never hard links to it.
            frozen = path / 'source/scene.xml'
            self.assertEqual(frozen.stat().st_nlink, 1)
            cached = path / 'asset-cache' / hashlib.sha256(frozen.read_bytes()).hexdigest()
            frozen.write_text('changed')
            self.assertNotEqual(cached.read_text(), 'changed')

    def test_interrupted_orphan_complete_chunk_is_recovered(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'motion'
            writer = MotionWriter(path, self.source, self.w.model, self.w.data, hz=60, chunk_seconds=0.05)
            for step in range(1, 101):
                self.w.data.time = step * 0.002
                writer.capture(self.w.data)
            writer.events.close()  # emulate process loss; buffered unfinalized states are absent
            meta = json.loads((path / 'stream.json').read_text())
            meta['chunks'] = meta['chunks'][:-1]
            (path / 'stream.json').write_text(json.dumps(meta))
            reader = MotionReader.recover(path)
            self.assertGreater(len(list(reader.frames())), 0)
            self.assertEqual(reader.meta['frames'], sum(c['frames'] for c in reader.meta['chunks']))

    def test_corrupt_chunk_and_mismatched_source_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'motion'
            writer = MotionWriter(path, self.source, self.w.model, self.w.data)
            writer.close()
            chunk = next(path.glob('chunk-*.npz'))
            chunk.write_bytes(b'corrupted')
            with self.assertRaisesRegex(ValueError, 'checksum'):
                list(MotionReader(path).frames())

    def test_frozen_policy_scene_retains_canonical_source_for_shared_recorder(self):
        from roboteam.runtime.world.pipeline import World
        from roboteam.tasks.scene import freeze_scene

        with tempfile.TemporaryDirectory() as td:
            path = Path(td)
            (path / 'public/inputs').mkdir(parents=True)
            task = freeze_scene(json.loads((self.source / 'task.json').read_text()), path)
            frozen = Workstation(path / 'private/inputs/scene')
            self.assertEqual(frozen.manifest['scene_sha256'], self.w.manifest['scene_sha256'])
            world = World(path, task)
            self.assertEqual(world.model.nq, frozen.model.nq)
            with self.assertRaisesRegex(ValueError, 'environment preview'):
                world.start_trial()
            world.close()

    def test_interrupted_events_allow_only_an_incomplete_tail(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'motion'
            writer = MotionWriter(path, self.source, self.w.model, self.w.data)
            writer.close(status='interrupted')
            events = path / 'events.jsonl'
            events.write_text('{"event":"valid","sim_time_s":0}\n{"unfinished"')
            self.assertEqual(len(list(MotionReader(path).events())), 1)
            events.write_text('{"bad"\n{"event":"later","sim_time_s":1}\n')
            with self.assertRaisesRegex(ValueError, 'Corrupted event'):
                list(MotionReader(path).events())


if __name__ == '__main__':
    unittest.main()
