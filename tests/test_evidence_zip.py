import base64
import contextlib
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from robofrontier.cli import archive_collection
from robofrontier.batch.archive import unpack
from robofrontier.batch.archive_policy_batch import verify


class EvidenceZipTests(unittest.TestCase):
    def test_zip_roundtrip_preserves_native_session_images_and_motion_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root/'collection'
            (source/'batch').mkdir(parents=True)
            (source/'sessions').mkdir()
            image = b'JPEG-observation-bytes\x00\xff'
            raw = json.dumps({'image': 'data:image/jpeg;base64,'+base64.b64encode(image).decode()}).encode()+b'\n'
            session = source/'sessions/role.jsonl'
            session.write_bytes(raw)
            motion = b'unchanged-compressed-motion\x00'*1000
            (source/'batch/motion.npz').write_bytes(motion)
            (source/'batch/batch.json').write_text('{"status":"closed","jobs":[]}')
            (source/'collection.json').write_text(json.dumps({
                'schema': 'robofrontier.luna-collection.v1', 'complete': True, 'job_count': 1,
                'jobs': [{'roles': [{'session': 'sessions/role.jsonl',
                                    'sha256': hashlib.sha256(raw).hexdigest()}]}]}))
            from robofrontier.cli import main
            result = root/'result.json'
            output = root/'result.zip'
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(main(['--result-file', str(result), 'archive', str(source),
                                       '--output', str(output)]), 0)
            receipt = json.loads(result.read_text())
            self.assertEqual(receipt['archive'], str(output.resolve()))
            self.assertEqual(receipt['archive_sha256'], hashlib.sha256(output.read_bytes()).hexdigest())
            unpack(output, root/'extracted')
            verify(root/'extracted', root/'restored')
            self.assertEqual((root/'restored/sessions/role.jsonl').read_bytes(), raw)
            self.assertEqual((root/'restored/batch/motion.npz').read_bytes(), motion)
            self.assertEqual(session.read_bytes(), raw)
            with self.assertRaises(ValueError):
                archive_collection(source, output)

    def test_unsafe_zip_is_rejected_before_creating_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            for name in ('../escape', '/absolute', 'a/../../escape', 'C:/escape', 'a\\escape'):
                archive = root/'bad.zip'
                with zipfile.ZipFile(archive, 'w') as out:
                    out.writestr('manifest.json', '{}')
                    out.writestr(name, 'bad')
                with self.subTest(name=name), self.assertRaises(ValueError):
                    unpack(archive, root/'output')
                self.assertFalse((root/'output').exists())


if __name__ == '__main__':
    unittest.main()
