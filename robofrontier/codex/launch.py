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

from robofrontier.run_setup import write_json
from robofrontier.task_families import ROOT, read


def profile(name, config=None):
    catalog = read(config or ROOT/'configs/models.json')
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
        if url.scheme != 'https' or url.username or url.password or url.query:
            raise ValueError('Use an HTTPS base URL without embedded credentials')
    return p


POLICY_PROFILE = 'robofrontier'


def hidden_skills(home=None, repo=ROOT):
    """Skill files Codex would list natively that a policy must not get.

    Personal skills (~/.agents/skills) and any developer skills in the repo's
    .agents/skills stay out of trials; policy Skills reach each run as frozen
    inputs. Codex's bundled system skills stay. Codex disables skills per file.
    """
    home = Path(home) if home else Path.home()
    return sorted(str(f.resolve()) for root in (home/'.agents/skills', Path(repo)/'.agents/skills')
                  for f in root.glob('*/SKILL.md'))


BENCHMARK_CODEX_HOME = Path.home()/'.robofrontier/codex-home'


def codex_home(env=None):
    """CODEX_HOME if set, else the shared benchmark home; never the user's ~/.codex.

    Keeps personal configuration, MCP servers, apps and sessions out of trials. Log
    in once with `CODEX_HOME=~/.robofrontier/codex-home codex login`.
    """
    environment = os.environ if env is None else env
    return Path(environment.get('CODEX_HOME') or BENCHMARK_CODEX_HOME).expanduser().resolve()


def launch_config(p, folder, run_dir=None):
    args = []
    # Account apps and goals are personal Codex features, not task tools, and no
    # AGENTS.md is injected, as on the Claude route.
    values = {'model':p['model'], 'model_provider':p['provider'],
              'model_reasoning_effort':p['effort'], 'model_context_window':p['context_window'],
              'model_auto_compact_token_limit':p['auto_compact_token_limit'],
              'web_search':'disabled', 'features.multi_agent':False,
              'features.apps':False, 'features.goals':False, 'project_doc_max_bytes':0}
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
    # Local Codex model catalog teaches the CLI that this exact model accepts
    # images. No global provider/auth/default settings are modified.
    cache_path=codex_home()/'models_cache.json'
    cached = read(cache_path).get('models', []) if p.get('use_cached_model_metadata',True) and cache_path.is_file() else []
    # Preserve exact OpenAI model metadata if available; the checked-in generic
    # template also permits an empty CODEX_HOME on a new server.
    model=deepcopy(next((m for m in cached if m.get('slug')==p['model']),
                        read(ROOT/'configs/codex-model-template.json')))
    model.update(slug=p['model'], display_name=p['model'], description='Benchmark provider model',
        context_window=p['context_window'],max_context_window=p['context_window'],
        input_modalities=['text','image'],tool_mode=None,shell_type='shell_command',
        use_responses_lite=False,supports_search_tool=False,apply_patch_tool_type='freeform',
        experimental_supported_tools=[],node_repl_disabled=True,
        default_reasoning_level=p['effort'],supported_reasoning_levels=[{'effort':p['effort'],'description':'Declared benchmark effort'}])
    model['model_messages']=None
    # Replaces Codex's own instructions. The catalog stays the same for every run, since the
    # model preflight receipt pins its hash; each thread receives the run's frozen system
    # prompt (role statement and rules) as baseInstructions (codex_policy_host.js).
    from robofrontier.policy_bootstrap import SYSTEM_PROMPT
    model['base_instructions']=SYSTEM_PROMPT
    model['availability_nux']=None
    model['service_tiers']=[];model['additional_speed_tiers']=[]
    model['available_access_programs']=None
    target=folder/'models.json';write_json(target,{'models':[model]})
    values['model_catalog_json']=str(target)
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
    return dict(model=p['model'],provider=p['provider'],effort=p['effort'],args=args,
                profile=p,context_window=p['context_window'],auto_compact_token_limit=p['auto_compact_token_limit'])


def initialize_codex_home(launch, folder, timeout_s=90, *, env=None):
    """Serialize the real app-server handshake for processes sharing CODEX_HOME."""
    home=codex_home(env)
    home.mkdir(parents=True, exist_ok=True)
    deadline=time.monotonic()+timeout_s
    with (home/'robofrontier-init.lock').open('a+') as lock:
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
            subprocess.run(['node',str(ROOT/'robofrontier/codex/codex_initialize.js'),*launch['args']],
                           cwd=ROOT,stdout=log,stderr=log,check=True,timeout=remaining,env=env)
