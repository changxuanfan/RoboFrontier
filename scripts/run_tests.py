"""Run every test: each tests/**/test_*.py module in its own process, in parallel, then every
tests/**/test_*.js with node --test. A module that fails is run once more alone; only a failure
that repeats counts, and the report says which modules failed only in parallel.

    .venv/bin/python -m scripts.run_tests                 # everything, one worker per CPU
    .venv/bin/python -m scripts.run_tests --workers 4 runtime.test_run_segments engines

Arguments name modules (runtime.test_run_segments) or folders under tests/ (engines).
Exits 1 when a failure repeats. CI runs it in the all-tests job (.github/workflows/harness.yml).
"""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
TESTS = ROOT/'tests'


def dotted(path):
    return str(path.relative_to(TESTS).with_suffix('')).replace(os.sep, '.')


def selected(names, found):
    return [f for f in found if not names or any(dotted(f) == n or dotted(f).startswith(n+'.') for n in names)]


def modules(names=()):
    return [dotted(p) for p in selected(names, sorted(TESTS.rglob('test_*.py')))]


def scripts(names=()):
    return selected(names, sorted(TESTS.rglob('test_*.js')))


def check_names(names):
    every = [dotted(p) for p in TESTS.rglob('test_*.*') if p.suffix in ('.py', '.js')]
    unknown = [n for n in names if not any(m == n or m.startswith(n+'.') for m in every)]
    if unknown: raise SystemExit('No such test module or folder: '+', '.join(unknown))


def run_python(module, timeout):
    began = time.monotonic()
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(('tests', 'scripts')))
    try:
        done = subprocess.run([sys.executable, '-m', 'unittest', module], cwd=ROOT, env=env,
                              capture_output=True, text=True, timeout=timeout)
        out, ok = done.stderr+done.stdout, done.returncode == 0
    except subprocess.TimeoutExpired as error:
        out, ok = (error.stderr or b'').decode(errors='replace') if isinstance(error.stderr, bytes) else (error.stderr or ''), False
        out += '\nTimed out after %d s' % timeout
    ran = re.search(r'Ran (\d+) test', out)
    return {'test': module, 'ok': ok, 'tests': int(ran.group(1)) if ran else 0,
            'seconds': round(time.monotonic()-began, 1), 'tail': '' if ok else out[-4000:]}


def run_node(path, timeout):
    began = time.monotonic()
    try:
        done = subprocess.run(['node', '--test', str(path)], cwd=ROOT, capture_output=True, text=True, timeout=timeout)
        out, ok = done.stdout+done.stderr, done.returncode == 0
    except subprocess.TimeoutExpired:
        out, ok = 'Timed out after %d s' % timeout, False
    passed = re.search(r'# pass (\d+)|ℹ pass (\d+)', out)
    count = int(next(g for g in passed.groups() if g)) if passed else 0
    return {'test': str(path.relative_to(ROOT)), 'ok': ok, 'tests': count,
            'seconds': round(time.monotonic()-began, 1), 'tail': '' if ok else out[-4000:]}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('names', nargs='*')
    parser.add_argument('--workers', type=int, default=os.cpu_count() or 4)
    parser.add_argument('--timeout-s', type=int, default=1800, help='Per module (default 1800)')
    parser.add_argument('--no-node', action='store_true', help='Skip the Node tests')
    parser.add_argument('--report', type=Path, help='Write the full result as JSON here')
    args = parser.parse_args(argv)
    began = time.monotonic()
    check_names(args.names)
    jobs = [('py', m) for m in modules(args.names)] + ([] if args.no_node else [('js', p) for p in scripts(args.names)])
    def run(job):
        kind, name = job
        return run_python(name, args.timeout_s) if kind == 'py' else run_node(name, args.timeout_s)
    with ThreadPoolExecutor(max(1, args.workers)) as pool:
        results = list(pool.map(run, jobs))
    first = [job for job, result in zip(jobs, results) if not result['ok']]
    repeated = [r for r in map(run, first) if not r['ok']]
    summary = {'tests': sum(r['tests'] for r in results), 'files': len(results),
               'failed_in_parallel_only': sorted(str(j[1].relative_to(ROOT)) if j[0] == 'js' else j[1] for j in first
                                                 if not any(r['test'] == (str(j[1].relative_to(ROOT)) if j[0] == 'js' else j[1]) for r in repeated)),
               'failed': [r['test'] for r in repeated], 'seconds': round(time.monotonic()-began, 1)}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps({'summary': summary, 'failures': repeated}, indent=1)+'\n')
    for result in repeated:
        print('== FAILED', result['test'], file=sys.stderr)
        print(result['tail'], file=sys.stderr)
    print(json.dumps(summary, indent=1))
    return 1 if repeated else 0


if __name__ == '__main__':
    raise SystemExit(main())
