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
from pathlib import Path
import subprocess

from . import run_layout
from .task_config import ROOT

NETWORK = False
WEB_SEARCH = False
HOME_SECRETS = ('.codex', '.claude', '.ssh', '.robofrontier', '.config/claude')


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
    for tmp in (tmp_dirs if tmp_dirs is not None else ('/tmp', os.environ.get('TMPDIR'))):
        if tmp: access[str(Path(tmp).resolve())] = 'write'
    access[str(run)] = 'read'
    access[str(run/'private')] = 'deny'
    # Prepared runs use the current layout, whose working folder is workspace/.
    access[str(run/run_layout.LAYOUTS[run_layout.CURRENT]['policy_cwd'])] = 'write'
    return access


def record(run, **kwargs):
    """What a prepared run freezes: the table, network and web search choices."""
    return {'schema': 'robofrontier.policy-access.v1', 'filesystem': table(run, **kwargs),
            'network': NETWORK, 'web_search': WEB_SEARCH}


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
