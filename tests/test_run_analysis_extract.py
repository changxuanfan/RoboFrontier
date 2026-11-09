"""Run-analysis extraction on small synthetic runs: model-busy spans and session archives."""

import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest

from robofrontier.run_analysis import extract, session_archive
from robofrontier.run_analysis.archive import Run


def stamp(s):
    return '2026-11-01T00:%02d:%02d.000Z' % (s // 60, s % 60)


def rollout(long_arguments):
    """A Codex rollout: model 0-10 s, tool 10-20 s, model 20-30 s. The call_id follows the arguments."""
    args = json.dumps({'code': 'x' * (2000 if long_arguments else 10)})
    rows = [
        dict(timestamp=stamp(0), type='event_msg', payload=dict(type='task_started')),
        dict(timestamp=stamp(10), type='response_item', payload=dict(
            type='function_call', status='completed', id='fc1', name='exec', arguments=args, call_id='call_1')),
        dict(timestamp=stamp(20), type='response_item', payload=dict(
            type='function_call_output', call_id='call_1', output='ok')),
        dict(timestamp=stamp(30), type='event_msg', payload=dict(type='task_complete')),
    ]
    return ''.join(json.dumps(r, separators=(',', ':')) + '\n' for r in rows)


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))

    def spans(self, long_arguments):
        folder = self.root / ('run%d' % long_arguments) / 'private/engine/transcripts'
        folder.mkdir(parents=True)
        (folder / 'a.jsonl').write_text(rollout(long_arguments))
        (folder / 'index.json').write_text(json.dumps(dict(
            threads=[dict(actor='Controller', file='private/engine/transcripts/a.jsonl')])))
        spans, src = extract.transcripts(Run('run%d' % long_arguments, self.root))
        self.assertEqual(src, 'codex-transcript')
        return [round(b - a) for _, a, b in spans]

    def test_model_time_after_a_long_tool_call_is_kept(self):
        self.assertEqual(self.spans(False), [10, 10])
        self.assertEqual(self.spans(True), [10, 10])

    def test_session_archive_finds_call_ids_after_long_arguments(self):
        data = rollout(True).encode()
        package = self.root / 'p.tar.gz'
        with tarfile.open(package, 'w:gz') as tar:
            info = tarfile.TarInfo('p/sessions/a.jsonl')
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
        O = session_archive.summarize_session_archive(package)
        self.assertEqual([round(b - a) for a, b in O['spans']], [10, 10])


if __name__ == '__main__':
    unittest.main()
