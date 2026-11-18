"""The one Python environment that policy scripts use, frozen when a run is prepared.

A run uses it when the trusted launcher names it in ROBOTEAM_POLICY_ENV. On macOS
`roboteam prepare` names the default one (default_root) unless that variable is set,
`off` keeping the host's Python. Runs already prepared keep what they froze. The environment lives outside the home folder and
the repository, is read-only, and holds a standalone Python with a few preinstalled
packages plus an offline wheel store (roboteam/runtime/sandbox/policy-env/). scripts/release/build_policy_env.py
builds it. Policy shells get variables() instead of the host's environment, so scripts
see the same interpreter and libraries on every host and for every harness.

Only policy shells get these variables. The native CLIs keep their own environment,
credentials and HOME.
"""

import hashlib
import json
import os
import shlex
import stat
import subprocess
from pathlib import Path

SCHEMA = 'roboteam.policy-env.v1'
MANIFEST = 'policy-env.json'
ENV_VAR = 'ROBOTEAM_POLICY_ENV'
TEMPORARY = '.tmp'  # Under workspace/: this run's temporary files, so they stay with the run.
USER_BASE = '.python'  # Under workspace/: packages this run installs from the wheel store.
SHELL_FILE = 'policy-env.sh'
GUIDE_FILE = 'environment.md'
RECEIPT_SUFFIX = '.check.json'
RECEIPT_SCHEMA = 'roboteam.policy-env-check.v2'
CLIS = {'codex': 'codex', 'claude': 'claude'}
# What each harness's policy shells run in: the Codex tool backend, or Claude Code's Bash isolation.
ISOLATION = {'codex': 'tool_backend', 'claude': 'bash_isolation'}


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
    manifest = json.loads((root / MANIFEST).read_text())
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


def receipt_path(root):
    """Beside the read-only environment, one per build.

    A build on shared storage has one receipt for every node that uses it: the check passes the
    build with the harnesses, sandboxes and CLIs it ran, not each node. A node without what Codex's
    confined tools need (unprivileged user namespaces) fails each command rather than running it
    less confined.
    """
    root = Path(root).resolve()
    return root.parent / (root.name + RECEIPT_SUFFIX)


