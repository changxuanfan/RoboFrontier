"""Codex CLI launch configuration, native home and app-server initialization."""
from copy import deepcopy
import fcntl
import json
import os
from pathlib import Path
import re
import subprocess
import time
import tomllib

from roboteam.runtime.setup import write_json
from roboteam.tasks.families import ROOT, read


def profile(name, config=None):
    from ...configuration import model_catalog
    catalog = model_catalog('codex', config)
    p = deepcopy(catalog['profiles'][name])
    p.update(context_window=catalog['context_window'], auto_compact_token_limit=catalog['auto_compact_token_limit'])
    if not p['vision']:
        raise ValueError('This benchmark requires native images; text-only models need a separately declared experiment')
    if not 0 < p['auto_compact_token_limit'] < p['context_window'] <= p['context_capacity']:
        raise ValueError('Requested context exceeds the declared model capacity')
    if 'base_url_env' in p:
        p['base_url'] = os.environ.get(p['base_url_env'])
        if not p['base_url']:
            raise ValueError('Set '+p['base_url_env']+' to the official workspace/region Responses base URL')
    if p['provider'] != 'openai':
        from urllib.parse import urlsplit
        url = urlsplit(p['base_url'])
        if loopback_gateway(p):
            # Plain HTTP only for a profile that declares a local protocol adapter, and only to
            # the literal loopback address: the key it sends is that adapter's local key.
            if (url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or url.username or url.password
                    or url.query or url.fragment or not p.get('env_key') or 'base_url_env' in p
                    or not p.get('transport_revision') or p.get('http_headers')):
                raise ValueError('A loopback gateway profile needs http://127.0.0.1:PORT, a local key variable '
                                 'and a transport revision')
        elif 'transport' in p:
            raise ValueError('Unknown model transport: '+str(p['transport']))
        elif url.scheme != 'https' or url.username or url.password or url.query:
            raise ValueError('Use an HTTPS base URL without embedded credentials')
    elif 'transport' in p:
        raise ValueError('A native OpenAI profile has no separate model transport')
    return p


LOOPBACK_GATEWAY = 'loopback_gateway'
# Upstream credentials a loopback adapter owns. The Codex process and its shells get the
# adapter's local key only, never these.
GATEWAY_UPSTREAM_SECRETS = ('ANTHROPIC_API_KEY', 'ANTHROPIC_AUTH_TOKEN')


def loopback_gateway(p):
    """Whether a profile explicitly routes its model through a local protocol adapter."""
    return p.get('transport') == LOOPBACK_GATEWAY


def gateway_environment(p, env):
    """The environment for Codex: a loopback gateway profile never passes upstream credentials."""
    if loopback_gateway(p):
        for name in GATEWAY_UPSTREAM_SECRETS:
            env.pop(name, None)
    return env


def require_gateway(p, timeout_s=5):
    """Refuse to start unless the profile's own adapter, at its frozen revision, is listening.

    A local check with no credential and no model call. It keeps the local key from being sent
    to some other process on that port, and a changed adapter from reusing an old receipt.
    """
    if not loopback_gateway(p):
        return
    from urllib.parse import urlsplit
    from urllib.request import ProxyHandler, build_opener
    url = urlsplit(p['base_url'])
    try:
        # No proxy: the address is this machine's loopback interface.
        with build_opener(ProxyHandler({})).open('http://127.0.0.1:%d/healthz' % url.port, timeout=timeout_s) as response:
            health = json.loads(response.read(65536))
    except (OSError, ValueError) as error:
        raise ValueError('The model gateway for this profile is not listening on 127.0.0.1:%d; start it first (%s)'
                         % (url.port, type(error).__name__)) from None
    if not isinstance(health, dict) or health.get('model') != p['model'] \
            or health.get('transport_revision') != p['transport_revision']:
        raise ValueError('The listener on 127.0.0.1:%d is not this profile\'s gateway (model or transport revision '
                         'differs)' % url.port)


POLICY_PROFILE = 'roboteam'


def hidden_skills(home=None, repo=ROOT):
    """Skill files Codex would list natively that a policy must not get.

    Personal skills (~/.agents/skills) and any developer skills in the repo's
    .agents/skills stay out of trials; policy Skills reach each run as frozen
    inputs. Codex's bundled system skills stay. Codex disables skills per file.
    """
    home = Path(home) if home else Path.home()
    return sorted(str(f.resolve()) for root in (home/'.agents/skills', Path(repo)/'.agents/skills')
                  for f in root.glob('*/SKILL.md'))


BENCHMARK_CODEX_HOME = Path.home()/'.roboteam/codex-home'


def codex_home(env=None):
    """CODEX_HOME if set, else the shared benchmark home; never the user's ~/.codex.

    Keeps personal configuration, MCP servers, apps and sessions out of trials. Log
    in once with `CODEX_HOME=~/.roboteam/codex-home codex login`.
    """
    environment = os.environ if env is None else env
    return Path(environment.get('CODEX_HOME') or BENCHMARK_CODEX_HOME).expanduser().resolve()


