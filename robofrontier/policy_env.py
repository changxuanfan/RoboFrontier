"""The one Python environment that policy scripts use, frozen when a run is prepared.

A run uses it only when the trusted launcher names it in ROBOFRONTIER_POLICY_ENV; every
other run keeps its earlier behavior. The environment lives outside the home folder and
the repository, is read-only, and holds a standalone Python with a few preinstalled
packages plus an offline wheel store (configs/policy-env/). scripts/build_policy_env.py
builds it. Policy shells get variables() instead of the host's environment, so scripts
see the same interpreter and libraries on every host and for every engine.

Only policy shells get these variables. The native CLIs keep their own environment,
credentials and HOME.
"""
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat

SCHEMA = 'robofrontier.policy-env.v1'
MANIFEST = 'policy-env.json'
ENV_VAR = 'ROBOFRONTIER_POLICY_ENV'
TEMPORARY = '.tmp'  # Under workspace/: this run's temporary files, so they stay with the run.
USER_BASE = '.python'  # Under workspace/: packages this run installs from the wheel store.
SHELL_FILE = 'policy-env.sh'
GUIDE_FILE = 'environment.md'


def _digest_file(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def tree_sha256(root):
    """Every file, link and executable bit under `root` except its manifest."""
    root = Path(root)
    digest = hashlib.sha256()
    for path in sorted(root.rglob('*'), key=lambda p: p.relative_to(root).as_posix()):
        relative = path.relative_to(root).as_posix()
        if relative == MANIFEST:
            continue
        if path.is_symlink():
            entry = 'link', os.readlink(path)
        elif path.is_file():
            executable = bool(path.stat().st_mode & stat.S_IXUSR)
            entry = 'file', str(executable), _digest_file(path)
        else:
            continue
        digest.update(json.dumps([relative, *entry]).encode() + b'\n')
    return digest.hexdigest()


def load(root):
    """The environment's manifest; raises when it is missing or malformed."""
    root = Path(root).resolve()
    manifest = json.loads((root/MANIFEST).read_text())
    if manifest.get('schema') != SCHEMA:
        raise ValueError('Not a policy environment: ' + str(root))
    return manifest


def verify(root):
    """The manifest, after checking every file against it. Raises on any difference."""
    root = Path(root).resolve()
    manifest = load(root)
    actual = tree_sha256(root)
    if actual != manifest['tree_sha256']:
        raise ValueError('Policy environment changed since it was built: ' + str(root))
    return manifest


def selected():
    """The environment named by the trusted launcher, or None for an earlier-style run."""
    value = os.environ.get(ENV_VAR)
    if not value:
        return None
    root = Path(value)
    if not root.is_absolute():
        raise ValueError(ENV_VAR + ' must be an absolute path')
    return root.resolve()


def variables(root, run):
    """What a policy shell receives, in place of the host's environment."""
    root = Path(root).resolve()
    workspace = Path(run).resolve()/'workspace'
    temporary = workspace/TEMPORARY
    manifest = load(root)
    return {'PATH': str(root/manifest['bin']) + ':/usr/bin:/bin', 'LANG': 'C.UTF-8', 'HOME': str(temporary/'home'),
            'TMPDIR': str(temporary), 'TMP': str(temporary), 'TEMP': str(temporary),
            'XDG_CACHE_HOME': str(temporary/'cache'), 'MPLBACKEND': 'Agg', 'MPLCONFIGDIR': str(temporary/'matplotlib'),
            'PYTHONUSERBASE': str(workspace/USER_BASE), 'PIP_USER': '1', 'PIP_NO_INDEX': '1',
            'PIP_FIND_LINKS': str(root/'wheels'), 'PIP_CONFIG_FILE': '/dev/null', 'PIP_NO_CACHE_DIR': '1',
            'PIP_DISABLE_PIP_VERSION_CHECK': '1'}


def shell_text(values):
    """The same variables as a shell file, for a host that sources one before each command.

    Clears the rest of the shell's environment first, so a policy shell sees neither the
    host's settings nor a CLI's credentials. Only what a shell itself maintains stays.
    """
    return ("for name in $(/usr/bin/env | /usr/bin/sed -n 's/^\\([A-Za-z_][A-Za-z0-9_]*\\)=.*/\\1/p'); do\n"
            '  case "$name" in PWD|OLDPWD|SHLVL|_) ;; *) unset "$name" 2>/dev/null ;; esac\n'
            'done\n' + ''.join('export %s=%s\n' % (name, shlex.quote(value)) for name, value in values.items()))


def guide_text(root):
    """What the policy is told about its Python, the same for every engine."""
    manifest = load(root)
    core = ', '.join('%s %s' % (name, manifest['packages'][name]) for name in manifest['core'])
    store = ', '.join(manifest['store'])
    return ('# Python environment\n\n'
            'Your shell provides `python` and `pip`: Python %s with %s.\n\n'
            'These can also be installed, with no network, by `pip install NAME` from a local package store: %s. '
            'Installed packages stay in this run. No other third-party packages are available, and the network is off.\n\n'
            'Keep temporary files in `workspace/%s`, which the shell already uses as TMPDIR. Outside this run\'s '
            '`public/` and `workspace/` folders your scripts can read only the operating system, this Python '
            'environment and `/tmp`, which other runs share.\n\n'
            'The folder above `workspace/` is closed, so `Operation not permitted` on it is expected. `workspace/%s` '
            'belongs to the shell and tools; you do not need to inspect it.\n'
            % (manifest['python'], core, store, TEMPORARY, TEMPORARY))


def prepare_run(run, root):
    """Create the run's own folders and frozen public files; returns the variables."""
    run = Path(run).resolve()
    values = variables(root, run)
    for name in ('HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'MPLCONFIGDIR'):
        Path(values[name]).mkdir(parents=True, exist_ok=True)
    public = run/'public/inputs'
    (public/SHELL_FILE).write_text(shell_text(values))
    (public/GUIDE_FILE).write_text(guide_text(root))
    return values
