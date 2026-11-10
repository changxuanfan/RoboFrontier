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

    def test_uncompacted_copy_with_a_rerendered_edited_file_notice(self):
        from robofrontier.claude.provenance import copied_history_length
        notice = {'type': 'edited_text_file', 'filename': '/run/workspace/skills.md', 'snippet': ''}
        parent = [row('a', 'user', None, message={'role': 'user', 'content': 'task'}),
                  row('n', 'attachment', 'a', attachment=dict(notice))]
        child = [dict(r, sessionId=CHILD, promptId='child') for r in copy.deepcopy(parent)]
        child[1]['attachment']['displayPath'] = 'skills.md'
        self.write(parent, child)
        source = history(transcript_rows(self.config, PARENT), PARENT)
        self.assertEqual(copied_history_length(source, history(transcript_rows(self.config, CHILD), CHILD)), 2)
        child[1]['attachment']['snippet'] = 'tampered'
        self.write(parent, child)
        with self.assertRaises(ValueError): fork_provenance(PARENT, CHILD, self.config, at=source)

    def test_compacted_copy_orders_a_split_assistant_message_as_its_metadata(self):
        # Observed 2026-11-10: three tool calls of one response were preserved; the file
        # interleaves call/result, the metadata and the copy list calls first.
        from robofrontier.claude.provenance import copied_history_length
        old = row('old', 'user', None, message={'role': 'user', 'content': 'old'})
        calls = [row('c%d' % i, 'assistant', None, message={'role': 'assistant', 'content': 'call %d' % i}) for i in range(3)]
        results = [row('r%d' % i, 'user', None, message={'role': 'user', 'content': 'result %d' % i}) for i in range(3)]
        layout = [old]
        for c, r in zip(calls, results): layout += [c, r]
        for i, r in enumerate(layout[1:], 1): r['parentUuid'] = layout[i-1]['uuid']
        ids = ['c0', 'c1', 'c2', 'r0', 'r1', 'r2']
        meta = {'preservedSegment': {'headUuid': 'c0', 'anchorUuid': 'summary', 'tailUuid': 'r2'},
                'preservedMessages': {'anchorUuid': 'summary', 'uuids': ids, 'allUuids': ids}}
        boundary = row('boundary', 'system', None, subtype='compact_boundary', compactMetadata=meta)
        summary = row('summary', 'user', 'boundary', isCompactSummary=True, message={'role': 'user', 'content': 'summary'})
        post = row('post', 'assistant', 'summary', message={'role': 'assistant', 'content': 'pending delegate'})
        parent = layout + [boundary, summary, post]
        by = {r['uuid']: r for r in layout}
        links = {'c0': 'summary', 'c1': 'c0', 'c2': 'c1', 'r0': 'c0', 'r1': 'c1', 'r2': 'c2'}
        child = copy.deepcopy([boundary, summary] + [dict(by[u], parentUuid=links[u]) for u in ids] + [dict(post, parentUuid='r2')])
        for item in child: item.update(sessionId=CHILD, promptId='child')
        self.write(parent, child)
        source = history(transcript_rows(self.config, PARENT), PARENT)
        fork_provenance(PARENT, CHILD, self.config, at=source)
        self.assertEqual(copied_history_length(source, history(transcript_rows(self.config, CHILD), CHILD)), 9)
        for mutation in ('order', 'content', 'link_outside', 'tail'):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(child)
                if mutation == 'order': bad[2], bad[3] = bad[3], bad[2]
                if mutation == 'content': bad[4]['message']['content'] = 'tampered'
                if mutation == 'link_outside': bad[3]['parentUuid'] = 'old'
                if mutation == 'tail': bad[-1]['parentUuid'] = 'c2'
                self.write(parent, bad)
                with self.assertRaises(ValueError): fork_provenance(PARENT, CHILD, self.config, at=source)

    def test_a_fork_may_keep_only_some_api_retry_notices(self):
        # Observed 2026-11-10 after a network outage: the parent had 11 retry notices, the
        # fork kept 6; a row that hung from a dropped notice hangs from its kept ancestor.
        from robofrontier.claude.provenance import copied_history_length
        retry = lambda ident, parent: row(ident, 'system', parent, subtype='api_error', source='request_retry', retryAttempt=1)
        parent = [row('a', 'user', None, message={'role': 'user', 'content': 'task'}),
                  retry('x1', 'a'), retry('x2', 'x1'),
                  row('b', 'assistant', 'x2', message={'role': 'assistant', 'content': 'delegate'})]
        child = [dict(r, sessionId=CHILD, promptId='child') for r in copy.deepcopy([parent[0], parent[1], parent[3]])]
        child[2]['parentUuid'] = 'x1'
        child.append({'uuid': 'prompt', 'sessionId': CHILD, 'type': 'user', 'message': {'role': 'user', 'content': 'delegate task'}})
        self.write(parent, child)
        source = history(transcript_rows(self.config, PARENT), PARENT)
        copied = history(transcript_rows(self.config, CHILD), CHILD)
        fork_provenance(PARENT, CHILD, self.config, at=source)
        self.assertEqual(copied_history_length(source, copied), 3)
        self.assertEqual(first_input(copied[3:]), 'delegate task')
        child[2]['message'] = {'role': 'assistant', 'content': 'tampered'}
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
