"""Verify that a Claude Code fork inherited its parent's history, from native transcripts.

`claude --resume PARENT --fork-session` writes the child's transcript under the same
config directory. An uncompacted fork preserves the source history exactly. After
compaction, the CLI resumes at the latest boundary and reinserts the preserved
segment described by that boundary. Only documented-by-observation metadata changes
are normalized; unrecognized history changes fail closed. The model's own claims are
never used as evidence.
"""
import copy
import hashlib
import json
import re
from pathlib import Path

UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')
# Per-session fields that legitimately differ between a parent row and its forked copy.
SESSION_FIELDS = ('sessionId', 'promptId')
# Where the CLI ran when it wrote a row. A fork starts in its launch directory and rewrites
# them on every copied row, so a parent that changed directory differs only in these.
ENVIRONMENT_FIELDS = ('cwd', 'slug', 'gitBranch')


def _without_environment(rows):
    return [{k: v for k, v in row.items() if k not in ENVIRONMENT_FIELDS} for row in rows]


def transcript_rows(config_dir, session_id):
    """Return the parsed rows of exactly one transcript for this native session ID."""
    if not UUID.fullmatch(session_id):
        raise ValueError('Expected a native session UUID')
    matches = sorted(Path(config_dir).glob('projects/*/' + session_id + '.jsonl'))
    if len(matches) != 1:
        raise ValueError('Native transcript missing or ambiguous for session ' + session_id)
    rows = []
    for number, line in enumerate(matches[0].read_text().splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as error:
            raise ValueError('Native transcript line %d is not JSON' % number) from error
        if not isinstance(row, dict):
            raise ValueError('Native transcript line %d is not an object' % number)
        rows.append(row)
    return rows


def history(rows, session_id):
    """Message rows in file order with per-session fields removed; fail on foreign rows."""
    out = []
    for row in rows:
        if not isinstance(row.get('uuid'), str):
            continue  # bookkeeping rows are not conversation history
        if row.get('sessionId') != session_id:
            raise ValueError('Transcript row belongs to a different session')
        out.append({k: v for k, v in row.items() if k not in SESSION_FIELDS})
    if len({row['uuid'] for row in out}) != len(out):
        raise ValueError('Duplicate message UUID inside one transcript')
    return out


class ForkDiverged(ValueError):
    """The histories differ in a way no further transcript write can repair."""


def copied_history_length(source, copied):
    """Verify the inherited prefix and return its length in the child transcript.

    Claude can resume from a compact boundary instead of copying earlier history.
    Its preserved-message metadata describes the only supported reordering and the
    two reparented edges. Unknown compaction formats fail closed.
    """
    if copied[:len(source)] == source or _without_environment(copied[:len(source)]) == _without_environment(source):
        return len(source)
    boundaries = [i for i, row in enumerate(source)
                  if row.get('type') == 'system' and row.get('subtype') == 'compact_boundary']
    if not boundaries:
        raise ValueError('Native fork history does not match the source session')
    boundary = boundaries[-1]
    metadata = source[boundary].get('compactMetadata')
    if not isinstance(metadata, dict):
        raise ValueError('Compaction metadata missing')
    preserved = metadata.get('preservedMessages')
    segment = metadata.get('preservedSegment')
    if not isinstance(preserved, dict) or not isinstance(segment, dict):
        raise ValueError('Unsupported compaction metadata')
    ids = preserved.get('uuids')
    anchor = preserved.get('anchorUuid')
    if (not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids)
            or len(set(ids)) != len(ids) or preserved.get('allUuids') != ids
            or segment.get('headUuid') != ids[0] or segment.get('tailUuid') != ids[-1]
            or segment.get('anchorUuid') != anchor):
        raise ValueError('Invalid preserved compaction segment')
    if boundary < len(ids) or [row['uuid'] for row in source[boundary-len(ids):boundary]] != ids:
        raise ValueError('Preserved segment is not contiguous before compaction')
    anchors = [i for i in range(boundary+1, len(source)) if source[i]['uuid'] == anchor]
    if len(anchors) != 1 or source[anchors[0]].get('isCompactSummary') is not True:
        raise ValueError('Compaction summary anchor is missing or ambiguous')
    anchor_index = anchors[0]
    if anchor_index + 1 >= len(source):
        raise ValueError('Compaction has no post-summary history')
    expected = copy.deepcopy(source[boundary:anchor_index+1] + source[boundary-len(ids):boundary]
                             + source[anchor_index+1:])
    insertion = anchor_index-boundary+1
    expected[insertion]['parentUuid'] = anchor
    expected[insertion+len(ids)]['parentUuid'] = ids[-1]
    actual = copy.deepcopy(copied[:len(expected)])
    for row in expected + actual:
        row.pop('cwd', None)
        row.pop('slug', None)
        row.pop('gitBranch', None)
        # A compacted copy re-renders an edited-file notice with the display path the
        # parent's row lacks; the file name and snippet still must match.
        if row.get('type') == 'attachment' and isinstance(row.get('attachment'), dict) \
                and row['attachment'].get('type') == 'edited_text_file':
            row['attachment'].pop('displayPath', None)
        if row.get('uuid') in ids and row.get('type') == 'assistant' and isinstance(row.get('message'), dict):
            row['message'].pop('usage', None)
    if actual != expected:
        raise ValueError('Compacted native fork history does not match the source session')
    return len(expected)


def fork_provenance(parent, child, config_dir, at=None):
    """Compare the native history prefix; this alone does not prove fork creation.

    `at` pins the parent's history at the fork point (for a delegate, its pending
    delegate call). The parent must still begin with it, and the child must carry the
    exact source or its verified compacted projection, with no later parent row.
    """
    if parent == child:
        raise ValueError('A fork cannot be its own source')
    current = history(transcript_rows(config_dir, parent), parent)
    copy = history(transcript_rows(config_dir, child), child)
    source = current if at is None else at
    if not source:
        raise ValueError('Source session has no recorded history')
    if current[:len(source)] != source:
        raise ForkDiverged('Source session no longer begins with the fork point')
    copied_length = copied_history_length(source, copy)
    if at is not None and {row['uuid'] for row in copy[copied_length:]} & {row['uuid'] for row in current}:
        raise ForkDiverged('Native fork copied source history beyond the fork point')
    digest = hashlib.sha256(json.dumps(source, sort_keys=True).encode()).hexdigest()
    return {'source_thread_id': parent, 'source_ordinal': len(source),
            'source_sha256': digest, 'source_last_uuid': source[-1]['uuid'], 'engine': 'claude'}


def first_input(rows):
    """Text of the first user message in these history rows that is not a tool result.

    A fork taken at a pending tool call starts with rows the CLI adds itself (an error
    result for the unanswered call, a short assistant reply and, when the parent had
    background commands, a system task notification); the host's first message to the
    child follows them.
    """
    for row in rows:
        message = row.get('message')
        if row.get('type') != 'user' or row.get('isMeta') or not isinstance(message, dict):
            continue
        if (row.get('origin') or {}).get('kind') == 'task-notification' and row.get('promptSource') == 'system':
            continue
        content = message.get('content')
        if isinstance(content, str):
            return content
        if isinstance(content, list) and content and all(
                isinstance(item, dict) and item.get('type') == 'text' for item in content):
            return ''.join(item.get('text', '') for item in content)
    return None
