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

Object poses (lost items, goal positions) and Dial angles come from each run's motion recording
when its process log is events-60s, which keeps poses only every 60 s (`--motion always` reads
the recording for every run that has one).

Every command exits 1 when a selected run is missing, fails or lacks the data it needs;
the failing ids are printed, and dial-turns and atomic-v2 also write them beside --out
(`<out>.errors.json`, `<out>.skipped.json`). Extraction writes each record atomically and
redoes any existing record that does not load.
"""

import argparse
from concurrent.futures import ProcessPoolExecutor
import json
import os
from pathlib import Path
import sys
import traceback

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from robofrontier.run_analysis import atomic_v2, extract, metrics, session_archive  # noqa: E402
from robofrontier.run_analysis.archive import Run  # noqa: E402


def _valid_record(path):
    """An earlier extraction that loads and read at least one file."""
    try:
        return json.loads(path.read_text()).get('nfiles', 0) > 0
    except (OSError, ValueError, AttributeError):
        return False


def _write_atomic(path, text):
    tmp = path.with_name(path.name + '.tmp.%d' % os.getpid())
    tmp.write_text(text)
    os.replace(tmp, path)


def _extract(job):
    sel, root, cache, out, motion = job
    target = Path(out) / f"{sel['id']}.json"
    if target.exists() and _valid_record(target):
        return sel['id'], 'skip'
    try:
        _write_atomic(target, json.dumps(extract.extract_run(sel, root, cache, motion), ensure_ascii=False))
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
    """(id, turns or None, error or None); None turns without error: not a Dial run."""
    sel, root, cache, motion = job
    if sel.get('family') not in (None, 'dial'):
        return sel['id'], None, None
    try:
        run = Run(sel['k'], root, cache)
        try:
            return sel['id'], atomic_v2.run_dial_turns(run, motion=motion), None
        finally:
            run.close()
    except Exception:
        return sel['id'], None, traceback.format_exc()[-600:]


def _skip_reason(d, turns, have_turns):
    """Why atomic_v2.compute gave nothing for a record, and whether that is missing data."""
    S = d.get('suite')
    if not d.get('nfiles'):
        return 'no files', True
    if not (S and S.get('lines')):
        return 'no evaluator rows', True
    if not metrics.Clock(d).ok:
        return 'no sim/wall clock (actions without sim times)', True
    if d['sel'].get('family') == 'dial':
        if not have_turns:
            return 'no --dial-turns given', False
        if turns is None:
            return 'no dial turns for this run', True
        if isinstance(turns, dict) and turns.get('unknown'):
            return 'dial turns unknown: ' + turns['unknown'], False
    return 'family %s has no version 2 rule' % d['sel'].get('family'), False


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
        s.add_argument(
            '--motion',
            choices=extract.MOTION_MODES,
            default='always',
            help='read object poses and dial angles from the motion recording of every run '
            'that has one (always, default) or only for events-60s logs (sparse)',
        )
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
            jobs = [(r, a.root, a.cache_dir, a.out, a.motion) for r in runs]
            failed = []
            with ProcessPoolExecutor(a.workers) as ex:
                for rid, status in ex.map(_extract, jobs):
                    print(status.split('\n')[0], rid, flush=True)
                    if status.startswith('FAIL'):
                        failed.append(rid)
                        print('FAIL', rid, status[5:], file=sys.stderr)
            print(len(jobs), 'runs,', len(failed), 'failed', flush=True)
            return 1 if failed else 0
        turns, errors = {}, {}
        with ProcessPoolExecutor(a.workers) as ex:
            for rid, value, err in ex.map(_turns, [(r, a.root, a.cache_dir, a.motion) for r in runs]):
                if err:
                    errors[rid] = err
                    print('FAIL', rid, err.strip().splitlines()[-1], file=sys.stderr)
                else:
                    turns[rid] = value
        _write_atomic(Path(a.out), json.dumps(turns))
        err_path = Path(str(a.out) + '.errors.json')
        if errors:
            _write_atomic(err_path, json.dumps(errors, indent=1))
        elif err_path.exists():
            err_path.unlink()
        print(len(turns), 'runs,', len(errors), 'failed', flush=True)
        return 1 if errors else 0
    if a.cmd == 'compute':
        paths = sorted(Path(a.extracted).glob('*.json'))
        with ProcessPoolExecutor(a.workers) as ex:
            rows = list(ex.map(_compute, paths))
        _write_atomic(Path(a.out), json.dumps(rows, ensure_ascii=False))
        bad = [r['id'] for r in rows if not r['ok']]
        for rid in bad:
            print('FAIL', rid, file=sys.stderr)
        print(len(rows), 'runs,', len(bad), 'failed')
        return 1 if bad else 0
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
        out, skipped = [], []
        for path in sorted(Path(a.extracted).glob('*.json')):
            try:
                d = json.loads(path.read_text())
                rid = d['sel']['id']
                new = atomic_v2.compute(d, v1.get(rid), turns.get(rid))
            except Exception:
                skipped.append(dict(id=path.stem, reason='error: ' + traceback.format_exc()[-300:], missing=True))
                continue
            if new:
                out.append(dict(id=rid, family=d['sel'].get('family'), v1=v1.get(rid), **new))
            else:
                reason, missing = _skip_reason(d, turns.get(rid), bool(a.dial_turns))
                skipped.append(dict(id=rid, family=d['sel'].get('family'), reason=reason, missing=missing))
        _write_atomic(Path(a.out), json.dumps(out, ensure_ascii=False))
        _write_atomic(Path(str(a.out) + '.skipped.json'), json.dumps(skipped, ensure_ascii=False, indent=1))
        for x in skipped:
            print('SKIP' if not x['missing'] else 'MISSING', x['id'], x['reason'].splitlines()[0],
                  file=sys.stderr)
        missing = sum(x['missing'] for x in skipped)
        print(len(out), 'runs,', len(skipped), 'skipped,', missing, 'missing data')
        return 1 if missing else 0
    rows = [
        dict(package=str(x), **session_archive.summarize_session_archive(x)) for x in a.packages
    ]
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False))
    return 0


if __name__ == '__main__':
    sys.exit(main())
