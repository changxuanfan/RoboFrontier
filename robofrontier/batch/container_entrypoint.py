"""Container entry: require local runtime storage before invoking the native CLI."""
import os
from pathlib import Path

from ..configuration import ROOT


def main():
    from .slurm_job import _local_storage
    from ..cli import main as native_main
    for path in (ROOT/'runs', ROOT/'.robofrontier'):
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        _local_storage(path)
    temporary = Path(os.environ.get('TMPDIR', '/tmp/robofrontier'))
    temporary.mkdir(parents=True, exist_ok=True, mode=0o700)
    return native_main()


if __name__ == '__main__':
    raise SystemExit(main())
