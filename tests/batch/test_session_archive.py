import json
import lzma
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

from robofrontier.runtime import layout as run_layout
from robofrontier.batch import session_archive
from robofrontier.batch.metrics import native_codex_sessions, native_subagent_calls, open_session
from robofrontier.runtime.store import RuntimeStore
from robofrontier.tasks.config import load_harness
from robofrontier.batch.collect import native_matches, session_name

THREAD = '01a19877-10bc-78a1-8113-bf51f6786dd5'
SNAPSHOT = '01a19877-10bc-78a1-8113-bf51f6786dd6'


def idle(path):
    old = time.time()-3600; os.utime(path, (old, old))


def finished_run(root, lifecycle='ended', engine='codex'):
    """A run-v6 run with a bound Controller and a snapshot anchor whose sessions sit in a Codex home."""
    root = Path(root).resolve()
    run = root/'run'; (run/'private/state').mkdir(parents=True); (run/'private/outputs').mkdir()
    (run/'private/inputs').mkdir()
    (run/'private/inputs/manifest.json').write_text(json.dumps({'engine': engine, **run_layout.manifest_record(engine)}))
    store = RuntimeStore(run/'private/state/runtime.sqlite')
    cfg = load_harness(); cfg['topology'] = 'centralized'; cfg['engine'] = engine
    store.initialize('run', cfg, ['A'])
    store.update_agent('Controller', thread_id=THREAD)
    store.put('delegations', {'d1': {'snapshot_thread_id': SNAPSHOT}})
    store.put('lifecycle', lifecycle); store.close()
    home = root/'home'; sessions = []
    for thread in (THREAD, SNAPSHOT):
        session = home/'sessions/2026/11/02'/('rollout-x-%s.jsonl' % thread)
        session.parent.mkdir(parents=True, exist_ok=True)
        session.write_text(''.join(json.dumps(r)+'\n' for r in [
            {'type': 'turn_context', 'payload': {'turn_id': 't1', 'model': 'm', 'effort': 'high'}},
            {'type': 'response_item', 'payload': {'type': 'function_call', 'name': 'spawn_agent'}}]))
        idle(session); sessions.append(session)
    marker = run_layout.path(run, 'codex_home_marker', engine); marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps({'codex_home': str(home)}))
    return run, home, sessions


