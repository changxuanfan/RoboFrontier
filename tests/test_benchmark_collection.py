import base64
import fcntl
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from scripts.collect_benchmark_batch import collect_batch, digest
from scripts.archive_policy_batch import create, verify


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value)+'\n')


class BenchmarkCollectionTests(unittest.TestCase):
    def test_task_home_takes_precedence_over_legacy_batch_home(self):
        from robofrontier.run_metrics import native_codex_sessions
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,sessions=self.make_batch(root)
            task_sessions=root/'isolated/sessions/2026'
            task_sessions.mkdir(parents=True)
            for path in sessions.glob('*.jsonl'):
                (task_sessions/path.name).write_bytes(path.read_bytes())
                path.write_text('{"wrong_home":true}\n')
            write(run/'codex-home.json', {'codex_home':str(root/'isolated')})
            self.assertEqual(native_codex_sessions(run,'parent'),[(task_sessions/'parent.jsonl').resolve()])
            report=collect_batch(batch,root/'export')
            self.assertTrue(report['complete'])
            for role in report['jobs'][0]['roles']:
                self.assertEqual((root/'export'/role['session']).read_bytes(),
                                 (task_sessions/(role['thread_id']+'.jsonl')).read_bytes())

    def make_batch(self, root, engine='codex', kind='controller', status='closed'):
        batch = root/'source'
        run = batch/'model/demo'
        state = run/'private/state'
        state.mkdir(parents=True)
        with sqlite3.connect(state/'runtime.sqlite') as conn:
            conn.execute('create table agents(id text,value text)')
            conn.executemany('insert into agents values (?,?)', [
                ('Meta', json.dumps({'kind':'manager'})),
                ('role', json.dumps({'kind':kind,'thread_id':'parent'})),
                ('child', json.dumps({'kind':'delegate','thread_id':'child','parent':'role'}))])
        write(run/'private/outputs/evaluation.json', {'task_success':False})
        write(run/'private/inputs/harness.json', {'engine':engine,'model':'example','topology':'adaptive'})
        job = {'profile':'model','case_id':'demo','status':status,'run_directory':str(run)}
        write(batch/'batch.json', {'schema':'robofrontier.claude-draft.v1' if engine=='claude' else 'robofrontier.cli-benchmark.v1',
                                 'status':'prepared_not_qualified' if engine=='claude' else status, 'jobs':[job]})
        if engine=='claude':
            write(batch/'engineering-status.json', {'status':status,'jobs':[job]})
            home=run/'private/claude-config'
            sessions=home/'projects/project'; sessions.mkdir(parents=True)
            write(home/'.credentials.json', {'secret':'MUST_NOT_COLLECT'})
        else:
            home=root/'home'
            sessions=home/'sessions/2026'; sessions.mkdir(parents=True)
            write(batch/'codex-home.json', {'codex_home':str(home)})
        for tid in ('parent','child'):
            write(sessions/(tid+'.jsonl'), {'sessionId':tid,'text':'\u539f\u59cb\u8bb0\u5f55'})
        return batch,run,sessions

    def test_all_role_kinds_and_failed_task_roundtrip(self):
        # 'coordinator' is how runs before the rename recorded 'team-controller'.
        for kind in ('controller','worker','team-controller','coordinator'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);batch,run,sessions=self.make_batch(root,kind=kind)
                report=collect_batch(batch,root/'export')
                self.assertTrue(report['complete'])
                self.assertEqual({r['kind'] for r in report['jobs'][0]['roles']},{kind,'delegate'})
                create(root/'export',root/'archive')
                verify(root/'archive',root/'restored')
                for p in (root/'export').rglob('*'):
                    if p.is_file():self.assertEqual(p.read_bytes(),(root/'restored'/p.relative_to(root/'export')).read_bytes())

    def test_claude_native_paths_sidecars_events_and_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,sessions=self.make_batch(root,'claude')
            write(sessions/'child/subagents/agent-one.jsonl', {'message':'auxiliary'})
            image=base64.b64encode(b'\xff\xd8\xffjpeg').decode()
            write(run/'private/evidence/turn.jsonl', {'content':[{'type':'image','mimeType':'image/jpeg','data':image}]})
            report=collect_batch(batch,root/'export')
            self.assertTrue(report['complete'])
            self.assertFalse(list((root/'export').rglob('.credentials.json')))
            self.assertTrue((root/'export/batch/model/demo/private/claude-config/projects/project/child.jsonl').is_file())
            self.assertTrue(list((root/'export/sessions').rglob('agent-one.jsonl')))
            create(root/'export',root/'archive');verify(root/'archive',root/'restored')
            original=run/'private/evidence/turn.jsonl'
            self.assertEqual(original.read_bytes(),(root/'restored/batch/model/demo/private/evidence/turn.jsonl').read_bytes())

    def test_managed_claude_home_collects_only_bound_native_sessions(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); batch, run, sessions = self.make_batch(root, 'claude')
            home = root / 'shared-native-home'
            (run / 'private/claude-config').rename(home)
            write(home / 'projects/another-project/unrelated.jsonl', {'private': 'UNRELATED_SESSION'})
            write(run / 'private/inputs/claude.json', {'profile': {
                'auth_mode': 'native_login', 'provider': 'anthropic', 'env_key': None,
                'native_config_dir': str(home)}})
            before = {p.relative_to(home): p.read_bytes() for p in home.rglob('*') if p.is_file()}
            report = collect_batch(batch, root / 'export')
            self.assertTrue(report['complete'])
            self.assertEqual({r['thread_id'] for r in report['jobs'][0]['roles']}, {'parent', 'child'})
            self.assertFalse(list((root / 'export').rglob('.credentials.json')))
            self.assertFalse(list((root / 'export').rglob('unrelated.jsonl')))
            self.assertEqual(before, {p.relative_to(home): p.read_bytes() for p in home.rglob('*') if p.is_file()})
            create(root/'export', root/'archive')
            verify(root/'archive', root/'restored')
            # Archived provenance remains readable on a machine with no account.
            from robofrontier.claude.native_home import history_directory, config_directory
            home.rename(root/'retained-native-home')
            restored = root/'restored/batch/model/demo'
            copied = history_directory(restored)
            self.assertEqual((copied/'projects/project/parent.jsonl').read_bytes(),
                             before[Path('projects/project/parent.jsonl')])
            with self.assertRaises(ValueError):
                config_directory(restored)

    def test_managed_auth_home_inside_batch_is_rejected_before_collection(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); batch, run, _ = self.make_batch(root, 'claude')
            home = batch/'native-auth'
            (run/'private/claude-config').rename(home)
            write(run/'private/inputs/claude.json', {'profile': {
                'auth_mode':'native_login', 'provider':'anthropic', 'env_key':None,
                'native_config_dir':str(home)}})
            with self.assertRaisesRegex(ValueError, 'outside'):
                collect_batch(batch, root/'export')
            self.assertFalse((root/'export').exists())

    def test_managed_claude_snapshot_history_survives_account_independent_restore(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,_=self.make_batch(root,'claude')
            home=root/'shared-native-home'
            (run/'private/claude-config').rename(home)
            write(run/'private/inputs/claude.json',{'profile':{
                'auth_mode':'native_login','provider':'anthropic','env_key':None,
                'native_config_dir':str(home)}})
            with sqlite3.connect(run/'private/state/runtime.sqlite') as conn:
                conn.execute('create table meta(key text,value text)')
                conn.executemany('insert into meta values (?,?)',[
                    ('lifecycle',json.dumps('ended')),
                    ('delegations',json.dumps({'batch-1':{'snapshot_thread_id':'anchor'}}))])
            native=home/'projects/project/anchor.jsonl'
            write(native,{'sessionId':'anchor','text':'inherited snapshot'})
            write(native.with_suffix('')/'tool-results/image-ref.json',{'image':'preserved'})
            report=collect_batch(batch,root/'export')
            self.assertTrue(report['complete'])
            row=report['jobs'][0]
            self.assertEqual(len(row['roles']),2)
            self.assertEqual([x['thread_id'] for x in row['snapshot_sessions']],['anchor'])
            create(root/'export',root/'archive');verify(root/'archive',root/'restored')
            home.rename(root/'retained-native-home')
            from robofrontier.claude.native_home import history_directory
            copied=history_directory(root/'restored/batch/model/demo')/'projects/project'
            self.assertEqual((copied/'anchor.jsonl').read_bytes(),
                             (root/'retained-native-home/projects/project/anchor.jsonl').read_bytes())
            self.assertTrue((copied/'anchor/tool-results/image-ref.json').is_file())
            self.assertFalse(list((root/'restored').rglob('.credentials.json')))

    def test_snapshot_anchor_is_collected_without_becoming_a_policy_role(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,sessions=self.make_batch(root)
            with sqlite3.connect(run/'private/state/runtime.sqlite') as conn:
                conn.execute('create table meta(key text,value text)')
                conn.executemany('insert into meta values (?,?)',[
                    ('lifecycle',json.dumps('ended')),
                    ('delegations',json.dumps({'batch-1':{'snapshot_thread_id':'anchor'}}))])
            write(sessions/'anchor.jsonl',{'sessionId':'anchor','text':'inherited history'})
            report=collect_batch(batch,root/'export')
            self.assertTrue(report['complete'])
            row=report['jobs'][0]
            self.assertEqual(len(row['roles']),2)
            self.assertEqual(row['snapshot_sessions'][0]['thread_id'],'anchor')
            self.assertEqual((root/'export'/row['snapshot_sessions'][0]['session']).read_bytes(),(sessions/'anchor.jsonl').read_bytes())

    def test_missing_snapshot_anchor_marks_collection_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,_=self.make_batch(root)
            with sqlite3.connect(run/'private/state/runtime.sqlite') as conn:
                conn.execute('create table meta(key text,value text)')
                conn.executemany('insert into meta values (?,?)',[
                    ('lifecycle',json.dumps('ended')),
                    ('delegations',json.dumps({'batch-1':{'snapshot_thread_id':'anchor'}}))])
            report=collect_batch(batch,root/'export')
            self.assertFalse(report['complete'])
            self.assertIn('batch-1: expected one snapshot session, found 0',report['jobs'][0]['issues'])

    def test_live_writers_and_pids_rejected_before_export(self):
        for name in ('supervisor.lock','model/demo/private/state/world.lock','model/demo/private/state/claude-engineering.lock'):
            with self.subTest(lock=name), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);batch,run,_=self.make_batch(root)
                with (batch/name).open('w') as lock:
                    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                    with self.assertRaises(ValueError):collect_batch(batch,root/'export')
                self.assertFalse((root/'export').exists())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,_=self.make_batch(root)
            unrelated=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)'])
            try:
                write(run/'private/state/host-process.json',{'pid':unrelated.pid})
                self.assertTrue(collect_batch(batch,root/'reused-pid')['complete'])
            finally:
                unrelated.terminate();unrelated.wait(timeout=5)
            process=subprocess.Popen([sys.executable,'-c','import time; time.sleep(20)','codex_policy_host.js',str(run)])
            try:
                write(run/'private/state/host-process.json',{'pid':process.pid})
                with self.assertRaises(ValueError):collect_batch(batch,root/'export')
            finally:
                process.terminate();process.wait(timeout=5)

    def test_incomplete_stopped_evidence_explicit_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,sessions=self.make_batch(root,status='needs_review')
            (sessions/'child.jsonl').unlink()
            report=collect_batch(batch,root/'export')
            self.assertFalse(report['complete'])
            with self.assertRaises(ValueError):create(root/'export',root/'archive')
            create(root/'export',root/'archive',allow_incomplete=True)
            self.assertFalse(json.loads((root/'archive/manifest.json').read_text())['collection_complete'])
            verify(root/'archive',root/'restored')

    def test_corrupt_database_preserved_as_incomplete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,_=self.make_batch(root)
            (run/'private/state/runtime.sqlite').write_bytes(b'corrupt')
            report=collect_batch(batch,root/'export')
            self.assertFalse(report['complete'])
            self.assertEqual((root/'export/batch/model/demo/private/state/runtime.sqlite').read_bytes(),b'corrupt')

    def test_missing_suite_motion_and_unfinalized_lifecycle_are_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,_=self.make_batch(root)
            write(run/'private/inputs/task.json',{'kind':'frontier_suite'})
            with sqlite3.connect(run/'private/state/runtime.sqlite') as conn:
                conn.execute('create table meta(key text,value text)')
                conn.execute('insert into meta values (?,?)',('lifecycle',json.dumps('running')))
            write(run/'private/outputs/seal.json',{'sealed':False,'unresolved_action_ids':['motion-one']})
            report=collect_batch(batch,root/'export')
            self.assertFalse(report['complete'])
            issues=report['jobs'][0]['issues']
            self.assertIn('missing motion recording',issues)
            self.assertIn('runtime lifecycle is not finalized',issues)
            self.assertIn('seal incomplete or physical actions unresolved',issues)

    def test_inventory_detects_changed_missing_and_extra_evidence(self):
        for action in ('changed','missing','extra'):
            with self.subTest(action=action), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);batch,run,_=self.make_batch(root)
                collect_batch(batch,root/'export')
                p=root/'export/batch/model/demo/private/outputs/evaluation.json'
                if action=='changed':p.write_text('changed')
                elif action=='missing':p.unlink()
                else:(root/'export/unlisted').write_text('extra')
                with self.assertRaises(ValueError):create(root/'export',root/'archive')

    def test_symlinks_and_escape_run_paths_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,_=self.make_batch(root)
            (batch/'linked').symlink_to(root/'home',target_is_directory=True)
            with self.assertRaises(ValueError):collect_batch(batch,root/'export')
            (batch/'linked').unlink()
            state=json.loads((batch/'batch.json').read_text());state['jobs'][0]['run_directory']=str(root/'home')
            write(batch/'batch.json',state)
            with self.assertRaises(ValueError):collect_batch(batch,root/'export')

    def test_links_in_a_policy_workspace_are_recorded_not_followed(self):
        from robofrontier import run_layout
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,_=self.make_batch(root)
            write(run/'private/inputs/manifest.json',run_layout.manifest_record('codex'))
            venv=run/'workspace/.tmp/venv/bin';venv.mkdir(parents=True)
            (venv/'python').symlink_to(sys.executable)
            (run/'workspace/secret').symlink_to(root/'home',target_is_directory=True)
            os.mkfifo(run/'workspace/pipe')
            (run/'workspace/skills.md').write_text('## lesson\n')
            report=collect_batch(batch,root/'export')
            self.assertFalse(report['complete'])
            issues=report['jobs'][0]['issues']
            self.assertIn('workspace symlink not collected: workspace/.tmp/venv/bin/python -> '+sys.executable,issues)
            self.assertIn('workspace symlink not collected: workspace/secret -> '+str(root/'home'),issues)
            self.assertIn('workspace nonregular not collected: workspace/pipe',issues)
            exported=root/'export/batch/model/demo/workspace'
            self.assertEqual((exported/'skills.md').read_text(),'## lesson\n')
            self.assertFalse(any(p.is_symlink() for p in exported.rglob('*')))
            self.assertFalse((exported/'secret').exists());self.assertFalse((exported/'pipe').exists())
            # Outside the workspace a link still stops collection.
            (run/'private/linked').symlink_to(root/'home',target_is_directory=True)
            with self.assertRaisesRegex(ValueError,'Symlink inside evidence'):collect_batch(batch,root/'export2')

    def test_36_jobs_keep_same_case_across_profiles_distinct(self):
        import shutil
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,sessions=self.make_batch(root)
            jobs=[]
            for i in range(36):
                profile=f'model{i:02d}';dest=batch/profile/'demo'
                shutil.copytree(run,dest)
                jobs.append({'profile':profile,'case_id':'demo','status':'closed','run_directory':str(dest)})
            write(batch/'batch.json',{'schema':'robofrontier.cli-benchmark.v1','status':'closed','jobs':jobs})
            report=collect_batch(batch,root/'export')
            self.assertTrue(report['complete']);self.assertEqual(report['job_count'],36)
            paths=[r['session'] for j in report['jobs'] for r in j['roles']]
            self.assertEqual(len(set(paths)),72)
            create(root/'export',root/'archive');verify(root/'archive',root/'restored')

    def test_source_mutation_does_not_publish_partial_collection(self):
        from scripts.collect_benchmark_batch import copy_stable
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,sessions=self.make_batch(root)
            def changing(source,target):
                checksum=copy_stable(source,target)
                if source.name=='child.jsonl':
                    (sessions/'parent.jsonl').write_text('changed after copy')
                return checksum
            with patch('scripts.collect_benchmark_batch.copy_stable',side_effect=changing):
                with self.assertRaises(ValueError):collect_batch(batch,root/'export')
            self.assertFalse((root/'export').exists())

    def test_late_claude_auxiliary_transcript_is_not_silently_missed(self):
        from scripts.collect_benchmark_batch import copy_stable
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);batch,run,sessions=self.make_batch(root,'claude')
            def changing(source,target):
                checksum=copy_stable(source,target)
                if source.name=='child.jsonl':
                    write(sessions/'parent/subagents/late.jsonl',{'late':'native event'})
                return checksum
            with patch('scripts.collect_benchmark_batch.copy_stable',side_effect=changing):
                with self.assertRaisesRegex(ValueError,'auxiliary session inventory changed'):
                    collect_batch(batch,root/'export')
            self.assertFalse((root/'export').exists())

    def test_corrupted_task_and_motion_json_objects_remain_incomplete_evidence(self):
        for target in ('task','motion'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);batch,run,_=self.make_batch(root)
                path=run/('private/inputs/task.json' if target=='task' else 'private/outputs/motion/stream.json')
                write(path,[])
                report=collect_batch(batch,root/'export')
                self.assertFalse(report['complete'])
                self.assertEqual(json.loads((root/'export/batch/model/demo'/path.relative_to(run)).read_text()),[])


class FinderMetadataTests(unittest.TestCase):
    def test_finder_metadata_is_not_evidence(self):
        from scripts.collect_benchmark_batch import _files
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'run').mkdir();(root/'run/events.jsonl').write_text('{}\n')
            (root/'.DS_Store').write_bytes(b'finder');(root/'run/.DS_Store').write_bytes(b'finder')
            self.assertEqual([p.relative_to(root).as_posix() for p in _files(root)],['run/events.jsonl'])


if __name__=='__main__':unittest.main()
