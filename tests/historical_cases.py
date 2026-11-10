"""The 36 cases at the scene revisions the scene builder made by default, before the release.

Tests written against those revisions (configs/environments) use them; the release's own
revisions come from robofrontier.tasks.families.case_specs."""
from robofrontier.tasks.families import case_specs


def cases():
    out = []
    for row in case_specs():
        case = dict(row)
        family, level = case['family'], case['level']
        case['scene_revision'] = {'transport': 4 if level == 1 else 5, 'mosaic': 5, 'dial': 6,
                                  'relay': 5 if level == 1 else 8 if level == 2 else 9}[family]
        out.append(case)
    return out
