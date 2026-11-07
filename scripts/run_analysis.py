#!/usr/bin/env python3
"""Extract archived runs and compute timing, outcomes and atomic-step metrics.

Data never lives in the repository: pass the data root, the run list and output paths.
A run list is a JSON array of objects with at least `id` and the archive key `k` (see
`robofrontier.run_analysis.archive`); `family` (transport, mosaic, relay, dial) and any other
fields are copied into the outputs.

  run_analysis.py extract  --root DATA --runs runs.json --out extracted/
  run_analysis.py compute  --extracted extracted/ --out metrics.json
  run_analysis.py dial-turns --root DATA --runs runs.json --out dial-turns.json
  run_analysis.py atomic-v2 --extracted extracted/ --metrics metrics.json \\
      --dial-turns dial-turns.json --out atomic-v2.json
  run_analysis.py session-archive package.tar.gz ... --out sessions.json
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from robofrontier.run_analysis import atomic_v2, extract, metrics, session_archive  # noqa: E402
from robofrontier.run_analysis.archive import Run  # noqa: E402


def _extract(job):
    sel, root, cache, out = job
    target = Path(out) / f"{sel['id']}.json"
    if target.exists():
        return sel['id'], 'skip'
    try:
        target.write_text(json.dumps(extract.extract_run(sel, root, cache), ensure_ascii=False))
        return sel['id'], 'ok'
    except Exception:
        return sel['id'], 'FAIL ' + traceback.format_exc()[-400:]


def _compute(path):
    try:
        d = json.loads(Path(path).read_text())
        return dict(metrics.compute(d), ok=True)
    except Exception:
        return dict(id=Path(path).stem, ok=False, err=traceback.format_exc()[-600:])


def _turns(job):
    sel, root, cache = job
    try:
        if sel.get('family') not in (None, 'dial'):
            return sel['id'], None
        return sel['id'], atomic_v2.run_dial_turns(Run(sel['k'], root, cache))
    except Exception:
        return sel['id'], None


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    sub = p.add_subparsers(dest='cmd', required=True)
    for name in ('extract', 'dial-turns'):
        s = sub.add_parser(name)
        s.add_argument('--root', required=True, help='data root that run keys are relative to')
        s.add_argument('--runs', required=True, help='JSON list of runs with id and k')
        s.add_argument('--out', required=True)
        s.add_argument('--cache-dir', help='tar member index cache (default: system temp)')
        s.add_argument('--workers', type=int, default=6)
    s = sub.add_parser('compute')
    s.add_argument('--extracted', required=True)
    s.add_argument('--out', required=True)
    s.add_argument('--workers', type=int, default=6)
    s = sub.add_parser('atomic-v2')
    s.add_argument('--extracted', required=True)
    s.add_argument('--metrics', help='version 1 output of `compute`, reused for Mosaic')
    s.add_argument('--dial-turns', help='output of `dial-turns`; Dial runs are skipped without it')
    s.add_argument('--out', required=True)
    s = sub.add_parser('session-archive')
    s.add_argument('packages', nargs='+')
    s.add_argument('--out', required=True)
    a = p.parse_args(argv)

    if a.cmd in ('extract', 'dial-turns'):
        runs = json.loads(Path(a.runs).read_text())
        if a.cmd == 'extract':
            Path(a.out).mkdir(parents=True, exist_ok=True)
            jobs = [(r, a.root, a.cache_dir, a.out) for r in runs]
            with ProcessPoolExecutor(a.workers) as ex:
                for rid, status in ex.map(_extract, jobs):
                    print(status.split('\n')[0], rid, flush=True)
        else:
            with ProcessPoolExecutor(a.workers) as ex:
                turns = dict(ex.map(_turns, [(r, a.root, a.cache_dir) for r in runs]))
            Path(a.out).write_text(json.dumps(turns))
        return 0
    if a.cmd == 'compute':
        paths = sorted(Path(a.extracted).glob('*.json'))
        with ProcessPoolExecutor(a.workers) as ex:
            rows = list(ex.map(_compute, paths))
        Path(a.out).write_text(json.dumps(rows, ensure_ascii=False))
        print(len(rows), 'runs,', sum(not r['ok'] for r in rows), 'failed')
        return 0
    if a.cmd == 'atomic-v2':
        v1 = (
            {
                r['id']: r.get('atomic')
                for r in json.loads(Path(a.metrics).read_text())
                if r.get('ok')
            }
            if a.metrics
            else {}
        )
        turns = json.loads(Path(a.dial_turns).read_text()) if a.dial_turns else {}
        out = []
        for path in sorted(Path(a.extracted).glob('*.json')):
            d = json.loads(path.read_text())
            rid = d['sel']['id']
            new = atomic_v2.compute(d, v1.get(rid), turns.get(rid))
            if new:
                out.append(dict(id=rid, family=d['sel'].get('family'), v1=v1.get(rid), **new))
        Path(a.out).write_text(json.dumps(out, ensure_ascii=False))
        print(len(out), 'runs')
        return 0
    rows = [
        dict(package=str(x), **session_archive.summarize_session_archive(x)) for x in a.packages
    ]
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
