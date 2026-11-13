"""Keep native credentials usable without inheriting personal customizations."""
import fcntl
import json
import os
from pathlib import Path
import sys

from robofrontier.runtime.setup import write_json
from .profile import require_clean_home

HOME_CONFIG = {'plugins': {'swarm': {'enabled': False}}, 'sidecars': {}, 'userSettings': {}}


def home_directory(run, profile, original=None, system=None):
    if profile['auth_mode'] == 'native_login' and (system or sys.platform) != 'darwin':
        return Path(original or Path.home()).resolve()
    return Path(run).resolve()/'private/engine/home'


def _link(path, source):
    source = source.resolve(strict=True)
    if path.is_symlink():
        if path.resolve() != source:
            raise ValueError('Antigravity keychain bridge changed')
    elif path.exists():
        raise ValueError('Antigravity keychain bridge requires a symlink')
    else:
        path.symlink_to(source, target_is_directory=source.is_dir())


def environment_home(run, profile, original):
    run, original = Path(run).resolve(), Path(original).resolve()
    home = home_directory(run, profile, original)
    if home == original:
        require_clean_home(original)
        return home
    private = run/'private/engine'
    private.mkdir(parents=True, exist_ok=True)
    with (private/'configuration.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if home.is_symlink():
            raise ValueError('Antigravity private home must not be a symlink')
        home.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(home, 0o700)
        config = home/'.gemini/config/config.json'
        if config.is_symlink() or config.exists() and json.loads(config.read_text()) != HOME_CONFIG:
            raise ValueError('Antigravity private-home configuration changed')
        if not config.exists():
            write_json(config, HOME_CONFIG)
        # A fresh native CLI otherwise enables the built-in swarm during legacy
        # configuration migration. All roles use the same explicit empty setup.
        (config.parent/'.migrated').touch(exist_ok=True)
        if profile['auth_mode'] == 'native_login':
            preferences = home/'Library/Preferences'
            preferences.mkdir(parents=True, exist_ok=True)
            _link(home/'Library/Keychains', original/'Library/Keychains')
            names = []
            for source in sorted((original/'Library/Preferences').glob('com.apple.security*.plist')):
                if source.is_file():
                    _link(preferences/source.name, source)
                    names.append(source.name)
            # Only the OS keychain and its lookup preferences are shared. No
            # token extraction, rule/plugin copying or global setting mutation.
            write_json(private/'auth-isolation.json', {'mode': 'macos-keychain-private-home',
                'source_home': str(original), 'linked_security_preferences': names})
    return home
