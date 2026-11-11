"""Engine-neutral benchmark helpers: .env loading and released case selection."""
import os
from pathlib import Path
import re
import shlex

from ..tasks.families import ROOT, RELEASE, read


def env_file_names(path, *names):
    """Which of `names` an .env file sets, without reading their values into the environment."""
    found = set()
    for line in Path(path).read_text().splitlines():
        line = line.strip()
        if line.startswith('export '): line = line[7:].lstrip()
        key, sep, _ = line.partition('=')
        if sep and key in names: found.add(key)
    return sorted(found)


def load_env(path):
    """Load literal KEY=value entries; existing process environment wins."""
    path = Path(path)
    if not path.is_file():
        return
    for number, line in enumerate(path.read_text().splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].lstrip()
        key, sep, raw = line.partition('=')
        if not sep or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]*', key):
            raise ValueError(f'Invalid .env entry at line {number}')
        try:
            values = shlex.split(raw, comments=True, posix=True)
        except ValueError as error:
            raise ValueError(f'Invalid .env value at line {number}') from error
        if len(values) > 1:
            raise ValueError(f'Quote whitespace in .env value at line {number}')
        os.environ.setdefault(key, values[0] if values else '')


def select_cases(families=None, cases=None, level=None, min_arms=False):
    """Resolve selection from released task metadata, without creating a world."""
    release=read(ROOT/RELEASE)
    if families and set(families)-set(release['families']):
        raise ValueError('Unknown task families')
    selected=[]
    for name,family in release['families'].items():
        if families and name not in families:continue
        rows=[]
        for case in family['gpt']:
            task=read(ROOT/case['directory']/'task.json')
            if cases and case['id'] not in cases or level is not None and task['level']!=level:continue
            rows.append(dict(case_id=case['id'],family=name,level=task['level'],arms=len(task['arms']),
                             directory=case['directory'],qualification=case['qualification']))
        if min_arms and rows:
            minimum=min(row['arms'] for row in rows)
            rows=[row for row in rows if row['arms']==minimum]
        selected.extend(rows)
    if not selected or cases and set(cases)-{row['case_id'] for row in selected}:
        raise ValueError('Unknown/empty released cases or conflicting selection filters')
    return selected
