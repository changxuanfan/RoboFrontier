"""Non-secret launch profiles; authentication belongs to the trusted host."""
import hashlib
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

from robofrontier.engines.common.identity import fingerprint

VERSION = '1.5.5'
AUTH_MODES = ('native_login', 'api_key')


def validate(value):
    value = dict(value)
    if any(not isinstance(value.get(k), str) or not value[k] for k in ('model', 'effort', 'auth_mode')):
        raise ValueError('Incomplete Antigravity profile')
    if value['effort'] not in ('low', 'medium', 'high', 'xhigh', 'max') or value['auth_mode'] not in AUTH_MODES:
        raise ValueError('Unsupported Antigravity effort or authentication mode')
    if value['auth_mode'] == 'native_login':
        if value.get('env_key') or value.get('base_url') or value.get('base_url_env'):
            raise ValueError('Subscription login cannot be combined with an API endpoint or key')
    else:
        if not isinstance(value.get('env_key'), str) or not value['env_key'].isidentifier():
            raise ValueError('An API profile names a credential variable, never a credential')
        url = urlsplit(value.get('base_url', 'https://generativelanguage.googleapis.com'))
        if url.scheme != 'https' or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError('Gemini-compatible service URL must be HTTPS without credentials, query or fragment')
        value['base_url'] = url.geturl().rstrip('/')
    return value


def profile(name, catalog=None):
    from robofrontier.configuration import model_catalog
    entry = dict(model_catalog('antigravity', catalog)['profiles'][name])
    if entry.get('base_url_env'):
        entry['base_url'] = os.environ.get(entry['base_url_env'], '')
        if not entry['base_url']:
            raise ValueError('Missing endpoint variable: ' + entry['base_url_env'])
    return validate(entry)


def require_clean_home(home):
    """Refuse ambient instructions/extensions rather than modifying a user's account."""
    home = Path(home)
    candidates = [home/'.gemini/GEMINI.md', home/'.gemini/config', home/'.agents',
                  home/'.gemini/antigravity-cli/settings.json']
    dirty = []
    for path in candidates:
        if not path.exists():
            continue
        if path.is_dir():
            if any(p.is_file() for p in path.rglob('*')):
                dirty.append(str(path))
        elif path.name == 'settings.json':
            saved = json.loads(path.read_text())
            if set(saved) - {'useG1Credits', 'showTips', 'showFeedbackSurvey', 'altScreenMode'}:
                dirty.append(str(path))
        elif path.read_text().strip():
            dirty.append(str(path))
    if dirty:
        raise ValueError('Antigravity would load ambient instructions/settings: ' + ', '.join(dirty))
