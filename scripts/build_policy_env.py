"""Build the read-only Python environment and offline wheel store for policy scripts.

Downloads the pinned Python and the hash-locked packages of configs/policy-env/, so it
needs the network and is run once per host, by an operator, before preparing runs. The
folder name carries a hash of the locks, Python version and platform; an existing valid
environment is kept. Point prepared runs at it with ROBOFRONTIER_POLICY_ENV.

    .venv/bin/python -m scripts.build_policy_env --base /Users/Shared/robofrontier

Each host builds its own folder from the same locks. Linux needs glibc 2.28 or newer,
which the wheels in the locks require. To move to newer versions, update PYTHON and UV,
then relock; --upgrade matters, since compile otherwise keeps a lock's existing versions:

    uv pip compile --universal --python-version 3.12 --generate-hashes --no-header --upgrade core.in store.in -o all.lock
    uv pip compile --universal --python-version 3.12 --generate-hashes --no-header core.in -c all.lock -o core.lock
"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys

from robofrontier.runtime import policy_env

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT/'configs/policy-env'
# The harness's Python series, in a separate installation. configs/policy-env/*.lock are resolved for it.
PYTHON = 'cpython-3.12.16'
UV = ('uvx', '--from', 'uv==0.13.7', 'uv')  # A host's own uv may not know this Python yet.
FORBIDDEN = ('mujoco', 'pybullet', 'ompl', 'torch', 'tensorflow', 'pinocchio', 'drake', 'python-fcl', 'ikpy', 'isaacgym')


def names(path):
    """Package names of a requirements input file, ignoring comments."""
    lines = (line.split('#')[0].strip() for line in path.read_text().splitlines())
    return sorted(re.split(r'[<>=!~; ]', line)[0] for line in lines if line)


def identity():
    digest = hashlib.sha256()
    for name in ('core.lock', 'all.lock'):
        digest.update((CONFIG/name).read_bytes())
    digest.update(json.dumps([PYTHON, sys.platform, platform.machine()]).encode())
    return digest.hexdigest()[:12]


def run(command, **options):
    print('+', ' '.join(str(part) for part in command), flush=True)
    return subprocess.run([str(part) for part in command], check=True, **options)


def make_read_only(root):
    for path in [*Path(root).rglob('*'), Path(root)]:
        if path.is_symlink():
            continue
        path.chmod(stat.S_IMODE(path.stat().st_mode) & ~0o222)


def make_writable(root):
    for path in [Path(root), *Path(root).rglob('*')]:
        if not path.is_symlink() and path.exists():
            path.chmod(stat.S_IMODE(path.stat().st_mode) | stat.S_IWUSR)


def build(base):
    # A shared account's ~/.local packages and pip settings must not reach the build or its manifest.
    os.environ.update(PYTHONNOUSERSITE='1', PIP_CONFIG_FILE=os.devnull)
    base = Path(base).expanduser().resolve()
    target = base/('policy-env-' + identity())
    base.mkdir(parents=True, exist_ok=True)
    # Hosts sharing a base build the same identity; one builds, the others wait and
    # then find its valid environment instead of deleting a tree still being built.
    with open(base/(target.name + '.lock'), 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if (target/policy_env.MANIFEST).is_file():
            policy_env.verify(target)
            print('Existing environment is valid:', target)
            return target
        if target.exists():
            make_writable(target)
            shutil.rmtree(target)
        target.mkdir(parents=True)
        install(target)
        try:
            policy_env.verify(target)
        except Exception:
            # Leave no manifest behind, so the next build starts over instead of
            # re-verifying a broken tree forever.
            make_writable(target)
            (target/policy_env.MANIFEST).unlink(missing_ok=True)
            raise
        return target


def install(target):
    """Install the pinned Python, packages and wheel store into the empty target and seal it."""
    installs = target/'python'
    # Standalone: not the host's Python, so nothing else on the machine affects it.
    run([*UV, 'python', 'install', PYTHON, '--no-bin', '--install-dir', installs])
    folders = [p for p in installs.iterdir() if p.is_dir() and p.name.startswith(PYTHON)]
    if len(folders) != 1:
        raise ValueError('Expected one Python installation, found ' + str(folders))
    python_home = folders[0]
    python = python_home/'bin/python3'
    for marker in python_home.rglob('EXTERNALLY-MANAGED'):
        marker.unlink()  # This Python belongs to the environment; pip may install for the user.
    run([*UV, 'pip', 'install', '--python', python, '--break-system-packages', '--require-hashes', '-r', CONFIG/'core.lock'])
    run([python, '-m', 'pip', 'download', '--disable-pip-version-check', '--require-hashes', '--no-deps', '--only-binary', ':all:',
         '-r', CONFIG/'all.lock', '-d', target/'wheels'])
    run([python, '-m', 'compileall', '-q', python_home/'lib'], stdout=subprocess.DEVNULL)
    listed = json.loads(subprocess.check_output([python, '-m', 'pip', 'list', '--format=json', '--disable-pip-version-check']))
    installed = {re.sub(r'[-_.]+', '-', item['name']).lower(): item['version'] for item in listed}
    wheels = sorted(path.name for path in (target/'wheels').glob('*.whl'))
    for name in FORBIDDEN:
        if name in installed or any(re.sub(r'[-_.]+', '-', wheel).lower().startswith(name + '-') for wheel in wheels):
            raise ValueError('Forbidden package in the policy environment: ' + name)
    core = names(CONFIG/'core.in')
    version = subprocess.check_output([python, '-c', 'import platform; print(platform.python_version())'], text=True).strip()
    manifest = {'schema': policy_env.SCHEMA, 'id': target.name, 'python': version, 'bin': str(python_home.relative_to(target)/'bin'),
                'platform': [sys.platform, platform.machine()], 'core': core,
                'store': names(CONFIG/'store.in'), 'packages': {name: installed[name] for name in core},
                'installed': installed, 'wheels': wheels,
                'locks_sha256': {name: hashlib.sha256((CONFIG/name).read_bytes()).hexdigest() for name in ('core.lock', 'all.lock')}}
    manifest['tree_sha256'] = policy_env.tree_sha256(target)
    (target/policy_env.MANIFEST).write_text(json.dumps(manifest, indent=1) + '\n')
    make_read_only(target)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument('--base', required=True, help='Folder outside the home folder and the repository')
    args = parser.parse_args(argv)
    target = build(args.base)
    size = sum(p.stat().st_size for p in target.rglob('*') if p.is_file() and not p.is_symlink())
    print(json.dumps({'root': str(target), 'bytes': size, 'tree_sha256': policy_env.load(target)['tree_sha256']}))


if __name__ == '__main__':
    main()
