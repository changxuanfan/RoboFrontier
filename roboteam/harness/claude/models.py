"""The Claude Code models of models.json: one validated entry, and the batch and launch schema names."""

import os
from pathlib import Path
from urllib.parse import urlsplit

from roboteam.harness.claude.session.runner import _oauth_endpoint_allowed
from roboteam.io import ROOT

CATALOG = ROOT / 'models.json'
BATCH_SCHEMA = 'roboteam.claude-batch.v2'
LAUNCH_SCHEMA = 'roboteam.claude-launch.v2'


def model_entry(name, catalog=CATALOG):
    from roboteam.configuration import model_catalog

    document = model_catalog('claude', catalog)
    if document.get('schema') != 'roboteam.claude-models.v1':
        raise ValueError('Unsupported Claude model catalog')
    try:
        selected = dict(document['models'][name])
    except KeyError as exc:
        raise ValueError('Unknown Claude model: ' + name) from exc
    if not all(isinstance(selected.get(k), str) and selected[k] for k in ('provider', 'model', 'effort')):
        raise ValueError('Incomplete model')
    if selected['effort'] not in ('low', 'medium', 'high', 'xhigh', 'max'):
        raise ValueError('Unsupported Claude effort')
    auth_mode = selected.get('auth_mode', 'api_key')
    if auth_mode not in ('api_key', 'oauth_token', 'native_login'):
        raise ValueError('Unsupported Claude authentication mode')
    if auth_mode == 'native_login':
        if selected.get('native_config_scope', 'directory') not in ('default', 'directory'):
            raise ValueError('Unknown native configuration scope')
        if selected['provider'] != 'anthropic' or selected.get('env_key'):
            raise ValueError('Native login requires Anthropic and no credential environment variable')
        name = selected.get('native_config_dir_env')
        if not isinstance(name, str) or not name.isidentifier():
            raise ValueError('Native login requires an explicit configuration-directory environment variable')
        value = os.environ.get(name)
        selected['native_config_dir'] = (
            str(Path(value).resolve()) if value and Path(value).is_absolute() else value
        )
    elif not isinstance(selected.get('env_key'), str) or not selected['env_key']:
        raise ValueError('Incomplete model')
    if auth_mode == 'oauth_token' and (
        selected['provider'] != 'anthropic' or selected['env_key'] != 'CLAUDE_CODE_OAUTH_TOKEN'
    ):
        raise ValueError('OAuth token mode is limited to the Anthropic subscription model')
    base = selected.get('base_url')
    if 'base_url_env' in selected:
        base = os.environ.get(selected['base_url_env'])
    if base:
        url = urlsplit(base)
        local_plan_gateway = (
            selected['provider'] == 'openai_chatgpt_plan'
            and url.scheme == 'http'
            and url.hostname in ('127.0.0.1', '::1')
        )
        if (
            (url.scheme != 'https' and not local_plan_gateway)
            or not url.hostname
            or url.username
            or url.password
            or url.query
            or url.fragment
        ):
            raise ValueError('Base URL must be HTTPS without credentials, query or fragment')
    if auth_mode in ('oauth_token', 'native_login') and not _oauth_endpoint_allowed(base):
        raise ValueError('OAuth token may only be sent to the Anthropic endpoint')
    selected['base_url'] = base
    return selected
