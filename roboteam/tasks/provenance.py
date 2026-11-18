"""Content fingerprints for physical assets, independent of catalogue status."""

import hashlib
import json


def environment_logic_manifest(source_hashes, task=None):
    """Fingerprint the evaluator, and for Dial its game."""
    names = ('roboteam/tasks/evaluate.py',)
    if task and task.get('task_type') == 'dial':
        names += ('roboteam/tasks/dial.py',)
    code = {name: source_hashes[name] for name in names}
    payload = json.dumps(code, sort_keys=True, separators=(',', ':')).encode()
    return dict(
        schema='roboteam.environment-logic.v2', sha256=hashlib.sha256(payload).hexdigest(), sources=code
    )