def launch_config(p, folder, run_dir=None):
    from .tool_backend import selected, fingerprint
    backend = selected(p)
    # A robot_only role keeps the robot tool alone (runtime/tool_mode.py): Codex's own tools
    # are switched off exactly as for the tool worker, and no file tools replace them.
    from roboteam.runtime import tool_mode
    robot_only = tool_mode.of(p) == tool_mode.ROBOT_ONLY
    if robot_only and backend != 'native':
        raise ValueError('A robot_only run has no file tools to confine: use the native tool backend')
    provider = p['provider']
    args = []
    # Account apps and goals are personal Codex features, not task tools, and no
    # AGENTS.md is injected, as on the Claude route.
    values = {'model':p['model'], 'model_provider':p['provider'],
              'model_reasoning_effort':p['effort'], 'model_context_window':p['context_window'],
              'model_auto_compact_token_limit':p['auto_compact_token_limit'],
              'web_search':'disabled', 'features.multi_agent':False,
              'features.apps':False, 'features.goals':False, 'project_doc_max_bytes':0}
    if backend == 'landlock-v1' or robot_only:
        if os.environ.get('ROBOTEAM_EGRESS_INSTANCE') and p.get('runner_backend') == 'slurm-managed-v1':
            values['features.respect_system_proxy'] = True
        for flag in ('shell_tool', 'view_image', 'shell_snapshot', 'unified_exec', 'plugins',
                     'browser_use', 'browser_use_external', 'browser_use_full_cdp_access',
                     'computer_use', 'code_mode', 'code_mode_only', 'code_mode_host', 'multi_agent_v2'):
            values['features.'+flag] = False
        values.update({'agents.enabled': False, 'tools.experimental_request_user_input.enabled': False})
        if p['provider'] == 'openai' and backend == 'landlock-v1':
            values['forced_login_method'] = 'chatgpt'
            # Built-in provider IDs cannot be overridden in CLI 0.165.0. Keep
            # native AuthManager/account refresh, with its normal ChatGPT URL,
            # but select HTTP/SSE without per-role WebSocket 403/retry bursts.
            provider = 'roboteam_openai_http'
            values.update({'model_provider': provider,
                           'model_providers.'+provider+'.name': 'OpenAI',
                           'model_providers.'+provider+'.wire_api': 'responses',
                           'model_providers.'+provider+'.requires_openai_auth': True,
                           'model_providers.'+provider+'.supports_websockets': False})
    if p['provider'] == 'openai':
        # Shared subscription homes retain native auth, but their MCP servers
        # are not benchmark tools. Disable known layers without editing them;
        # the host checks the effective configuration again before inference.
        home = codex_home()
        directory = Path(folder).resolve()
        # The personal ~/.codex is only a configuration layer when it is the active home.
        personal = (Path.home()/'.codex/config.toml').resolve()
        configs = {home/'config.toml', *(parent/'.codex/config.toml'
                    for parent in (directory, *directory.parents)
                    if (parent/'.codex/config.toml').resolve() != personal)}
        overrides = set()
        for config in configs:
            if not config.is_file():
                continue
            document = tomllib.loads(config.read_text())
            overrides.update(('mcp_servers', name) for name in document.get('mcp_servers', {}))
            for profile_name, layer in document.get('profiles', {}).items():
                overrides.update(('profiles.'+profile_name+'.mcp_servers', name)
                                 for name in layer.get('mcp_servers', {}))
        for prefix, name in sorted(overrides):
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not re.fullmatch(r'[A-Za-z0-9_.-]+', prefix):
                raise ValueError('Use a separate native home for MCP names that cannot be safely overridden')
            values[prefix+'.'+name+'.enabled'] = False
    if p['provider'] != 'openai':
        prefix='model_providers.'+p['provider']+'.'
        values.update({prefix+'name':p['provider'], prefix+'base_url':p['base_url'],
            prefix+'env_key':p['env_key'], prefix+'wire_api':'responses',
            prefix+'requires_openai_auth':False, prefix+'supports_websockets':False,
            prefix+'request_max_retries':3, prefix+'stream_max_retries':3})
        for name, value in p.get('http_headers', {}).items():
            if not re.fullmatch(r'[A-Za-z0-9_-]+', name) or not isinstance(value, str):
                raise ValueError('Provider HTTP headers require simple names and string values')
            if name.lower() in ('authorization', 'proxy-authorization', 'cookie') or '\r' in value or '\n' in value:
                raise ValueError('Keep credentials out of frozen HTTP headers; use env_key')
            values[prefix+'http_headers.'+name] = value
    if loopback_gateway(p):
        # Model shells never inherit the adapter's local key or an upstream credential. Their
        # network is off as well, so the loopback port is out of reach either way.
        values['shell_environment_policy.exclude'] = [p['env_key'], *GATEWAY_UPSTREAM_SECRETS]
    # Local Codex model catalog teaches the CLI that this exact model accepts
    # images. No global provider/auth/default settings are modified.
    cache_path=codex_home()/'models_cache.json'
    cached = read(cache_path).get('models', []) if p.get('use_cached_model_metadata',True) and cache_path.is_file() else []
    # Preserve exact OpenAI model metadata if available; the checked-in generic
    # template also permits an empty CODEX_HOME on a new server.
    model=deepcopy(next((m for m in cached if m.get('slug')==p['model']),
                        read(Path(__file__).with_name('model_template.json'))))
    model.update(slug=p['model'], display_name=p['model'], description='Benchmark provider model',
        context_window=p['context_window'],max_context_window=p['context_window'],
        input_modalities=['text','image'],tool_mode=None,shell_type='shell_command',
        use_responses_lite=False,supports_search_tool=False,apply_patch_tool_type='freeform',
        experimental_supported_tools=[],node_repl_disabled=True,
        default_reasoning_level=p['effort'],supported_reasoning_levels=[{'effort':p['effort'],'description':'Declared benchmark effort'}])
    model['model_messages']=None
    if loopback_gateway(p):
        # Output verbosity is an OpenAI-only request control that the adapter cannot translate
        # and would reject; the model's own default applies.
        model.update(support_verbosity=False, default_verbosity=None)
    # Replaces Codex's own instructions. The catalog stays the same for every run, since the
    # model preflight receipt pins its hash; each thread receives the run's frozen system
    # prompt (role statement and rules) as baseInstructions (codex_policy_host.js).
    from roboteam.runtime.bootstrap import SYSTEM_PROMPT
    model['base_instructions']=SYSTEM_PROMPT
    model['availability_nux']=None
    model['service_tiers']=[];model['additional_speed_tiers']=[]
    model['available_access_programs']=None
    if backend == 'landlock-v1' or robot_only:
        model.update(apply_patch_tool_type=None, multi_agent_version='disabled')
    target=folder/'models.json';write_json(target,{'models':[model]})
    values['model_catalog_json']=str(target.resolve())
    for key,value in values.items():
        # JSON scalar/array strings are also valid TOML values; argv, never shell.
        args.extend(['-c',key+'='+json.dumps(value)])
    skills=','.join('{path='+json.dumps(f)+',enabled=false}' for f in hidden_skills())
    args.extend(['-c','skills.config=['+skills+']'])
    access=Path(run_dir)/'private/inputs/policy-access.json' if run_dir is not None else None
    if access is not None and access.is_file():
        # The run's frozen access table as a named permission profile. A thread/start
        # `sandbox` parameter would replace it, so the host sends none for these runs.
        frozen=read(access)
        table=','.join(json.dumps(path)+'='+json.dumps(mode) for path,mode in frozen['filesystem'].items())
        args.extend(['-c','default_permissions='+json.dumps(POLICY_PROFILE),
                     '-c','permissions.'+POLICY_PROFILE+'.filesystem={'+table+'}',
                     '-c','permissions.'+POLICY_PROFILE+'.network.enabled='+json.dumps(bool(frozen['network']))])
        if frozen.get('policy_env'):
            # Shells get only the frozen variables. A login shell would reorder PATH.
            args.extend(['-c','allow_login_shell=false','-c','shell_environment_policy.inherit="none"'])
            for name,value in frozen['policy_env']['variables'].items():
                args.extend(['-c','shell_environment_policy.set.'+name+'='+json.dumps(value)])
    return dict(model=p['model'],provider=provider,effort=p['effort'],args=args,
                profile=p,context_window=p['context_window'],auto_compact_token_limit=p['auto_compact_token_limit'],
                tool_backend=backend,tool_backend_sha256=fingerprint(p),model_catalog=str(target.resolve()),
                **({'tool_mode': tool_mode.ROBOT_ONLY} if robot_only else {}))


def initialize_codex_home(launch, folder, timeout_s=90, *, env=None):
    """Serialize the real app-server handshake for processes sharing CODEX_HOME."""
    home=codex_home(env)
    home.mkdir(parents=True, exist_ok=True)
    deadline=time.monotonic()+timeout_s
    with (home/'roboteam-init.lock').open('a+') as lock:
        while True:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic()>=deadline:
                    raise TimeoutError('Timed out waiting for CODEX_HOME initialization lock')
                time.sleep(.1)
        remaining=deadline-time.monotonic()
        if remaining<=0:raise TimeoutError('Timed out before Codex initialization')
        with (folder/'codex-initialize.log').open('a') as log:
            subprocess.run(['node',str(ROOT/'roboteam/engines/codex/codex_initialize.js'),*launch['args']],
                           cwd=ROOT,stdout=log,stderr=log,check=True,timeout=remaining,env=env)
