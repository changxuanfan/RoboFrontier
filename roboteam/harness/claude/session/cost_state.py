"""Read native cumulative cost metadata without treating history as new spend."""
from decimal import Decimal, InvalidOperation
import json
from pathlib import Path
import re

UUID = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}')


def amount(value):
    if isinstance(value, bool):
        return None
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() and number >= 0 else None


def baseline(directory, session):
    """Return a verified native counter, or None for a conservative upper bound.

    Missing historical bookkeeping never authorizes a deduction. A native
    unknown-model-cost marker is a separate error before another capped call.
    Only the selected session transcript is read; credential files are not used.
    """
    if session is None:
        return Decimal('0')
    if not isinstance(session, str) or not UUID.fullmatch(session):
        return None
    matches = list(Path(directory).glob('projects/*/'+session+'.jsonl'))
    if len(matches) != 1:
        return None
    latest = None
    try:
        for line in matches[0].read_text().splitlines():
            row = json.loads(line)
            if row.get('type') != 'cost-state' or row.get('sessionId') != session:
                continue
            latest = row
    except (OSError, json.JSONDecodeError, AttributeError):
        return None
    if latest is None:
        return None
    if latest.get('hasUnknownModelCost') is True:
        raise ValueError('Native session has unknown model cost')
    return amount(latest.get('totalCostUSD')) if latest.get('hasUnknownModelCost') is False else None


def invocation_cost(summary, before):
    """Keep the raw total and deduct only a verified, nondecreasing baseline."""
    total = amount(summary.get('total_cost_usd'))
    summary['native_session_total_cost_usd'] = summary.get('total_cost_usd')
    summary['native_cost_baseline_usd'] = str(before) if before is not None else None
    if total is None or before is not None and total < before:
        summary['total_cost_usd'] = None
        summary['cost_scope'] = 'unknown'
    else:
        summary['total_cost_usd'] = float(total-before) if before is not None else float(total)
        summary['cost_scope'] = 'invocation' if before is not None else 'session_total_upper_bound'
