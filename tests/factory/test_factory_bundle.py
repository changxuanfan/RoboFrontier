import io
import json
import os
from pathlib import Path
import shutil
import tarfile
import tempfile
import unittest

import numpy as np

from robofrontier.factory import bundle
from robofrontier.factory import server


def fixture(root):
    source=root/'original'
    motion=source/'run/motion';(motion/'source').mkdir(parents=True)
    scene=motion/'source/scene.xml';scene.write_text('<mujoco/>')
    bundle.write(motion/'source/workstation.json',dict(scene_sha256=bundle.digest(scene),case=dict(id='transport-a04-d1')))
    bundle.write(motion/'source/task.json',dict(family='transport',level=1))
    bundle.write(motion/'source/environment.json',{})
    (motion/'source/assets').mkdir();(motion/'source/assets/shared.bin').write_bytes(b'asset'*1000)
    (motion/'events.jsonl').write_text('')
    for name in ('actions.json','process.jsonl'):(motion.parent/name).write_text('{}\n')
    times=np.array([0.,.1,.2]);states=np.zeros((3,1),dtype='<u4')
    np.savez_compressed(motion/'chunk-000000.npz',base=states[0],xor=states,time_s=times)
    bundle.write(motion/'stream.json',dict(schema='robofrontier.motion.v1',case_id='transport-a04-d1',
        source_scene_sha256=bundle.digest(scene),sample_hz=10,nq=1,frames=3,
        chunks=[dict(file='chunk-000000.npz',sha256=bundle.digest(motion/'chunk-000000.npz'),frames=3)]))
    edit=source/'edit/edit.json'
    edit.parent.mkdir()
    np.savez_compressed(edit.parent/'selection.npz',source_time_s=times,keep=np.ones(3,dtype=bool))
    bundle.write(edit,dict(schema='robofrontier.station-edit.v2',case_id='transport-a04-d1',
        source_scene_sha256=bundle.digest(scene),source_stream_sha256=bundle.digest(motion/'stream.json'),
        events_sha256=bundle.digest(motion/'events.jsonl'),source_end_frame=2,source_hz=10,
        input_evidence_sha256={n:bundle.digest(motion.parent/n) for n in ('actions.json','process.jsonl')},
        selection_file='selection.npz',selection_sha256=bundle.digest(edit.parent/'selection.npz')))
    factory=source/'factory/scene.xml';factory.parent.mkdir();factory.write_text('<mujoco/>')
    bundle.write(factory.parent/'manifest.json',dict(scene_sha256=bundle.digest(factory)))
    asset=source/'asset';asset.mkdir()
    bundle.write(asset/'scene.json',dict(source_scene_sha256=bundle.digest(factory),source_scene='/old/computer/scene.xml'))
    (asset/'shared.bin').write_bytes(b'asset'*1000)
    cameras=source/'cameras.json'
    bundle.write(cameras,[dict(id='transport-a04-d1--'+view) for view in ('front','side')])
    release=source/'release.json'
    bundle.write(release,dict(schema='test',presentation=dict(fps=30),families=dict(transport=dict(speedup=1,fps=30,oracle=[dict(
        id='transport-a04-d1',directory=str(scene.parent),recording=str(motion),edit=str(edit),edit_sha256=bundle.digest(edit))]))))
    output=root/'bundle'
    bundle.export(output,factory,release,cameras,asset,source)
    return output


