"""Generate the project page's data files from the release and encoded media.

tasks:  site/data/tasks.json, the 36 released cases with their public facts (family, level,
        arms, workload) and the one-line level differences, from the release and each case's
        public policy task.
media:  site/data/media.json, every video set (Oracle, then one per model) with its base URL
        and per-task front/side files, from the manifests that scripts.site_media writes.

    .venv/bin/python -m scripts.site_data tasks
    .venv/bin/python -m scripts.site_data media SET=BASE_URL=MANIFEST [...] [--film VIDEO POSTER]
    .venv/bin/python -m scripts.site_data readme-gallery

A set's BASE_URL is where its files are published (its media repository's Pages site), or a
relative path such as `_media/oracle/` for a local preview.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

from robofrontier.tasks.config import ROOT

SITE = ROOT / 'site/data'

FAMILIES = {
    'transport': {'name': 'Transport', 'verb': 'Deliver ordered items to their boards, by handover or staging',
                  'unit': 'targets', 'levels': ['Release on the board', 'Insert blades into fixed blind slots',
                                                'Insert into a spring-mounted moving board']},
    'mosaic': {'name': 'Mosaic', 'verb': 'Fill every cell of a color pattern with distinct cubes',
               'unit': 'cells', 'levels': ['Square pockets guide each cube', 'Printed grid lines only',
                                           'No visible grid']},
    'relay': {'name': 'Relay', 'verb': 'Carry long timbers arm to arm and land them over the goal',
              'unit': 'timbers', 'levels': ['Straight timber', '63-degree arc timber with a pendant',
                                            'Deflected timber on passive springs']},
    'dial': {'name': 'Dial', 'verb': 'Turn spring dials and read BEST feedback to crack a hidden code',
             'unit': 'dials', 'levels': ['Fixed dial modules', 'Lift each module: support and grasp',
                                         'Lifted modules with an eccentric crank']},
}


# How each released Oracle recording was qualified (benchmark/release.json), in plain words.
ORACLE_KINDS = {
    'r13_frozen_oracle': ('program', 'R13'),
    'r13_pure_program': ('program', 'R13'),
    'r13_privileged_assisted': ('assisted', 'R13'),
    'pure_program': ('program', 'R11'),
    'privileged_assisted': ('assisted', 'R11'),
    'historical_user_goal_completion_not_relabelled_native': ('reviewed', 'historical'),
}


def oracle(release):
    """Per case: how its Oracle video was made, its revision and its playback speed."""
    out = {}
    for family in release['families'].values():
        for record in family['oracle']:
            kind, revision = ORACLE_KINDS[record['qualification']]
            out[record['id']] = {'kind': kind, 'revision': revision, 'speedup': family['speedup']}
    return out


def workload(case):
    """The family's unit of work for one case, from its released identity."""
    family, arms = case['family'], case['arm_count']
    if family == 'transport': return 3 * arms
    if family == 'mosaic':
        rows, cols = map(int, re.search(r'-(\d+)x(\d+)-', case['id']).groups())
        return rows * cols
    if family == 'relay': return {8: 2, 12: 3, 16: 4}[arms]
    return len(case['dials'])


