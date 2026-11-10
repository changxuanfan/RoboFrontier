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


def _normalized(rows, preserved=()):
    """Rows without the metadata a native fork rewrites (observed, not guessed):

    - where the CLI ran (ENVIRONMENT_FIELDS), which the fork sets to its launch directory;
    - the display path of an edited-file notice, which a fork re-renders;
    - the usage of a preserved assistant row, which a compacted copy rewrites.
    Message content always has to match."""
    out = []
    for row in copy.deepcopy(rows):
        for key in ENVIRONMENT_FIELDS: row.pop(key, None)
        notice = row.get('attachment')
        if row.get('type') == 'attachment' and isinstance(notice, dict) and notice.get('type') == 'edited_text_file':
            notice.pop('displayPath', None)
        if row.get('uuid') in preserved and row.get('type') == 'assistant' and isinstance(row.get('message'), dict):
            row['message'].pop('usage', None)
        out.append(row)
    return out


def _is_retry(row):
    """The CLI's own notice of a retried API request; a fork keeps only some of them."""
    return row.get('type') == 'system' and row.get('subtype') == 'api_error'


def _without_retries(rows):
    """Rows without retry notices; a row that hung from one hangs from its nearest kept ancestor."""
    gone = {row['uuid']: row.get('parentUuid') for row in rows if _is_retry(row)}
    out = []
    for row in rows:
        if _is_retry(row): continue
        link, seen = row.get('parentUuid'), set()
        while link in gone and link not in seen: seen.add(link); link = gone[link]
        out.append(row if link == row.get('parentUuid') else dict(row, parentUuid=link))
    return out


def _prefix_holding(rows, count):
    """Length of the shortest prefix of `rows` that holds `count` rows other than retry notices."""
    if count == 0: return 0
    kept = 0
    for index, row in enumerate(rows):
        if not _is_retry(row):
            kept += 1
            if kept == count: return index + 1
    return None


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
    if copied[:len(source)] == source or _normalized(copied[:len(source)]) == _normalized(source):
        return len(source)
    kept = _without_retries(source)
    length = _prefix_holding(copied, len(kept))
    if length is not None and _normalized(_without_retries(copied[:length])) == _normalized(kept):
        return length
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
    # The preserved rows are the ones just before the boundary. The metadata lists them in
    # the order the copy carries them, which can differ from file order: a split assistant
    # message's tool calls come before their results (observed 2026-11-10).
    before = source[boundary-len(ids):boundary] if boundary >= len(ids) else []
    if sorted(row['uuid'] for row in before) != sorted(ids):
        raise ValueError('Preserved segment is not contiguous before compaction')
    rows = {row['uuid']: row for row in before}
    anchors = [i for i in range(boundary+1, len(source)) if source[i]['uuid'] == anchor]
    if len(anchors) != 1 or source[anchors[0]].get('isCompactSummary') is not True:
        raise ValueError('Compaction summary anchor is missing or ambiguous')
    anchor_index = anchors[0]
    if anchor_index + 1 >= len(source):
        raise ValueError('Compaction has no post-summary history')
    expected = _without_retries(source[boundary:anchor_index+1] + [rows[u] for u in ids] + source[anchor_index+1:])
    length = _prefix_holding(copied, len(expected))
    if length is None:
        raise ValueError('Compacted native fork history does not match the source session')
    actual = _without_retries(copied[:length])
    insertion = next(i for i, row in enumerate(expected) if row['uuid'] == anchor) + 1
    relinked = range(insertion, insertion+len(ids)+1)  # the preserved rows and the first row after them
    # Reparented edges: the segment hangs from the summary, each preserved row from an earlier
    # one of the segment (or the summary), and the history after it from the segment's tail.
    seen = {anchor}
    for index in relinked[:-1]:
        link = actual[index].get('parentUuid')
        if link not in seen or (index == insertion and link != anchor):
            raise ValueError('Compacted native fork reparents the preserved segment unexpectedly')
        seen.add(actual[index].get('uuid'))
    if actual[relinked[-1]].get('parentUuid') != ids[-1]:
        raise ValueError('Compacted native fork does not continue from the preserved tail')
    expected, actual = _normalized(expected, ids), _normalized(actual, ids)
    for index in relinked:
        expected[index].pop('parentUuid', None); actual[index].pop('parentUuid', None)
    if actual != expected:
        raise ValueError('Compacted native fork history does not match the source session')
    return length


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
