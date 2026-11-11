"""Pinned native checkpoint configuration, verified before policy input.

The CLI has no public flag for this setting. Its local LanguageServerService
accepts an AgentConfig when creating a conversation; that static configuration
survives CLI resume and native forks. Never confuse its contextWindow string
(a model option name) with an integer capacity in tokens.
"""
import copy
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


def verify_static(driver):
    spec = driver.rpc('GetConversationMetadata', {'conversationId': driver.session})['metadata']['staticConfig']
    config = spec.get('agentConfig', {}).get('cascadeConfig', {}).get('checkpointConfig', {})
    capacity, threshold = limits(driver.run)
    if config.get('maxTokenLimit') != threshold or config.get('useModelReportedTokenCount') is not True:
        raise ValueError('Native session checkpoint configuration differs from the frozen contract')
    path = driver.run/'private/engine/context'/(driver.session+'.json')
    previous = json.loads(path.read_text()) if path.is_file() else {}
    write_json(path, {
        'session_id': driver.session, 'requested_context_capacity': capacity,
        'configured_auto_compact_token_limit': threshold, 'static_config_verified': True,
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
