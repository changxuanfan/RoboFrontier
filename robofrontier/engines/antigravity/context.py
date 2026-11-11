"""Pinned native session configuration, verified before policy input.

The CLI has no public flag for these settings. Its local LanguageServerService
accepts an AgentConfig when creating a conversation; that static configuration
survives CLI resume and native forks. Two things are set there:

- the checkpoint (compaction) budget. Never confuse its contextWindow string
  (a model option name) with an integer capacity in tokens;
- the system prompt. By default the CLI sends the agent's text followed by eight
  sections of its own (environment, MCP, skills, rules, messaging, artifacts,
  guidelines, style), about 8,000 characters, and it cuts the agent's text at each
  top-level heading into a block named after the heading. One untitled section
  holding the whole frozen system.md sends that text and nothing else, as Claude
  Code's --system-prompt and Codex's baseInstructions do.
"""
import copy
import hashlib
import json

from robofrontier.configuration import model_catalog
from robofrontier.runtime.setup import write_json


def limits(run):
    path = run/'private/inputs/antigravity.json'
    frozen = json.loads(path.read_text()) if path.is_file() else {}
    defaults = model_catalog('codex')
    capacity = frozen.get('context_window', defaults['context_window'])
    threshold = frozen.get('requested_auto_compact_token_limit', defaults['auto_compact_token_limit'])
    if type(capacity) is not int or type(threshold) is not int or not 0 < threshold < capacity:
        raise ValueError('Invalid Antigravity context limits')
    return capacity, threshold


def with_checkpoint(spec, threshold):
    spec = copy.deepcopy(spec)
    if 'agentConfig' not in spec:
        raise ValueError('Pinned Antigravity agent configuration missing')
    config = spec['agentConfig'].setdefault('cascadeConfig', {}).setdefault('checkpointConfig', {})
    config.update(maxTokenLimit=threshold, useModelReportedTokenCount=True)
    return spec


# User-level customizations the CLI would otherwise look up for the agent.
DISCOVERY = ('skills', 'agents', 'plugins', 'rules', 'hooks')


def system_text(run):
    """The frozen system prompt as the CLI stores it: without the file's final newline."""
    return (run/'private/inputs/bootstrap/system.md').read_text().rstrip('\n')


def policy_spec(spec, threshold, system):
    """The bootstrap session's configuration with this run's budget and only its system prompt."""
    spec = with_checkpoint(spec, threshold)
    agent = spec['agentConfig']
    sections = agent.get('mixinConfig', {}).get('promptSections', [])
    own = [s['custom'].get('content', '').strip() for s in sections if 'custom' in s]
    # The CLI cut the run's agent file into one titled section per top-level heading
    # (`# Policy rules` became a <Policy rules> block). Every piece must come from the
    # frozen prompt; anything else means another agent definition was loaded.
    if not own or any(not piece or piece not in system for piece in own):
        raise ValueError('Native agent does not carry the frozen system prompt')
    agent['mixinConfig']['promptSections'] = [{'custom': {'title': '', 'content': system}}]
    discovery = agent.setdefault('customizationDiscovery', {})
    for name in DISCOVERY:
        discovery.setdefault(name, {})['inheritUser'] = False
    return spec


def prompt_only(spec, system):
    agent = spec.get('agentConfig', {})
    sections = agent.get('mixinConfig', {}).get('promptSections', [])
    discovery = agent.get('customizationDiscovery', {})
    return (len(sections) == 1 and set(sections[0]) == {'custom'}
            and not sections[0]['custom'].get('title') and sections[0]['custom'].get('content') == system
            and not any(discovery.get(name, {}).get('inheritUser') for name in DISCOVERY))


def verify_static(driver):
    spec = driver.rpc('GetConversationMetadata', {'conversationId': driver.session})['metadata']['staticConfig']
    config = spec.get('agentConfig', {}).get('cascadeConfig', {}).get('checkpointConfig', {})
    capacity, threshold = limits(driver.run)
    if config.get('maxTokenLimit') != threshold or config.get('useModelReportedTokenCount') is not True:
        raise ValueError('Native session checkpoint configuration differs from the frozen contract')
    system = system_text(driver.run)
    if not prompt_only(spec, system):
        raise ValueError('Native session system prompt differs from the frozen system prompt')
    path = driver.run/'private/engine/context'/(driver.session+'.json')
    previous = json.loads(path.read_text()) if path.is_file() else {}
    write_json(path, {
        'session_id': driver.session, 'requested_context_capacity': capacity,
        'configured_auto_compact_token_limit': threshold, 'static_config_verified': True,
        'system_prompt': 'frozen_system_prompt_only',
        'system_prompt_sha256': hashlib.sha256(system.encode()).hexdigest(),
        'effective_auto_compact_token_limit': previous.get('effective_auto_compact_token_limit'),
        'provider_context_capacity_verified': False})


def verify_effective(driver):
    values = driver.rpc('GetCascadeTrajectoryExecutorMetadatas',
        {'cascadeId': driver.session, 'executorMetadataOffset': 0}).get('executorMetadata', [])
    _, threshold = limits(driver.run)
    if not values or any(v.get('cascadeConfig', {}).get('checkpointConfig', {}).get('maxTokenLimit') != threshold
                         for v in values):
        raise ValueError('Native execution did not retain the configured compaction threshold')
    path = driver.run/'private/engine/context'/(driver.session+'.json')
    receipt = json.loads(path.read_text())
    receipt['effective_auto_compact_token_limit'] = threshold
    receipt['executor_configurations_checked'] = len(values)
    write_json(path, receipt)