class FactoryBundleTests(unittest.TestCase):
    def test_portable_roundtrip_preserves_motion_edits_and_semantic_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            result=bundle.pack(data,root/'factory.tar.gz')
            restored=root/'other-machine/data'
            bundle.restore(root/'factory.tar.gz',restored,result['archive_sha256'])
            shutil.rmtree(root/'original');shutil.rmtree(data)
            verified=bundle.verify(restored)
            self.assertEqual(verified['stations'],1)
            plan=server.prepare(restored,root/'batch',duration_s=.1,device='CPU')
            self.assertEqual(plan['jobs'],2)
            self.assertEqual(bundle.read(root/'batch/plan.json')['jobs'][0]['frames'],3)
            release=bundle.resolved_release(restored)
            spec=release['families']['transport']['oracle'][0]
            self.assertTrue((Path(spec['recording']).parent/'actions.json').is_file())
            self.assertTrue(Path(spec['directory']).is_relative_to(restored.resolve()))
            # Identical assets share disk blocks after archive restore.
            shared=[p for p in restored.rglob('shared.bin')]
            self.assertEqual(len({p.stat().st_ino for p in shared}),1)

    def test_corruption_is_rejected_before_installation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            bundle.pack(data,root/'factory.tar.gz')
            with self.assertRaisesRegex(ValueError,'SHA-256'):
                bundle.restore(root/'factory.tar.gz',root/'restored','0'*64)
            self.assertFalse((root/'restored').exists())
            (data/'asset/shared.bin').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError,'checksum'):
                bundle.verify(data)

    def test_archive_traversal_and_symlinks_are_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);archive=root/'bad.tar.gz'
            for kind in ('traversal','symlink'):
                with tarfile.open(archive,'w:gz') as tar:
                    info=tarfile.TarInfo('../outside' if kind=='traversal' else 'link')
                    if kind=='symlink':info.type=tarfile.SYMTYPE;info.linkname='/etc/passwd';tar.addfile(info)
                    else:info.size=1;tar.addfile(info,io.BytesIO(b'x'))
                with self.assertRaises(ValueError):bundle.restore(archive,root/'installed',bundle.digest(archive))
                self.assertFalse((root/'outside').exists())
                self.assertFalse((root/'installed').exists())

    def test_frozen_plan_refuses_changed_inputs_and_slurm_is_explicit(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            plan=Path(server.prepare(data,root/'batch',device='OPTIX')['plan'])
            with patch.object(server,'blender_path',return_value='/software/blender'):
                cmd=server.submit(plan,'example',parallel=2,dry_run=True)['command']
            self.assertIn('0-1%2',cmd);self.assertIn('--gres=gpu:1',cmd)
            self.assertIn('--signal=B:TERM@180',cmd)
            bundle.write(root/'batch/release.json',{})
            with self.assertRaisesRegex(ValueError,'release changed'):server.load_plan(plan)

    def test_download_parts_reassemble_the_checked_archive(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            bundle.pack(data,root/'factory.tar.gz')
            config=bundle.split_archive(root/'factory.tar.gz',data,root.as_uri(),part_bytes=1000)
            self.assertGreater(len(config['parts']),1)
            bundle.write(root/'download.json',config)
            installed=root/'installed'
            result=bundle.setup(root/'download.json',installed)
            self.assertEqual(result['bundle_sha256'],config['bundle_sha256'])
            self.assertEqual(bundle.setup(root/'download.json',installed)['status'],'verified')

    def test_failed_render_preserves_attempt_and_has_no_completion_marker(self):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            plan=Path(server.prepare(data,root/'batch',device='CPU')['plan'])
            with self.assertRaises(subprocess.CalledProcessError):
                server.run_job(plan,0,blender=shutil.which('true'),scratch=root)
            job=root/'batch/jobs/transport-a04-d1--front'
            self.assertFalse((job/'complete.json').exists())
            attempts=list(job.glob('attempt-*/attempt.json'))
            self.assertEqual(len(attempts),1)
            self.assertEqual(bundle.read(attempts[0])['status'],'failed')
            self.assertTrue((attempts[0].parent/'render.log').is_file())
            self.assertEqual(server.status(plan)['jobs'][0]['status'],'failed')

    def test_plan_parameter_edits_are_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            plan=Path(server.prepare(data,root/'batch',device='CPU')['plan'])
            changed=bundle.read(plan);changed['samples']=999;bundle.write(plan,changed)
            with self.assertRaisesRegex(ValueError,'plan changed'):server.load_plan(plan)

    @unittest.skipUnless(os.name=='posix','POSIX signals are used by the Slurm runner')
    def test_sigterm_collects_interrupted_attempt_without_success_marker(self):
        import signal
        import subprocess
        import sys
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            plan=Path(server.prepare(data,root/'batch',device='CPU')['plan'])
            marker=root/'subprocess-started'
            script='''
import subprocess,sys
from unittest.mock import patch
from robofrontier.factory import server
original=subprocess.Popen
def launch(argv,**kwargs):
    return original([sys.executable,'-c',
        "import pathlib,time; pathlib.Path("+repr(sys.argv[2])+").write_text('ready'); time.sleep(60)"],**kwargs)
with patch.object(server.subprocess,'Popen',side_effect=launch):
    try: server.run_job(sys.argv[1],0,blender=sys.executable,scratch=sys.argv[3])
    except InterruptedError: pass
'''
            worker=subprocess.Popen([sys.executable,'-c',script,str(plan),str(marker),str(root)])
            try:
                deadline=time.monotonic()+15
                while not marker.exists() and worker.poll() is None and time.monotonic()<deadline:
                    time.sleep(.05)
                self.assertTrue(marker.exists(),'The subprocess must start before sending SIGTERM')
                worker.send_signal(signal.SIGTERM)
                self.assertEqual(worker.wait(timeout=15),0)
            finally:
                if worker.poll() is None:
                    worker.kill();worker.wait()
            job=root/'batch/jobs/transport-a04-d1--front'
            self.assertFalse((job/'complete.json').exists())
            attempts=list(job.glob('attempt-*/attempt.json'))
            self.assertEqual(len(attempts),1)
            self.assertEqual(bundle.read(attempts[0])['status'],'interrupted')
            self.assertEqual(bundle.read(attempts[0])['signals'],[signal.SIGTERM])
            self.assertFalse((job/'running.json').exists())
            self.assertEqual(server.status(plan)['jobs'][0]['status'],'interrupted')

    def test_render_dependency_verification_checks_used_bytes_without_other_recordings(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);data=fixture(root)
            unrelated=data/'unrelated/data.bin';unrelated.parent.mkdir();unrelated.write_bytes(b'original')
            manifest=bundle.read(data/'bundle.json')
            manifest['files']['unrelated/data.bin']=dict(bytes=8,sha256=bundle.digest(unrelated));bundle.write(data/'bundle.json',manifest)
            unrelated.write_bytes(b'corrupt!')
            self.assertEqual(bundle.verify(data,cases=['transport-a04-d1'])['verification_scope'],'selected_render_dependencies')
            with self.assertRaisesRegex(ValueError,'checksum'):bundle.verify(data)
            shared=data/'asset/shared.bin';shared.write_bytes(b'broken')
            with self.assertRaisesRegex(ValueError,'checksum'):bundle.verify(data,cases=['transport-a04-d1'])


def tour_fixture(root):
    """Synthetic 36-station media fixture, not a physical-task qualification."""
    fixture(root)
    source = root/'original'
    families, placements, cameras = {}, [], []
    for fi, (family, scales) in enumerate((('relay',(8,12,16)), ('transport',(4,8,12)),
                                          ('mosaic',(4,6,8)), ('dial',(4,6,8)))):
        specs = []
        for level in (1,2,3):
            for rank, arms in enumerate(scales):
                ident = f'{family}-a{arms:02d}-d{level}'
                directory = source/'records'/ident
                shutil.copytree(source/'run', directory)
                motion = directory/'motion'
                bundle.write(motion/'source/task.json', {'id':ident,'family':family,'level':level,
                             'scale':{'scene_revision':14} if family=='mosaic' else {},
                             'arms':{chr(65+i):{} for i in range(arms)}})
                workstation = bundle.read(motion/'source/workstation.json')
                workstation['case']['id'] = ident
                bundle.write(motion/'source/workstation.json', workstation)
                stream = bundle.read(motion/'stream.json'); stream['case_id'] = ident
                bundle.write(motion/'stream.json', stream)
                edit_dir = source/'edits'/ident
                shutil.copytree(source/'edit', edit_dir)
                edit = bundle.read(edit_dir/'edit.json'); edit.update(case_id=ident,
                    source_stream_sha256=bundle.digest(motion/'stream.json'))
                bundle.write(edit_dir/'edit.json', edit)
                specs.append({'id':ident,'directory':str(motion/'source'),'recording':str(motion),
                              'edit':str(edit_dir/'edit.json'),'edit_sha256':bundle.digest(edit_dir/'edit.json')})
                x, y = fi*12+rank*3, level*5
                placements.append({'case_id':ident,'family':family,'translation_m':[x,y,0],
                                   'planning_bounds_xy_m':[x-1,y-1,x+1,y+1]})
                for view in ('front','side'):
                    cameras.append({'id':ident+'--'+view,'position_m':[x+(3 if view=='side' else 0),y-3,3],
                                    'target_m':[x,y,.8],'vertical_fov_deg':48})
        families[family] = {'speedup':1,'fps':30,'oracle':specs}
    factory = source/'factory/scene.xml'
    bundle.write(factory.parent/'manifest.json', {'scene_sha256':bundle.digest(factory),'placements':placements})
    bundle.write(source/'cameras.json', cameras)
    bundle.write(source/'release.json', {'schema':'synthetic-tour','presentation':{'fps':30},'families':families})
    output = root/'tour-bundle'
    bundle.export(output, factory, source/'release.json', source/'cameras.json', source/'asset', source)
    return output


if __name__=='__main__':unittest.main()