class SessionArchiveTests(unittest.TestCase):
    def test_compression_is_verified_and_never_removes_the_original_itself(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'a.jsonl'; path.write_text('{"x": 1}\n'*1000)
            record = session_archive.compress_verified(path)
            self.assertTrue(path.exists())
            self.assertEqual(lzma.open(record['path'], 'rt').read(), '{"x": 1}\n'*1000)
            self.assertLess(record['bytes_compressed'], record['bytes_uncompressed'])
            # A copy that does not round-trip is discarded.
            other = Path(tmp)/'b.jsonl'; other.write_text('keep me\n')
            real = session_archive.sha256
            with patch.object(session_archive, 'sha256', lambda p, opener=open: 'bad' if opener is lzma.open else real(p, opener)):
                with self.assertRaisesRegex(ValueError, 'original kept'): session_archive.compress_verified(other)
            self.assertEqual(other.read_text(), 'keep me\n')
            self.assertEqual(sorted(p.name for p in Path(tmp).iterdir()), ['a.jsonl', 'a.jsonl.xz', 'b.jsonl'])

    def test_the_host_copy_keeps_the_home_originals_for_a_continued_segment(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp), lifecycle='interrupted')
            kept = session_archive.keep_codex(run)
            self.assertEqual((kept['threads'], kept['complete']), (2, True))
            self.assertTrue(all(s.exists() for s in sessions))
            folder = run/'private/engine/transcripts'
            self.assertEqual(sorted(p.name for p in folder.glob('*.jsonl')), sorted(s.name for s in sessions))
            index = json.loads((folder/'index.json').read_text())
            self.assertEqual({r['actor'] for r in index['threads']}, {'Controller', 'snapshot:d1'})
            # Reports read the run's own copy first.
            self.assertEqual(native_codex_sessions(run, THREAD), [folder/sessions[0].name])
            # An interrupted run that may still continue is not archived without --final.
            from robofrontier.runtime import segments as run_segments
            store = RuntimeStore(run/'private/state/runtime.sqlite'); store.put('start_at', time.time()-60); store.close()
            with patch.object(run_segments, '_last_frame', lambda run, segment: ('reader', 0, 1., 'pose')):
                with self.assertRaisesRegex(ValueError, 'can still be continued'): session_archive.archive_run(run)
            self.assertTrue(all(s.exists() for s in sessions))
            # One that can no longer continue (here: it never recorded motion) is final.
            self.assertEqual(session_archive.archive_run(run)['archived'], 2)

    def test_a_continuable_run_needs_final_after_its_source_moved_on_or_its_retry_was_used(self):
        from robofrontier.runtime import segments as run_segments
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp), lifecycle='interrupted')
            store = RuntimeStore(run/'private/state/runtime.sqlite')
            store.put('start_at', time.time()-60); store.put('segment', run_segments.AUTOMATIC_CONTINUES); store.close()
            with patch.object(run_segments, '_last_frame', lambda run, segment: ('reader', 0, 1., 'pose')), \
                    patch('robofrontier.runtime.setup.verify_inputs', return_value=['source:robofrontier/edited.py']), \
                    patch.object(run_segments, 'verify_inputs', return_value=['source:robofrontier/edited.py'], create=True):
                with self.assertRaisesRegex(ValueError, 'can still be continued'): session_archive.archive_run(run)
                self.assertTrue(all(s.exists() for s in sessions))
                self.assertEqual(session_archive.archive_run(run, final=True)['archived'], 2)
            # A normal end is final without --final.
            run2, _, _ = finished_run(Path(tmp)/'other', lifecycle='interrupted')
            store = RuntimeStore(run2/'private/state/runtime.sqlite')
            store.put('start_at', time.time()-60); store.event('POLICY_WALL_LIMIT', 'Meta'); store.close()
            with patch.object(run_segments, '_last_frame', lambda run, segment: ('reader', 0, 1., 'pose')):
                self.assertEqual(session_archive.archive_run(run2)['archived'], 2)

    def test_a_final_run_is_archived_and_releases_its_home_copies(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp))
            result = session_archive.archive_run(run)
            self.assertEqual((result['archived'], result['home_sources_removed']), (2, 2))
            self.assertFalse(any(s.exists() for s in sessions))
            archived = native_codex_sessions(run, THREAD)
            self.assertEqual([p.name for p in archived], [sessions[0].name+'.xz'])
            with open_session(archived[0]) as stream: self.assertIn('turn_context', stream.read())
            self.assertEqual(native_subagent_calls(archived), {'spawn_agent': 1})
            manifest = json.loads((run/'private/outputs/session-archive.json').read_text())
            self.assertEqual((len(manifest['files']), len(manifest['home_sources_removed'])), (2, 2))
            # Repeating is harmless; the run's verified copies remain the record.
            self.assertEqual(session_archive.archive_run(run)['archived'], 0)
            self.assertTrue(json.loads((run/'private/engine/transcripts/index.json').read_text())['complete'])
            # Collection finds the archived copy and keeps its suffix.
            root, matches = native_matches('codex', run, home, THREAD)
            self.assertEqual(matches, archived)
            self.assertEqual(session_name(THREAD, matches[0]), THREAD+'.jsonl.xz')

    def test_an_archive_stopped_part_way_resumes_without_losing_a_copy(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp))
            session_archive.keep_codex(run)
            copy = run/'private/engine/transcripts'/sessions[0].name
            session_archive.compress_verified(copy); copy.unlink()  # stopped before the home was released
            result = session_archive.archive_run(run)
            self.assertEqual((result['archived'], result['home_sources_removed']), (1, 2))
            self.assertFalse(any(s.exists() for s in sessions))

    def test_a_home_original_changed_after_the_copy_is_kept(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp))
            session_archive.keep_codex(run)
            real = session_archive.keep_codex
            def keep_then_change(*args, **kwargs):
                kept = real(*args, **kwargs)
                with sessions[1].open('a') as stream: stream.write('{"late": true}\n')
                idle(sessions[1])
                return kept
            with patch.object(session_archive, 'keep_codex', keep_then_change):
                self.assertEqual(session_archive.archive_run(run)['home_sources_removed'], 1)
            self.assertFalse(sessions[0].exists()); self.assertTrue(sessions[1].exists())

    def test_running_runs_and_recently_written_sessions_are_left_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp), lifecycle='running')
            with self.assertRaisesRegex(ValueError, 'finished run'): session_archive.archive_run(run)
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp))
            sessions[0].touch()
            with self.assertRaisesRegex(ValueError, 'modified'): session_archive.archive_run(run)
            self.assertTrue(all(s.exists() for s in sessions))
            self.assertFalse((run/'private/outputs/session-archive.json').exists())

    def test_claude_run_archives_transcripts_in_its_own_config_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            run, home, sessions = finished_run(Path(tmp), engine='claude')
            projects = run_layout.path(run, 'engine_config', 'claude')/'projects/p'
            transcript = projects/(THREAD+'.jsonl'); sidecar = projects/THREAD/'subagents/agent-1.jsonl'
            sidecar.parent.mkdir(parents=True); transcript.write_text('{"type": "user"}\n'); sidecar.write_text('{}\n')
            idle(transcript); idle(sidecar)
            self.assertEqual(session_archive.archive_run(run)['archived'], 2)
            self.assertTrue((projects/(THREAD+'.jsonl.xz')).is_file())
            self.assertFalse(transcript.exists())
            self.assertTrue(all(s.exists() for s in sessions))  # a Claude run never touches a Codex home
            root, matches = native_matches('claude', run, home, THREAD)
            self.assertEqual(matches, [projects/(THREAD+'.jsonl.xz')])


if __name__ == '__main__': unittest.main()
