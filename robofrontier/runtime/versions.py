"""The program versions every run uses; a different one changes behavior, so it is refused.

The engine CLIs are pinned, and so are the simulation libraries (the same versions as
uv.lock). `robofrontier prepare` records them in the batch and refuses a mismatch, and
`robofrontier run` checks again before it starts. Claude Code's self-update is turned off
for runs (DISABLE_AUTOUPDATER); Codex never updates itself while running.
"""
import importlib.metadata
import re
import subprocess

ENGINES = {'claude': '2.1.316', 'codex': '0.165.0'}
LIBRARIES = {'mujoco': '3.16.0', 'numpy': '2.5.4', 'pillow': '12.3.0'}
ENGINE_COMMANDS = {'claude': ['claude', '--version'], 'codex': ['codex', '--version']}
ENGINE_ENVIRONMENT = {'claude': {'DISABLE_AUTOUPDATER': '1'}, 'codex': {}}


def engine_version(engine, run=subprocess.run):
    """The installed engine CLI's version, or None when it cannot be read."""
    try: out = run(ENGINE_COMMANDS[engine], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError): return None
    found = re.search(r'\d+\.\d+\.\d+', out or '')
    return found.group(0) if found else None


def installed(engine, run=subprocess.run):
    versions = {engine: engine_version(engine, run)}
    for name in LIBRARIES:
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = None
    return versions


def require(engine, run=subprocess.run):
    """The pinned versions, after checking that this host has exactly them."""
    expected = {engine: ENGINES[engine], **LIBRARIES}
    actual = installed(engine, run)
    wrong = {name: {'pinned': expected[name], 'installed': actual[name]} for name in expected if actual[name] != expected[name]}
    if wrong:
        raise ValueError('Installed versions differ from the pinned ones: '+', '.join(
            f"{name} {v['installed']} (pinned {v['pinned']})" for name, v in wrong.items()))
    return expected
