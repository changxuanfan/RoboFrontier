"""Actual HTTP reads must never initialize or access the runtime database."""
from contextlib import contextmanager
import json
from pathlib import Path
import sqlite3
import re
import subprocess
import tempfile
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from scripts.view_policy_batch import HTML, batch_snapshot, create_server


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value))


@contextmanager
def serving(batch):
    server=create_server(batch)
    thread=threading.Thread(target=server.serve_forever,kwargs={'poll_interval':.02},daemon=True)
    thread.start()
    try:yield f'http://127.0.0.1:{server.server_port}'
    finally:
        server.shutdown();server.server_close();thread.join(timeout=3)
        if thread.is_alive():raise AssertionError('Viewer did not stop')


class BatchViewerTests(unittest.TestCase):
    def fixture(self,base,*,legacy=False,engine='codex'):
        run=base/'profile/task'
        (run/'private/state').mkdir(parents=True)
        job=dict(case_id='transport-a04-d1',family='transport',level=1,arms=4,
                 profile='test-profile',status='prepared')
        job['run_dir' if legacy else 'run_directory']=str(run)
        write(base/'batch.json',dict(status='running',**{'cases' if legacy else 'jobs':[job]}))
        write(base/'effective-config.json',{'policy':{'engine':engine}})
        return run

    def test_http_api_is_readonly_even_with_no_database_and_with_invalid_database(self):
        for legacy in (False,True):
            with self.subTest(legacy=legacy),tempfile.TemporaryDirectory() as temporary:
                base=Path(temporary).resolve();run=self.fixture(base,legacy=legacy)
                def inventory():return {str(p.relative_to(base)):p.read_bytes() for p in base.rglob('*') if p.is_file()}
                for existing in (False,True):
                    if existing:(run/'private/state/runtime.sqlite').write_bytes(b'Unopenable database sentinel')
                    before=inventory()
                    with patch.object(sqlite3,'connect',side_effect=AssertionError('No SQLite access')),serving(base) as url:
                        with urlopen(url+'/api',timeout=3) as response:data=json.load(response)
                        self.assertTrue(data['read_only'])
                        self.assertEqual(data['cases'][0]['lifecycle'],'task_state_not_reported')
                        self.assertIsNone(data['cases'][0]['actions'])
                        self.assertIsNone(data['cases'][0]['evaluation'])
                        self.assertIsNone(data['cases'][0]['snapshot_mtime'])
                        with urlopen(url,timeout=3) as response:self.assertIn(b'lang="en"',response.read())
                    self.assertEqual(inventory(),before)
                    if not existing:self.assertFalse((run/'private/state/runtime.sqlite').exists())

    def test_claude_supervisor_updates_and_terminal_snapshot_are_distinct(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();run=self.fixture(base,engine='claude')
            write(base/'engineering-status.json',{'status':'running','jobs':[{
                'profile':'test-profile','case_id':'transport-a04-d1','status':'running'}]})
            with serving(base) as url:
                with urlopen(url+'/api',timeout=3) as response:first=json.load(response)
                self.assertEqual(first['engine'],'claude')
                self.assertEqual(first['cases'][0]['lifecycle'],'running')
                self.assertIsNone(first['cases'][0]['snapshot_mtime'])
                write(run/'private/outputs/runtime.json',{'lifecycle':'ended','agents':{
                    'Controller':{'kind':'controller','note':'PRIVATE_NOTE'},'helper':{'kind':'delegate'}},
                    'jobs':{'a':{},'b':{}},'messages':['PRIVATE_MAIL']})
                write(run/'private/outputs/evaluation.json',{'task_success':False,'private_truth':'PRIVATE_TRUTH'})
                with urlopen(url+'/api',timeout=3) as response:second=json.load(response)
                row=second['cases'][0]
                self.assertEqual(row['lifecycle'],'ended');self.assertEqual(row['actions'],2)
                self.assertEqual(row['delegates'],1);self.assertEqual(row['evaluation'],{'task_success':False})
                self.assertIsNotNone(row['snapshot_mtime'])
                self.assertNotIn('PRIVATE_',json.dumps(second))

    def test_image_mime_and_video_ranges_without_render_or_encoder(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();run=self.fixture(base)
            image=run/'public/observations/1-global.jpg';image.parent.mkdir(parents=True)
            Image.new('RGB',(20,10),'white').save(image)
            video=run/'private/outputs/global-realtime.mp4';video.parent.mkdir(parents=True)
            video.write_bytes(b'0123456789')  # HTTP range fixture, not a video-quality assertion.
            with serving(base) as url:
                with urlopen(url+'/frame/0',timeout=3) as response:
                    self.assertEqual(response.headers.get_content_type(),'image/jpeg')
                    self.assertEqual(response.read(),image.read_bytes())
                request=Request(url+'/video/0',headers={'Range':'bytes=2-5'})
                with urlopen(request,timeout=3) as response:
                    self.assertEqual(response.status,206);self.assertEqual(response.read(),b'2345')
                with self.assertRaises(HTTPError) as error:urlopen(url+'/frame/not-a-task',timeout=3)
                self.assertEqual(error.exception.code,404)

    def test_outside_run_directory_is_rejected_before_server_start(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();self.fixture(base)
            data=json.loads((base/'batch.json').read_text());data['jobs'][0]['run_directory']=str(base.parent)
            write(base/'batch.json',data)
            with self.assertRaisesRegex(ValueError,'inside the selected batch'):create_server(base)

    def test_malformed_optional_snapshot_is_missing_not_success(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();run=self.fixture(base)
            output=run/'private/outputs';output.mkdir()
            (output/'runtime.json').write_text('{partial')
            (output/'evaluation.json').write_text('{partial')
            row=batch_snapshot(base)['cases'][0]
            self.assertEqual(row['lifecycle'],'task_state_not_reported')
            self.assertIsNone(row['evaluation']);self.assertIsNone(row['snapshot_mtime'])

    def test_same_case_in_two_profiles_has_unambiguous_image_keys(self):
        with tempfile.TemporaryDirectory() as temporary:
            base=Path(temporary).resolve();first=self.fixture(base)
            second=base/'other-profile/task';image=first/'private/outputs/final-global.jpg'
            image.parent.mkdir(parents=True);image.write_bytes(b'first saved JPEG fixture')
            other=second/'private/outputs/final-global.jpg';other.parent.mkdir(parents=True)
            other.write_bytes(b'second saved JPEG fixture')
            data=json.loads((base/'batch.json').read_text());data['jobs'].append({
                **data['jobs'][0],'profile':'other-profile','run_directory':str(second)})
            write(base/'batch.json',data)
            with serving(base) as url:
                with urlopen(url+'/api',timeout=3) as response:rows=json.load(response)['cases']
                self.assertEqual([r['key'] for r in rows],['0','1'])
                for key,expected in [('0',image.read_bytes()),('1',other.read_bytes())]:
                    with urlopen(url+'/frame/'+key,timeout=3) as response:self.assertEqual(response.read(),expected)
                with self.assertRaises(HTTPError):urlopen(url+'/frame/transport-a04-d1',timeout=3)

    def test_inline_browser_script_is_valid_without_running_a_browser(self):
        for script in re.findall(r'<script>(.*?)</script>',HTML,re.S):
            result=subprocess.run(['node','-e',"new(require('node:vm').Script)(process.argv[1])",script],
                capture_output=True,text=True)
            self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
