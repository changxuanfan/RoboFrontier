"""Stable identity for non-secret model launch configuration."""

import hashlib
import json


def fingerprint(model_entry):
    return hashlib.sha256(json.dumps(model_entry, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
