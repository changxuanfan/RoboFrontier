"""Recognize a plan's usage limit in a failed model turn, and read when it resets.

A subscription's 5-hour or weekly limit lasts until its reset, so retrying within a few
minutes cannot help (codex_rpc.capacityFailure leaves it out). Instead the host asks the
world to pause (runtime_cli quota-pause): physics and dispatch are held and the time is not
counted, as in a network outage (egress_pause.WorldPause). The world resumes itself at the
reset, and the host continues the failed turn once with the frozen quota notice. It is the
same segment; no continuation is used. See docs/running/continuation.md#usage-limit-pause.

    Claude Code: "You've hit your limit · resets 3pm (America/New_York)"
                 "You've hit your weekly limit · resets Nov 14, 9am (Asia/Shanghai)"
                 "Claude AI usage limit reached|1794360000"
    Codex:       "You've hit your usage limit. ... try again at 3:05 PM." / "... try again in 2 days 4 hours"
                 or a turn error whose codexErrorInfo names usageLimitExceeded
"""
import json
import re
import time
from datetime import datetime, timedelta

# Text that names a plan limit (not a short rate limit).
LIMIT = re.compile(r"(you'?ve hit your (?:\w+ )?(?:usage )?limit|usage limit reached|usage[_ ]limit[_ ]exceeded|"
                   r"usageLimitExceeded|weekly limit|session limit)", re.I)
# When a reset time cannot be read, the world tries again after this long.
RECHECK_S = 1800.
# The world resumes this long after the stated reset, as reset times are rounded.
MARGIN_S = 60.
# A reset further away than this is not believed; the world tries again after RECHECK_S.
LONGEST_S = 8 * 86400.


def _zone(name):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:
        return None


def _clock(text):
    """(hour, minute) of '3pm', '3:45 pm', '15:05'; None otherwise."""
    found = re.fullmatch(r'(\d{1,2})(?::(\d{2}))?\s*([ap]\.?m\.?)?', text.strip(), re.I)
    if not found: return None
    hour, minute, half = int(found.group(1)), int(found.group(2) or 0), (found.group(3) or '').lower().replace('.', '')
    if half == 'pm' and hour != 12: hour += 12
    if half == 'am' and hour == 12: hour = 0
    if not (0 <= hour < 24 and 0 <= minute < 60): return None
    return hour, minute


MONTHS = {m: i + 1 for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'))}


def _at(when, now, zone):
    """The epoch time of a stated reset ('3pm', 'Nov 14, 9am', 'Nov 14th, 2026 3:05 PM'), the next
    such moment after `now` when no date is given."""
    tz = zone or datetime.now().astimezone().tzinfo
    local = datetime.fromtimestamp(now, tz)
    when = re.sub(r'(\d)(st|nd|rd|th)\b', r'\1', when.strip().rstrip('.'), flags=re.I)
    dated = re.fullmatch(r'([A-Za-z]{3})[a-z]*\.?\s+(\d{1,2})(?:,?\s*(\d{4}))?(?:,|\s+at)?\s+(.+)', when)
    if dated:
        month = MONTHS.get(dated.group(1).lower()); clock = _clock(dated.group(4))
        if month is None or clock is None: return None
        year = int(dated.group(3) or local.year)
        try: moment = datetime(year, month, int(dated.group(2)), *clock, tzinfo=tz)
        except ValueError: return None
        if not dated.group(3) and moment.timestamp() < now - 86400: moment = moment.replace(year=year + 1)
        return moment.timestamp()
    clock = _clock(when)
    if clock is None: return None
    moment = local.replace(hour=clock[0], minute=clock[1], second=0, microsecond=0)
    if moment.timestamp() <= now: moment += timedelta(days=1)
    return moment.timestamp()


def _within(text):
    """Seconds of 'in 2 days 4 hours 3 minutes'; None when nothing is stated."""
    total, seen = 0., False
    for amount, unit in re.findall(r'(\d+)\s*(day|hour|hr|minute|min|second|sec)s?\b', text, re.I):
        seen = True
        total += int(amount) * {'day': 86400, 'hour': 3600, 'hr': 3600, 'minute': 60, 'min': 60,
                                'second': 1, 'sec': 1}[unit.lower()]
    return total if seen else None


def resets_at(text, now=None):
    """When the limit named in `text` resets (epoch seconds), or None when it is not stated."""
    now = time.time() if now is None else now
    epoch = re.search(r'usage limit reached\|(\d{9,11})', text, re.I)
    if epoch: return float(epoch.group(1))
    stated = re.search(r'resets?\s+(?:at\s+)?([^()\n]+?)\s*(?:\(([\w/+-]+)\))?\s*(?:$|[.\n])', text, re.I)
    if stated:
        return _at(stated.group(1), now, _zone(stated.group(2)) if stated.group(2) else None)
    again = re.search(r'try again (in|at)\s+([^\n]+?)\s*(?:$|\.\s|\.$|\n)', text, re.I)
    if again:
        if again.group(1).lower() == 'in':
            seconds = _within(again.group(2))
            return None if seconds is None else now + seconds
        return _at(again.group(2), now, None)
    return None


def usage_limit(error, now=None):
    """{'text', 'resets_at'} when a failed turn's error names a plan's usage limit, else None.

    `error` is the error's text or its structured record (Codex's turn error)."""
    text = error if isinstance(error, str) else json.dumps(error, ensure_ascii=False)
    if not text or not LIMIT.search(text): return None
    now = time.time() if now is None else now
    reset = resets_at(text, now)
    if reset is not None and not now - 3600 < reset < now + LONGEST_S: reset = None
    return {'text': text[:500], 'resets_at': reset}


def resume_at(request, now=None):
    """When a world paused for this request resumes: after the stated reset, else RECHECK_S after
    the pause began."""
    reset = request.get('resets_at')
    started = request.get('paused_at') or (time.time() if now is None else now)
    return reset + MARGIN_S if isinstance(reset, (int, float)) else started + RECHECK_S


def main(argv=None):
    """python -m robofrontier.runtime.quota TEXT : the recognized limit, as JSON (for the Codex host)."""
    import sys
    argv = sys.argv[1:] if argv is None else argv
    print(json.dumps(usage_limit(' '.join(argv))))


if __name__ == '__main__':
    main()
