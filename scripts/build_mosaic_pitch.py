"""Build Mosaic R15 (71 mm grid pitch) from R14 into benchmark/mosaic/ and update the release."""
import argparse

from robofrontier.suite.mosaic_pitch import build

if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--no-render', action='store_true', help='Skip the local preview images')
    a = p.parse_args()
    for case in build(render=not a.no_render):
        print(case['id'], case['directory'], flush=True)
