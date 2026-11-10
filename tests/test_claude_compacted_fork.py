"""Fork provenance after Claude's preserved-message compaction."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

from robofrontier.claude.provenance import first_input, fork_provenance, history, transcript_rows

PARENT = '44444444-4444-4444-8444-444444444444'
CHILD = '55555555-5555-4555-8555-555555555555'


def row(ident, kind, parent=None, **extra):
    return {'uuid': ident, 'sessionId': PARENT, 'promptId': 'p', 'type': kind,
            'parentUuid': parent, 'cwd': '/parent', 'slug': 'parent', 'gitBranch': 'main', **extra}


def compacted_source():
    old = row('old', 'user', message={'role': 'user', 'content': 'old context'})
    head = row('head', 'assistant', 'old', message={'role': 'assistant', 'content': 'preserved',
                                                   'usage': {'input_tokens': 10}})
    tail = row('tail', 'user', 'head', message={'role': 'user', 'content': 'preserved response'})
    meta = {'preservedSegment': {'headUuid': 'head', 'anchorUuid': 'summary', 'tailUuid': 'tail'},
            'preservedMessages': {'anchorUuid': 'summary', 'uuids': ['head', 'tail'],
                                  'allUuids': ['head', 'tail']}}
    boundary = row('boundary', 'system', None, subtype='compact_boundary', compactMetadata=meta)
    attachment = row('attachment', 'attachment', 'boundary')
    summary = row('summary', 'user', 'attachment', isCompactSummary=True,
                  message={'role': 'user', 'content': 'compressed summary'})
    post = row('post', 'assistant', 'summary', message={'role': 'assistant', 'content': 'pending delegate'})
    return [old, head, tail, boundary, attachment, summary, post]


def child_copy(source):
    # Native CLI moves the preserved segment after the summary and rewires its ends.
    rows = copy.deepcopy(source[3:6] + source[1:3] + source[6:])
    rows[3]['parentUuid'] = 'summary'
    rows[3]['message']['usage'] = {'input_tokens': 0}
    rows[5]['parentUuid'] = 'tail'
    for item in rows:
        item.update(sessionId=CHILD, promptId='child', cwd='/child', slug='child', gitBranch='other')
    return rows


class CompactedForkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.config = Path(self.temp.name)
        self.folder = self.config/'projects/project'
        self.folder.mkdir(parents=True)
        self.source = compacted_source()

    def tearDown(self): self.temp.cleanup()

    def write(self, parent, child):
        for sid, rows in ((PARENT, parent), (CHILD, child)):
            (self.folder/(sid+'.jsonl')).write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def test_compacted_fork_keeps_boundary_and_child_input(self):
        from robofrontier.claude.provenance import copied_history_length
        child = child_copy(self.source)
        child.append({'uuid': 'prompt', 'sessionId': CHILD, 'type': 'user',
                      'message': {'role': 'user', 'content': 'delegate task'}})
        self.write(self.source, child)
        source = history(transcript_rows(self.config, PARENT), PARENT)
        copied = history(transcript_rows(self.config, CHILD), CHILD)
        proof = fork_provenance(PARENT, CHILD, self.config, at=source)
        self.assertEqual(proof['source_ordinal'], len(source))
        self.assertEqual(copied_history_length(source, copied), 6)
        self.assertEqual(first_input(copied[copied_history_length(source, copied):]), 'delegate task')

    def test_edited_file_display_path_and_background_task_notice_are_cli_rows(self):
        # Observed in a real Opus run (2026-11-10): a compacted copy adds `displayPath` to an
        # edited-file notice, and a parent with background commands gets their notice first.
        from robofrontier.claude.provenance import copied_history_length
        notice = {'type': 'edited_text_file', 'filename': '/run/workspace/handoff.md', 'snippet': '1\tplan'}
        self.source[4]['attachment'] = dict(notice)
        child = child_copy(self.source)
        child[1]['attachment'] = dict(notice, displayPath='handoff.md')
        child.append({'uuid': 'tasks', 'sessionId': CHILD, 'type': 'user', 'promptSource': 'system',
                      'origin': {'kind': 'task-notification'},
                      'message': {'role': 'user', 'content': '<task-notification>stopped</task-notification>'}})
        child.append({'uuid': 'prompt', 'sessionId': CHILD, 'type': 'user', 'promptSource': 'sdk',
                      'message': {'role': 'user', 'content': 'delegate task'}})
        self.write(self.source, child)
        source = history(transcript_rows(self.config, PARENT), PARENT)
        copied = history(transcript_rows(self.config, CHILD), CHILD)
        fork_provenance(PARENT, CHILD, self.config, at=source)
        self.assertEqual(first_input(copied[copied_history_length(source, copied):]), 'delegate task')
        for change in ('snippet', 'filename'):
            with self.subTest(change=change):
                child[1]['attachment'] = dict(notice, displayPath='handoff.md', **{change: 'tampered'})
                self.write(self.source, child)
                with self.assertRaises(ValueError): fork_provenance(PARENT, CHILD, self.config, at=source)
        # A model-visible user message, even one shaped like a notice, is still the first input.
        self.assertEqual(first_input([{'type': 'user', 'message': {'role': 'user', 'content': '<task-notification>x'}}]),
                         '<task-notification>x')

    def test_uncompacted_copy_of_a_parent_that_changed_directory(self):
        # Observed 2026-11-10: the parent had cd'd into workspace/tools; the copy carried the
        # fork's launch directory on every row and nothing else differed.
        from robofrontier.claude.provenance import copied_history_length
        parent = [row('a', 'user', None, message={'role': 'user', 'content': 'task'}),
                  row('b', 'assistant', 'a', cwd='/run/workspace/tools', message={'role': 'assistant', 'content': 'delegate'})]
        child = [dict(r, sessionId=CHILD, promptId='child', cwd='/run/workspace') for r in parent]
        child.append({'uuid': 'prompt', 'sessionId': CHILD, 'type': 'user', 'message': {'role': 'user', 'content': 'delegate task'}})
        self.write(parent, child)
        source = history(transcript_rows(self.config, PARENT), PARENT)
        copied = history(transcript_rows(self.config, CHILD), CHILD)
        fork_provenance(PARENT, CHILD, self.config, at=source)
        self.assertEqual(first_input(copied[copied_history_length(source, copied):]), 'delegate task')
        child[1]['message'] = {'role': 'assistant', 'content': 'tampered'}
        self.write(parent, child)
        with self.assertRaises(ValueError): fork_provenance(PARENT, CHILD, self.config, at=source)

    def test_tampered_missing_reordered_or_late_history_is_rejected(self):
        for mutation in ('summary', 'preserved_content', 'missing', 'reordered', 'parent_link',
                         'late', 'metadata', 'unknown_layout'):
            with self.subTest(mutation=mutation):
                parent = copy.deepcopy(self.source)
                child = child_copy(parent)
                if mutation == 'summary': child[2]['message']['content'] = 'tampered'
                if mutation == 'preserved_content': child[3]['message']['content'] = 'tampered'
                if mutation == 'missing': child.pop(4)
                if mutation == 'reordered': child[3], child[4] = child[4], child[3]
                if mutation == 'parent_link': child[3]['parentUuid'] = 'old'
                if mutation == 'metadata': parent[3]['compactMetadata']['preservedMessages']['uuids'] = ['tail', 'head']
                if mutation == 'unknown_layout':
                    parent[3]['compactMetadata'].pop('preservedMessages')
                    child[0]['compactMetadata'].pop('preservedMessages')
                if mutation == 'late':
                    later = row('late', 'user', 'post', message={'role':'user','content':'after fork'})
                    parent.append(later)
                    child.append({**later, 'sessionId': CHILD})
                self.write(parent, child)
                source = history(parent[:len(self.source)], PARENT)
                with self.assertRaises(ValueError): fork_provenance(PARENT, CHILD, self.config, at=source)
