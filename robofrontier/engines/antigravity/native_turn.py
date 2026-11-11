"""Distinguish a completed native turn from conversation-wide CLI errors."""
import sqlite3
from contextlib import closing

from .provenance import fields


def connection(driver):
    path = driver.home/'conversations'/(driver.session+'.db')
    return sqlite3.connect(path.as_uri()+'?mode=ro', uri=True, timeout=5)


def boundary(driver):
    with closing(connection(driver)) as db:
        count, last = db.execute('SELECT COUNT(*),MAX(idx) FROM steps').fetchone()
    if last is not None and last != count-1:
        raise ValueError('Native turn history is not contiguous')
    return count


def completed(driver, start, response):
    """Prove a new, settled, text-only final response after this input.

    CLI result.status/error scan the whole conversation. An old error_message
    can make every later result ERROR, including successful native forks. Do
    not retry a completed robot turn because of that cumulative field.
    """
    with closing(connection(driver)) as db:
        rows = db.execute('SELECT idx,step_type,status,step_payload FROM steps WHERE idx>=? ORDER BY idx',
                          (start,)).fetchall()
    if (not rows or [r[0] for r in rows] != list(range(start, start+len(rows)))
            or not any(r[1] == 14 for r in rows) or any(r[2] != 3 for r in rows)
            or rows[-1][1] != 15 or not isinstance(response, str)):
        return None
    try:
        final = fields(rows[-1][3])
        planner = fields(final[20])
        text = planner.get(8) or planner.get(1)
        if (final.get(1) != 15 or final.get(4) != 3 or 31 in final or 7 in planner
                or not isinstance(text, bytes) or text.decode().strip() != response.strip()):
            return None
    except (KeyError, ValueError, UnicodeDecodeError):
        return None
    return {'native_step_start': start, 'native_step_end': rows[-1][0],
            'native_final_response_verified': True, 'native_error_message_steps': sum(r[1] == 17 for r in rows)}
