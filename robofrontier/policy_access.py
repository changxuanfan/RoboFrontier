"""What a policy may read and write on the host, the same for both engines.

One table, frozen when a run is prepared, maps absolute paths to `read`,
`write` or `deny`; the more specific path wins. Each engine renders it in its
own sandbox: Codex as a named permission profile, Claude Code as settings
permissions plus its Bash sandbox. The policy may write only its working folder
(workspace/) and temporary folders, may read its run's public inputs and the
rest of the machine, and may not read the repository (source, configuration,
other runs, answers), any checkout of it, its own run's private/ folder or any
engine's credentials. Shell network access and web search are off for both
engines: the repository is public, so the network could reach reference
solutions, and results would depend on what the web returned that day.
"""
import os
import json
from pathlib import Path
import subprocess
import sys

from . import policy_env, run_layout
from .task_config import ROOT

NETWORK = False
WEB_SEARCH = False
HOME_SECRETS = ('.codex', '.claude', '.ssh', '.robofrontier', '.config/claude')
# Closed for a run with a policy environment: people's files, removable disks, other temporary
# folders, other Python installations, and the system keychain files. /tmp stays open, since
# shells and tools write there at fixed paths.
CLOSED_ROOTS = {'darwin': ('/Users', '/Volumes', '/var/tmp', '/var/folders', '/opt', '/usr/local', '/Library/Keychains'),
                'linux': ('/home', '/root', '/mnt', '/media', '/raid', '/var/tmp', '/dev/shm', '/opt', '/usr/local')}


def _checkouts(repo):
    """Every checkout of this repository: the main one and its git worktrees."""
    try:
        out = subprocess.run(['git', '-C', str(repo), 'worktree', 'list', '--porcelain'], capture_output=True,
                             text=True, timeout=30, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return [repo]
    return [Path(line[len('worktree '):]) for line in out.splitlines() if line.startswith('worktree ')] or [repo]


def _auth_homes(home):
    """Credential homes of both engines, wherever this host keeps them."""
    homes = [home/name for name in HOME_SECRETS]
    for key in ('CODEX_HOME', 'CLAUDE_CONFIG_DIR', 'ROBOFRONTIER_CLAUDE_HOME', 'ROBOFRONTIER_CODEX_HOME',
                'ROBOFRONTIER_JOB_PRIVATE_ROOT', 'ROBOFRONTIER_CREDENTIAL_STORE', 'ROBOFRONTIER_EGRESS_ROOT'):
        if os.environ.get(key):
            homes.append(Path(os.environ[key]).expanduser())
    return homes


def table(run, repo=ROOT, home=None, tmp_dirs=None, checkouts=None):
    run = Path(run).resolve()
    home = Path(home).expanduser().resolve() if home else Path.home().resolve()
    access = {'/': 'read'}
    for checkout in (checkouts if checkouts is not None else _checkouts(Path(repo))):
        access[str(Path(checkout).resolve())] = 'deny'
    for path in _auth_homes(home):
        access[str(Path(path).resolve())] = 'deny'
    # Shared Slurm storage can contain independent clones and source archives
    # that git worktree discovery cannot enumerate. The trusted launcher names
    # these roots; the resulting concrete table is frozen and hashed per run.
    roots = json.loads(os.environ.get('ROBOFRONTIER_SHARED_DENY_ROOTS', '[]'))
    if not isinstance(roots, list) or any(not isinstance(p, str) or not Path(p).is_absolute() or p == '/' for p in roots):
        raise ValueError('Shared deny roots must be absolute operator-storage paths')
    for path in roots:
        access[str(Path(path).resolve())] = 'deny'
    for tmp in (tmp_dirs if tmp_dirs is not None else ('/tmp', os.environ.get('TMPDIR'))):
        if tmp: access[str(Path(tmp).resolve())] = 'write'
    access[str(run)] = 'read'
    access[str(run/'private')] = 'deny'
    # Prepared runs use the current layout, whose working folder is workspace/.
    access[str(run/run_layout.LAYOUTS[run_layout.CURRENT]['policy_cwd'])] = 'write'
    return access


def closed_table(run, environment, *, home=None, system=None, **kwargs):
    """The table of a run with a policy environment: personal, shared and other software closed.

    The root stays readable because a process cannot start on macOS without it (a table
    without it aborts even /bin/sh), so this closes what holds other people's data, other
    runs or other software rather than listing what stays open. Only this run's public/
    and workspace/ folders and the environment are open beneath the closed folders; /tmp
    stays writable and is shared with other runs.
    """
    run = Path(run).resolve()
    home = Path(home).expanduser().resolve() if home else Path.home().resolve()
    access = table(run, home=home, **{**kwargs, 'tmp_dirs': ('/tmp',)})
    for path in CLOSED_ROOTS[system or sys.platform]:
        access[str(Path(path).resolve())] = 'deny'
    access[str(home)] = 'deny'
    # A run may sit in node-local scratch under /tmp, beside the rest of its batch.
    for folder in (run.parent, run.parent.parent):
        if folder not in (Path('/'), Path('/tmp').resolve()):
            access[str(folder)] = 'deny'
    access[str(Path(environment).resolve())] = 'read'
    access[str(run)] = 'deny'
    access[str(run/'public')] = 'read'
    access[str(run/'private')] = 'deny'
    access[str(run/run_layout.LAYOUTS[run_layout.CURRENT]['policy_cwd'])] = 'write'
    return access


def record(run, environment=None, unchecked=False, **kwargs):
    """What a prepared run freezes: the table, network and web search choices."""
    environment = environment or policy_env.selected()
    if environment is None:
        return {'schema': 'robofrontier.policy-access.v1', 'filesystem': table(run, **kwargs),
                'network': NETWORK, 'web_search': WEB_SEARCH}
    manifest = policy_env.verify(environment)
    # scripts/check_policy_env.py is what passes this, so it alone may be `unchecked`.
    if not unchecked:
        policy_env.require_checked(environment, manifest)
    return {'schema': 'robofrontier.policy-access.v2', 'filesystem': closed_table(run, environment, **kwargs),
            'network': NETWORK, 'web_search': WEB_SEARCH,
            'policy_env': {'root': str(Path(environment).resolve()), 'id': manifest['id'], 'python': manifest['python'],
                           'tree_sha256': manifest['tree_sha256'], 'variables': policy_env.variables(environment, run)}}


def mode(access, path):
    """The access a table grants for `path`: its most specific listed ancestor wins."""
    path = Path(path).resolve()
    best = None
    for prefix, value in access.items():
        prefix = Path(prefix)
        if path == prefix or prefix in path.parents:
            if best is None or len(prefix.parts) > len(best[0].parts):
                best = (prefix, value)
    return best[1] if best else 'deny'
