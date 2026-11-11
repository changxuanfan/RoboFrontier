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
import re
import json
from pathlib import Path
import subprocess
import sys

from . import policy_env, layout as run_layout
from ..tasks.config import ROOT

NETWORK = False
WEB_SEARCH = False
HOME_SECRETS = ('.codex', '.claude', '.ssh', '.robofrontier', '.config/claude')
# Closed for a run with a policy environment: people's files, removable disks, other temporary
# folders, other Python installations, the system keychain files, and a RunPod pod's /workspace
# volume, which holds other runs and data (the run's own public/ and workspace/ open below it). /tmp stays open, since
# shells and tools write there at fixed paths.
CLOSED_ROOTS = {'darwin': ('/Users', '/Volumes', '/var/tmp', '/var/folders', '/opt', '/usr/local', '/Library/Keychains'),
                'linux': ('/home', '/root', '/mnt', '/media', '/raid', '/var/tmp', '/dev/shm', '/opt', '/usr/local',
                          '/workspace')}


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
    system = system or sys.platform
    if system == 'linux':
        require_outside_tmp(run)
    home = Path(home).expanduser().resolve() if home else Path.home().resolve()
    access = table(run, home=home, **{**kwargs, 'tmp_dirs': ('/tmp',)})
    for path in CLOSED_ROOTS[system]:
        access[str(Path(path).resolve())] = 'deny'
    access[str(home)] = 'deny'
    # On macOS a run may sit in scratch under /tmp, beside the rest of its batch; Linux refuses it above.
    for folder in (run.parent, run.parent.parent):
        if folder not in (Path('/'), Path('/tmp').resolve()):
            access[str(folder)] = 'deny'
    if system == 'linux':
        # The system's own Python and pip live in the open /usr/bin: closed one by one, so a
        # policy shell runs only the environment's Python, as on macOS where /opt and
        # /usr/local hold the others.
        for path in system_pythons():
            access[path] = 'deny'
    access[str(Path(environment).resolve())] = 'read'
    access[str(run)] = 'deny'
    access[str(run/'public')] = 'read'
    access[str(run/'private')] = 'deny'
    access[str(run/run_layout.LAYOUTS[run_layout.CURRENT]['policy_cwd'])] = 'write'
    return access


SYSTEM_PYTHON = re.compile(r'(python|pip)[0-9.]*(-config)?')


def system_pythons(folders=('/usr/bin', '/bin', '/usr/sbin')):
    """The Python interpreters and pip commands a Linux system keeps in its open folders."""
    found = set()
    for folder in folders:
        folder = Path(folder)
        if folder.is_symlink() or not folder.is_dir(): continue
        for entry in folder.iterdir():
            if SYSTEM_PYTHON.fullmatch(entry.name): found.add(str(entry))
    return sorted(found)


def require_outside_tmp(run):
    """On Linux, refuse a run with a policy environment, or a TMPDIR, inside /tmp.

    Landlock cannot open a folder and close something inside it: the folder itself gets no rule.
    A closed run, batch or TMPDIR inside /tmp would leave /tmp unwritable, where shells and the
    CLIs create files at fixed paths. TMPDIR=/tmp itself stays open.
    """
    tmp = Path('/tmp').resolve()
    temporary = Path(os.environ['TMPDIR']).resolve() if os.environ.get('TMPDIR') else None
    for name, path in (('the run folder', run), ('TMPDIR', temporary)):
        if path is not None and path != tmp and path.is_relative_to(tmp):
            raise ValueError('On Linux, keep %s outside /tmp for a run with a policy environment (set '
                             'slurm.scratch_root and TMPDIR under /var/tmp, for example); found %s' % (name, path))


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
