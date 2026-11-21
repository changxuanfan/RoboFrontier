"""The program versions every run uses; a different one changes behavior, so it is refused.

The harness CLIs are pinned, and so are the simulation libraries (the same versions as
uv.lock). `roboteam prepare` records them in the batch and refuses a mismatch, and
`roboteam run` checks again before it starts. Claude Code's self-update is turned off
for runs (DISABLE_AUTOUPDATER); Codex never updates itself while running.
"""

import importlib.metadata
import re
import subprocess

HARNESSES = {'claude': '2.1.316', 'codex': '0.165.0'}
LIBRARIES = {'mujoco': '3.16.0', 'numpy': '2.5.4', 'pillow': '12.3.0'}
HARNESS_COMMANDS = {'claude': ['claude', '--version'], 'codex': ['codex', '--version']}
NPM_PACKAGES = {'claude': '@anthropic-ai/claude-code', 'codex': '@openai/codex'}
HARNESS_ENVIRONMENT = {'claude': {'DISABLE_AUTOUPDATER': '1'}, 'codex': {}}


def harness_version(harness, run=subprocess.run):
    """The installed harness CLI's version, or None when it cannot be read."""
    try:
        out = run(HARNESS_COMMANDS[harness], capture_output=True, text=True, timeout=60).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.search(r'\d+\.\d+\.\d+', out or '')
    return found.group(0) if found else None


def installed(harness, run=subprocess.run):
    versions = {harness: harness_version(harness, run)}
    for name in LIBRARIES:
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = None
    return versions


def require(harness, run=subprocess.run):
    """The pinned versions, after checking that this host has exactly them."""
    expected = {harness: HARNESSES[harness], **LIBRARIES}
    actual = installed(harness, run)
    wrong = {
        name: {'pinned': expected[name], 'installed': actual[name]}
        for name in expected
        if actual[name] != expected[name]
    }
    if wrong:
        hints = []
        if harness in wrong:
            hints.append(f'npm install --global {NPM_PACKAGES[harness]}@{expected[harness]}')
        if set(wrong) - {harness}:
            hints.append('uv sync --locked')
        raise ValueError(
            'Installed versions differ from the pinned ones: '
            + ', '.join(f"{name} {v['installed']} (pinned {v['pinned']})" for name, v in wrong.items())
            + '. To get the pinned ones: '
            + '; '.join(hints)
        )
    return expected
