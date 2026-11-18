"""Generate the project page's data files from the release and encoded media.

tasks:  site/data/tasks.json, the 36 released cases with their public facts (task type, level,
        arms, workload) and the one-line level differences, from the release and each case's
        public policy task, with the note on each Oracle video from site/data/oracle-videos.json.
media:  site/data/media.json, every video set (Oracle, then one per model) with its base URL
        and per-task front/side files, from the manifests that scripts.site.site_media writes.

    .venv/bin/python -m scripts.site.site_data tasks
    .venv/bin/python -m scripts.site.site_data media SET=BASE_URL=MANIFEST [...] [--film VIDEO POSTER]
    .venv/bin/python -m scripts.site.site_data readme-gallery

A set's BASE_URL is where its files are published (its media repository's Pages site), or a
relative path such as `_media/oracle/` for a local preview.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from roboteam.tasks.config import ROOT

# The published project page; README media links point at it.
PROJECT_PAGE = 'https://changxuanfan.github.io/RoboTeam/'
SITE = ROOT / 'site/data'
ORACLE_VIDEOS = ROOT / 'site/data/oracle-videos.json'

TASK_TYPES = {
    'transport': {
        'name': 'Transport',
        'verb': 'Deliver ordered items to their boards, by handover or staging',
        'unit': 'targets',
        'levels': [
            'Release on the board',
            'Insert blades into fixed blind slots',
            'Insert into a spring-mounted moving board',
        ],
    },
    'mosaic': {
        'name': 'Mosaic',
        'verb': 'Fill every cell of a color pattern with distinct cubes',
        'unit': 'cells',
        'levels': ['Square pockets guide each cube', 'Printed grid lines only', 'No visible grid'],
    },
    'relay': {
        'name': 'Relay',
        'verb': 'Carry long timbers arm to arm and land them over the goal',
        'unit': 'timbers',
        'levels': [
            'Straight timber',
            '63-degree arc timber with a pendant',
            'Deflected timber on passive springs',
        ],
    },
    'dial': {
        'name': 'Dial',
        'verb': 'Turn spring dials and read BEST feedback to crack a hidden code',
        'unit': 'dials',
        'levels': [
            'Fixed dial modules',
            'Lift each module: support and grasp',
            'Lifted modules with an eccentric crank',
        ],
    },
}


def oracle_videos():
    """Per case: how its Oracle video was made, its scene revision and its playback speed.

    A fixed record (site/data/oracle-videos.json); the Oracle programs are not in this repository."""
    return json.loads(ORACLE_VIDEOS.read_text())['videos']


def workload(case):
    """The task type's unit of work for one case, from its released identity."""
    task_type, arms = case['family'], case['arm_count']
    if task_type == 'transport':
        return 3 * arms
    if task_type == 'mosaic':
        rows, cols = map(int, re.search(r'-(\d+)x(\d+)-', case['id']).groups())
        return rows * cols
    if task_type == 'relay':
        return {8: 2, 12: 3, 16: 4}[arms]
    return len(case['dials'])


def tasks():
    import tempfile

    from roboteam.tasks.config import public_task
    from roboteam.tasks.task_types import RELEASE, freeze_public, policy_task

    payload = (ROOT / RELEASE).read_bytes()
    release = json.loads(payload)
    references = oracle_videos()
    rows = []
    for task_type in TASK_TYPES:
        for record in release['families'][task_type]['policy']:
            # The same rule overlay a new policy run receives.
            task = policy_task(record['id'])
            public = public_task(task)
            with tempfile.TemporaryDirectory(prefix='rf-site-public-') as temporary:
                for folder in ('public/inputs', 'private/inputs'):
                    (Path(temporary) / folder).mkdir(parents=True)
                freeze_public(task, Path(temporary), public)
            case = {
                'id': public['id'],
                'family': public['family'],
                'level': public['level'],
                'arm_count': len(task['arms']),
                'dials': public.get('dials'),
            }
            rows.append(
                {
                    'id': case['id'],
                    'family': task_type,
                    'level': case['level'],
                    'arms': case['arm_count'],
                    'workload': workload(case),
                    'unit': TASK_TYPES[task_type]['unit'],
                    'level_note': TASK_TYPES[task_type]['levels'][case['level'] - 1],
                    'objective': public['objective'],
                    'rules': public['rules'],
                    'oracle': references[case['id']],
                }
            )
    rows.sort(key=lambda r: (list(TASK_TYPES).index(r['family']), r['arms'], r['workload'], r['level']))
    document = {
        'schema': 'roboteam.site-tasks.v1',
        'release_sha256': hashlib.sha256(payload).hexdigest(),
        'families': TASK_TYPES,
        'tasks': rows,
    }
    return write(SITE / 'tasks.json', document)


def media(specs, film=None):
    sets = []
    for spec in specs:
        key, base, manifest = spec.split('=', 2)
        data = json.loads(Path(manifest).read_text())
        if data.get('schema') != 'roboteam.site-media.v1':
            raise ValueError('Not a site media manifest: ' + manifest)
        sets.append(
            {
                'key': key,
                'base': base,
                'tasks': {
                    case: {
                        view: {k: record[k] for k in ('video', 'poster', 'size', 'duration_s', 'sha256')}
                        for view, record in views.items()
                    }
                    for case, views in sorted(data['tasks'].items())
                },
            }
        )
    document = {'schema': 'roboteam.site-media-index.v1', 'sets': sets}
    if film:
        document['film'] = {
            'video': film[0],
            'poster': film[1],
            'note': 'A tour of the factory hall: one moment from each zone, then every task type and scale; 3 min 41 s, 1080p. Oracle reference runs, not model results.',
        }
    return write(SITE / 'media.json', document)


def readme_gallery(page=PROJECT_PAGE, readme=ROOT / 'README.md'):
    """Fill the README's gallery block: per task type a 3 x 3 table of task thumbnails."""
    data = json.loads((SITE / 'tasks.json').read_text())
    blocks = []
    for task_type, info in data['families'].items():
        rows = [t for t in data['tasks'] if t['family'] == task_type]
        key = (lambda t: t['workload']) if task_type == 'dial' else (lambda t: t['arms'])
        scales = sorted({key(t) for t in rows})
        head = ''.join(f'<th>{s} {"dials" if task_type == "dial" else "arms"}</th>' for s in scales)
        body = []
        for level in (1, 2, 3):
            cells = []
            for s in scales:
                t = next(t for t in rows if key(t) == s and t['level'] == level)
                cells.append(
                    f'<td><a href="{page}#task={t["id"]}"><img src="docs/media/readme/tasks/{t["id"]}.jpg" '
                    f'width="240" alt="{t["id"]}"></a><br><sub>{t["id"]}</sub></td>'
                )
            body.append(f'<tr><th>L{level}</th>{"".join(cells)}</tr>')
        blocks.append(f'<b>{info["name"]}</b>\n\n<table><tr><th></th>{head}</tr>{"".join(body)}</table>\n')
    text = readme.read_text()
    start, end = '<!-- gallery -->', '<!-- /gallery -->'
    before, rest = text.split(start, 1)
    _, after = rest.split(end, 1)
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
    m = sub.add_parser('media')
    m.add_argument('sets', nargs='+', help='KEY=BASE_URL=MANIFEST')
    m.add_argument('--film', nargs=2, metavar=('VIDEO_URL', 'POSTER_URL'))
    sub.add_parser('readme-gallery')
    args = parser.parse_args(argv)
    if args.command == 'tasks':
        print(tasks())
    elif args.command == 'media':
        print(media(args.sets, args.film))
    else:
        print(readme_gallery())


if __name__ == '__main__':
    main()
