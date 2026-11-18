"""Build the hall that runs load, from the released scenes: benchmark/hall/built.

    python -m scripts.release.build_hall

The folder is not tracked. It ships in the asset archive, so every host loads the same hall;
benchmark/assets.json pins it by the hash of its hall.json.
"""

import argparse
import json

from roboteam.io import ROOT, file_sha256
from roboteam.sim.hall.flat import BUILT, build_hall


def main():
    # Parsed first, so that asking for --help never starts a build.
    argparse.ArgumentParser(description=__doc__.splitlines()[0]).parse_args()
    hall = build_hall()
    path = ROOT / 'benchmark/assets.json'
    config = json.loads(path.read_text())
    config['hall_sha256'] = file_sha256(BUILT / 'hall.json')
    path.write_text(json.dumps(config, indent=2) + '\n')
    print(json.dumps({'folder': str(BUILT), 'hall_sha256': hall['hall_sha256'], 'desks': len(hall['desks'])}))


if __name__ == '__main__':
    main()