def cli_version(binary, env=None, timeout_s=30):
    """What `binary --version` prints, or None when it is missing, fails or does not answer in time."""
    try:
        done = subprocess.run(
            [binary, '--version'],
            env=env,
            capture_output=True,
            text=True,
            stdin=subprocess.DEVNULL,
            timeout=timeout_s,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return (done.stdout.strip() or None) if done.returncode == 0 else None


def combination(harness, isolation, env=None):
    """One harness as a run would use it here: its sandbox and the CLI version on PATH."""
    return {'harness': harness, ISOLATION[harness]: isolation, 'cli': cli_version(CLIS[harness], env)}


def require_checked(root, manifest, wanted=None):
    """Refuse an environment whose build scripts/release/check_policy_env.py has not passed.

    With `wanted` (a combination()), also refuse when the check did not run that harness with
    that sandbox and CLI version.
    """
    rerun = 'Run scripts/release/check_policy_env.py on this build first: ' + str(root)
    try:
        receipt = json.loads(receipt_path(root).read_text())
    except (OSError, ValueError):
        raise ValueError(rerun) from None
    if (
        not isinstance(receipt, dict)
        or not receipt.get('passed')
        or receipt.get('tree_sha256') != manifest['tree_sha256']
    ):
        raise ValueError(rerun)
    if receipt.get('schema') != RECEIPT_SCHEMA or not isinstance(receipt.get('checked'), list):
        raise ValueError(
            'This build\'s check does not record which harnesses, sandboxes and CLI versions it '
            'ran; rerun scripts/release/check_policy_env.py: ' + str(root)
        )
    if wanted is not None and wanted not in receipt['checked']:
        raise ValueError(
            'scripts/release/check_policy_env.py has not checked %s on this build (it checked %s); rerun it '
            'with this harness, sandbox and CLI: %s'
            % (
                json.dumps(wanted, sort_keys=True),
                ', '.join(json.dumps(item, sort_keys=True) for item in receipt['checked']),
                root,
            )
        )


def require_combination(harness, isolation):
    """Before preparing runs with an environment: refuse an harness combination its check did not run."""
    root = selected()
    if root is not None:
        require_checked(root, load(root), combination(harness, isolation))


def require_private_route(config):
    """Refuse a Mac route's state under /tmp for a run with an environment, where policies can reach it."""
    slurm = config.get('slurm', {})
    if selected() is None or slurm.get('egress_mode', 'direct') != 'mac-ssh':
        return
    if Path(slurm['egress_root']).resolve().is_relative_to(Path('/tmp').resolve()):
        raise ValueError('Keep slurm.egress_root outside /tmp, which policies can read and write')


OFF = ('off', 'none', '0', 'false', 'no')
# Where scripts/release/build_policy_env.py builds by default on macOS: outside every home folder.
# Elsewhere ROBOTEAM_POLICY_ENV_BASE names the base (for example on Slurm shared storage).
DEFAULT_BASE = Path('/Users/Shared/roboteam')
# The interpreter the environment is built on, and the locked package sets in policy-env/, beside this file.
PYTHON = 'cpython-3.12.16'
CONFIG = Path(__file__).resolve().with_name('policy-env')


# The ordinary environment (None) holds no physics simulator. A named variant adds the
# locked packages of its file to the preinstalled ones; only the runs it is meant for may
# use it (require_variant). `mujoco` is for ground_truth runs (runtime/tools/observation_mode.py).
VARIANTS = {None: None, 'mujoco': 'mujoco'}
# System folders a variant's shells search after /usr/bin and /bin. On macOS `import mujoco`
# runs `sysctl`, which lives in /usr/sbin.
VARIANT_PATH = {'mujoco': ('/usr/sbin',)}


def variant_files(variant):
    """The input and lock file names a variant adds; none for the ordinary environment."""
    if variant not in VARIANTS:
        raise ValueError('Unknown policy environment variant: ' + str(variant))
    name = VARIANTS[variant]
    return () if name is None else (name + '.in', name + '.lock')


def identity(variant=None):
    """The environment's folder suffix: its locks, interpreter and platform (and its variant).

    The ordinary environment's value does not depend on any variant's files."""
    import platform
    import sys

    digest = hashlib.sha256()
    for name in ('core.lock', 'all.lock', *variant_files(variant)[1:]):
        digest.update((CONFIG / name).read_bytes())
    digest.update(
        json.dumps(
            [PYTHON, sys.platform, platform.machine(), *([] if variant is None else [variant])]
        ).encode()
    )
    return digest.hexdigest()[:12]


def folder_name(variant=None):
    """The build's folder under its base: policy-env-<id>, or policy-env-<variant>-<id>."""
    return 'policy-env-' + ('' if variant is None else variant + '-') + identity(variant)


def require_variant(root, variant):
    """Refuse an environment built as another variant than the run needs.

    A ground_truth run needs the simulator; every other run must not have one."""
    actual = load(root).get('variant')
    if actual != variant:

        def name(value):
            return 'the ordinary environment' if value is None else 'the %s variant' % value

        raise ValueError(
            'This run needs %s of the policy environment, but %s is %s' % (name(variant), root, name(actual))
        )


BASE_VAR = 'ROBOTEAM_POLICY_ENV_BASE'


def selected():
    """The environment named by the trusted launcher, or None when none is named."""
    value = os.environ.get(ENV_VAR)
    if not value or value.strip().lower() in OFF:
        return None
    root = Path(value)
    if not root.is_absolute():
        raise ValueError(ENV_VAR + ' must be an absolute path')
    return root.resolve()


def default_root(variant=None):
    """The environment `roboteam prepare` uses when ROBOTEAM_POLICY_ENV is unset.

    New runs use the build of the current locks by default: under ROBOTEAM_POLICY_ENV_BASE,
    or on macOS under DEFAULT_BASE. The build must have passed scripts/release/check_policy_env.py
    (require_checked). Preparation refuses when it is missing or unchecked, rather than silently
    falling back to the host's Python. A host without a base (Linux with none named) returns
    None, and preparation then refuses (apply_default)."""
    import sys

    base = os.environ.get(BASE_VAR) or (str(DEFAULT_BASE) if sys.platform == 'darwin' else None)
    if not base:
        return None
    base = Path(base)
    root = base / folder_name(variant)
    hint = (
        ' Build and check it once: .venv/bin/python -m scripts.release.build_policy_env --base %s%s, then '
        '.venv/bin/python -m scripts.release.check_policy_env %s.'
        % (base, '' if variant is None else ' --variant ' + variant, root)
    )
    if not root.is_dir():
        raise ValueError('The default policy environment is not built: ' + str(root) + '.' + hint)
    manifest = verify(root)
    try:
        require_checked(root, manifest)
    except ValueError as error:
        raise ValueError(
            'The default policy environment did not pass its check. ' + str(error) + '.' + hint
        ) from None
    return root.resolve()


def apply_default(variant=None):
    """Name the environment for this process's preparation: the one chosen, or the default.

    Every run on every platform uses a checked policy environment and the closed access
    table; there is no run on the host's Python. `variant` is what the runs need
    (observation_mode.environment_variant): the default is that variant's build, and preparing a
    run refuses a chosen environment of another variant (require_variant)."""
    value = os.environ.get(ENV_VAR)
    if value and value.strip().lower() in OFF:
        raise ValueError(ENV_VAR + '=' + value + ' is not supported: every run uses a policy environment')
    if value:
        return selected()
    root = default_root(variant)
    if root is None:
        raise ValueError(
            'No policy environment: set ' + BASE_VAR + ' to the folder holding the build of this host '
            '(scripts/release/build_policy_env.py --base), or ' + ENV_VAR + ' to the build itself'
        )
    os.environ[ENV_VAR] = str(root)
    return root


def variables(root, run):
    """What a policy shell receives, in place of the host's environment."""
    root = Path(root).resolve()
    workspace = Path(run).resolve() / 'workspace'
    temporary = workspace / TEMPORARY
    manifest = load(root)
    return {
        'PATH': ':'.join(
            [str(root / manifest['bin']), '/usr/bin', '/bin', *VARIANT_PATH.get(manifest.get('variant'), ())]
        ),
        'LANG': 'C.UTF-8',
        'HOME': str(temporary / 'home'),
        'TMPDIR': str(temporary),
        'TMP': str(temporary),
        'TEMP': str(temporary),
        'XDG_CACHE_HOME': str(temporary / 'cache'),
        'MPLBACKEND': 'Agg',
        'MPLCONFIGDIR': str(temporary / 'matplotlib'),
        'PYTHONUSERBASE': str(workspace / USER_BASE),
        'PIP_USER': '1',
        'PIP_NO_INDEX': '1',
        'PIP_FIND_LINKS': str(root / 'wheels'),
        'PIP_CONFIG_FILE': '/dev/null',
        'PIP_NO_CACHE_DIR': '1',
        'PIP_DISABLE_PIP_VERSION_CHECK': '1',
    }


def shell_text(values):
    """The same variables as a shell file, for a host that sources one before each command.

    Clears the rest of the shell's environment first, so a policy shell sees neither the
    host's settings nor a CLI's credentials. Only what a shell itself maintains stays.
    """
    return (
        "for name in $(/usr/bin/env | /usr/bin/sed -n 's/^\\([A-Za-z_][A-Za-z0-9_]*\\)=.*/\\1/p'); do\n"
        '  case "$name" in PWD|OLDPWD|SHLVL|_) ;; *) unset "$name" 2>/dev/null ;; esac\n'
        'done\n' + ''.join('export %s=%s\n' % (name, shlex.quote(value)) for name, value in values.items())
    )


def guide_text(root):
    """What the policy is told about its Python, the same for every harness."""
    manifest = load(root)
    core = ', '.join('%s %s' % (name, manifest['packages'][name]) for name in manifest['core'])
    store = ', '.join(manifest['store'])
    return (
        '# Python environment\n\n'
        'Your shell provides `python` and `pip`: Python %s with %s.\n\n'
        'These can also be installed, with no network, by `pip install NAME` from a local package store: %s. '
        'Installed packages stay in this run. No other third-party packages are available, and the network is off.\n\n'
        'Keep temporary files in `workspace/%s`, which the shell already uses as TMPDIR. Outside this run\'s '
        '`public/` and `workspace/` folders your scripts can read only the operating system, this Python '
        'environment and `/tmp`, which other runs share.\n\n'
        'The folder above `workspace/` is closed, so `Operation not permitted` on it is expected. `workspace/%s` '
        'belongs to the shell and tools; you do not need to inspect it.\n'
        % (manifest['python'], core, store, TEMPORARY, TEMPORARY)
    )


def prepare_run(run, root):
    """Create the run's own folders and frozen public files; returns the variables."""
    run = Path(run).resolve()
    values = variables(root, run)
    for name in ('HOME', 'TMPDIR', 'XDG_CACHE_HOME', 'MPLCONFIGDIR'):
        Path(values[name]).mkdir(parents=True, exist_ok=True)
    public = run / 'public/inputs'
    (public / SHELL_FILE).write_text(shell_text(values))
    (public / GUIDE_FILE).write_text(guide_text(root))
    return values