def tasks():
    import tempfile
    from robofrontier.tasks.config import public_task
    from robofrontier.tasks.families import RELEASE, freeze_public, policy_task
    payload = (ROOT / RELEASE).read_bytes()
    release = json.loads(payload)
    references = oracle(release)
    rows = []
    for family in FAMILIES:
        for record in release['families'][family]['gpt']:
            # The same rule overlay a new policy run receives.
            task = policy_task(record['id'])
            public = public_task(task)
            with tempfile.TemporaryDirectory(prefix='rf-site-public-') as temporary:
                for folder in ('public/inputs', 'private/inputs'):
                    (Path(temporary) / folder).mkdir(parents=True)
                freeze_public(task, Path(temporary), public)
            case = {'id': public['id'], 'family': public['family'], 'level': public['level'],
                    'arm_count': len(task['arms']), 'dials': public.get('dials')}
            rows.append({'id': case['id'], 'family': family, 'level': case['level'], 'arms': case['arm_count'],
                         'workload': workload(case), 'unit': FAMILIES[family]['unit'],
                         'level_note': FAMILIES[family]['levels'][case['level'] - 1],
                         'objective': public['objective'], 'rules': public['rules'],
                         'oracle': references[case['id']]})
    rows.sort(key=lambda r: (list(FAMILIES).index(r['family']), r['arms'], r['workload'], r['level']))
    document = {'schema': 'robofrontier.site-tasks.v1', 'release_sha256': hashlib.sha256(payload).hexdigest(),
                'families': FAMILIES, 'tasks': rows}
    return write(SITE / 'tasks.json', document)


def media(specs, film=None):
    sets = []
    for spec in specs:
        key, base, manifest = spec.split('=', 2)
        data = json.loads(Path(manifest).read_text())
        if data.get('schema') != 'robofrontier.site-media.v1':
            raise ValueError('Not a site media manifest: ' + manifest)
        sets.append({'key': key, 'base': base, 'tasks': {
            case: {view: {k: record[k] for k in ('video', 'poster', 'size', 'duration_s', 'sha256')}
                   for view, record in views.items()} for case, views in sorted(data['tasks'].items())}})
    document = {'schema': 'robofrontier.site-media-index.v1', 'sets': sets}
    if film:
        document['film'] = {'video': film[0], 'poster': film[1],
                            'note': 'A tour of Robo World: one moment from each zone, then every family and scale; 3 min 41 s, 1080p. Oracle reference runs, not model results.'}
    return write(SITE / 'media.json', document)


def readme_gallery(page='https://changxuanfan.github.io/RoboFrontier/', readme=ROOT / 'README.md'):
    """Fill the README's gallery block: per family a 3 x 3 table of task thumbnails."""
    data = json.loads((SITE / 'tasks.json').read_text())
    blocks = []
    for family, info in data['families'].items():
        rows = [t for t in data['tasks'] if t['family'] == family]
        key = (lambda t: t['workload']) if family == 'dial' else (lambda t: t['arms'])
        scales = sorted({key(t) for t in rows})
        head = ''.join(f'<th>{s} {"dials" if family == "dial" else "arms"}</th>' for s in scales)
        body = []
        for level in (1, 2, 3):
            cells = []
            for s in scales:
                t = next(t for t in rows if key(t) == s and t['level'] == level)
                cells.append(f'<td><a href="{page}#task={t["id"]}"><img src="docs/media/readme/tasks/{t["id"]}.jpg" '
                             f'width="240" alt="{t["id"]}"></a><br><sub>{t["id"]}</sub></td>')
            body.append(f'<tr><th>L{level}</th>{"".join(cells)}</tr>')
        blocks.append(f'<b>{info["name"]}</b>\n\n<table><tr><th></th>{head}</tr>{"".join(body)}</table>\n')
    text = readme.read_text()
    start, end = '<!-- gallery -->', '<!-- /gallery -->'
    before, rest = text.split(start, 1); _, after = rest.split(end, 1)
    readme.write_text(before + start + '\n' + '\n'.join(blocks) + end + after)
    return readme


def write(path, document):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=1, ensure_ascii=False) + '\n')
    return path


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('tasks')
    m = sub.add_parser('media'); m.add_argument('sets', nargs='+', help='KEY=BASE_URL=MANIFEST')
    m.add_argument('--film', nargs=2, metavar=('VIDEO_URL', 'POSTER_URL'))
    sub.add_parser('readme-gallery')
    args = parser.parse_args(argv)
    if args.command == 'tasks': print(tasks())
    elif args.command == 'media': print(media(args.sets, args.film))
    else: print(readme_gallery())


if __name__ == '__main__':
    main()
