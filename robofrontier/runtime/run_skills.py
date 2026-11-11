"""The run's shared lessons file, read and extended through the robot tool.

In a full run every role reads workspace/skills.md and edits it with its own file
tools. A robot_only role has none, so the runtime does it: `skills` lists headings,
returns entries and appends an entry or a revision. Earlier text is never changed or
removed, which is also the rule a full run's roles follow (the "Run skills" section of
the Skill). The runtime handles one request at a time, so appends never collide.
"""
import os
from pathlib import Path
import re
import tempfile

from . import layout as run_layout

MAX_BODY_CHARS = 20_000
MAX_HEADING_CHARS = 400
ACTIONS = ('headings', 'read', 'append', 'revise')


def path(run):
    return run_layout.path(run, 'skills_file')


def parse(text):
    """(preamble, entries): an entry is the lines from a `## ` heading to the next one."""
    lines = text.splitlines(keepends=True)
    starts = [index for index, line in enumerate(lines) if line.startswith('## ')]
    preamble = ''.join(lines[:starts[0]] if starts else lines)
    entries = [''.join(lines[start:end]) for start, end in zip(starts, starts[1:] + [len(lines)])]
    return preamble, entries


def _line(value, name):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(name + ' must be a nonempty string')
    value = value.strip()
    if '\n' in value or '\r' in value or len(value) > MAX_HEADING_CHARS:
        raise ValueError(name + ' must be one line of at most %d characters' % MAX_HEADING_CHARS)
    return value


def _body(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('body must be a nonempty string')
    if len(value) > MAX_BODY_CHARS:
        raise ValueError('body is limited to %d characters' % MAX_BODY_CHARS)
    lines = value.strip('\n').splitlines()
    if any(re.match(r'#{1,3} ', line) for line in lines):
        raise ValueError('body lines must not start with a Markdown heading; the tool writes the heading')
    return '\n'.join(line.rstrip() for line in lines) + '\n'


def _write(target, text):
    fd, temporary = tempfile.mkstemp(prefix=target.name + '.', suffix='.tmp', dir=target.parent)
    try:
        with os.fdopen(fd, 'w') as output:
            output.write(text)
        os.replace(temporary, target)
    finally:
        try: os.unlink(temporary)
        except FileNotFoundError: pass


def _entry(entries, number):
    if type(number) is not int or not 1 <= number <= len(entries):
        raise ValueError('entry must be a number from the headings list (1..%d)' % len(entries))
    return number - 1


def handle(run, actor, data):
    """The result of one `skills` request from `actor`."""
    action = data.get('action')
    if action not in ACTIONS:
        raise ValueError('skills needs action: ' + ', '.join(ACTIONS))
    allowed = {'headings': set(), 'read': {'entries'}, 'append': {'heading', 'body'},
               'revise': {'entry', 'heading', 'body'}}[action]
    if set(data) - allowed - {'action'}:
        raise ValueError('skills %s accepts only: %s' % (action, ', '.join(sorted(allowed)) or 'no other field'))
    target = Path(path(run))
    preamble, entries = parse(target.read_text())
    if action == 'headings':
        return {'entries': [{'entry': number, 'heading': entry.splitlines()[0],
                             'revisions': [line for line in entry.splitlines() if line.startswith('### ')]}
                            for number, entry in enumerate(entries, 1)]}
    if action == 'read':
        selected = data.get('entries')
        if selected is None:
            return {'text': preamble + ''.join(entries)}
        if not isinstance(selected, list) or not selected:
            raise ValueError('entries must be a nonempty list of entry numbers')
        return {'text': '\n'.join(entries[_entry(entries, number)].rstrip('\n') + '\n' for number in selected)}
    body = _body(data.get('body'))
    heading = _line(data.get('heading'), 'heading')
    if action == 'append':
        heading = heading if heading.startswith('## ') else '## ' + heading.lstrip('# ')
        # Earlier text stays byte for byte; only the new entry is added after it.
        text = (preamble + ''.join(entries)).rstrip('\n') + '\n\n' + heading + '\n' + body
        number, written = len(entries) + 1, heading
    else:
        index = _entry(entries, data.get('entry'))
        revision = 2 + sum(line.startswith('### rev ') for line in entries[index].splitlines())
        # The runtime states the revision number and the writing role itself.
        if heading.startswith('#'):
            raise ValueError('For a revision, heading is only what changed, in one line; the tool writes '
                             '"### rev <n> — <role> —" before it')
        written = '### rev %d — %s — %s' % (revision, actor, heading)
        last = index == len(entries) - 1
        entries[index] = entries[index].rstrip('\n') + '\n\n' + written + '\n' + body + ('' if last else '\n')
        text = preamble + ''.join(entries)
        number = index + 1
    _write(target, text)
    return {'written': True, 'entry': number, 'heading': written}
