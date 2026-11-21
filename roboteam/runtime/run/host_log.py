"""What a run's host writes about itself: the host event log and the simulation speed.

Every harness process appends to private/logs/host.jsonl through host_event; the world's
owner summarizes its own speed with simulation_speed. Reading these back into metrics is
in roboteam/launch/results/host_metrics.py.
"""

import json
import os
import time
from pathlib import Path

from roboteam.runtime.run import layout as run_layout


def host_event(run, event, **fields):
    # Telemetry is derived evidence. Its failure must not hide a robot result
    # or turn a settled action into an apparently unsubmitted request.
    try:
        path = run_layout.path(run, 'host_log')
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = (
            json.dumps(
                {'schema': 'roboteam.host-event.v1', 'at': time.time(), 'event': event, **fields},
                ensure_ascii=False,
                allow_nan=False,
            )
            + '\n'
        ).encode()
        fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o600)
        try:
            return os.write(fd, raw) == len(raw)
        finally:
            os.close(fd)
    except (OSError, ValueError, TypeError):
        return False


SPEED_WINDOW_S = 600.0


def simulation_speed(run, sim_s, active_s=None, stalls=None):
    """How fast the world ran: simulation time over active time, and the slowest 10 minutes.

    The windows come from the world's performance log (one cumulative step count every 5 s
    of wall time), so a window that held an outage pause also counts as slow. Recorded for
    comparing hosts; a slow run is never stopped for it."""
    rows = []
    for path in sorted(Path(run).glob('private/outputs/**/cpu-performance.jsonl')):
        for line in path.read_text(errors='replace').splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if (
                isinstance(row, dict)
                and isinstance(row.get('at'), (int, float))
                and isinstance(row.get('world_steps'), int)
            ):
                rows.append((row['at'], row['world_steps'], str(path)))
    worst = None
    for name in sorted({r[2] for r in rows}):
        series = [(at, steps) for at, steps, source in rows if source == name]
        j = 0
        for i in range(len(series)):
            while j < len(series) and series[j][0] - series[i][0] < SPEED_WINDOW_S:
                j += 1
            if j < len(series):
                ratio = (series[j][1] - series[i][1]) * 0.02 / (series[j][0] - series[i][0])
                worst = ratio if worst is None else min(worst, ratio)
    return {
        'sim_s': round(float(sim_s), 3),
        'active_s': None if active_s is None else round(float(active_s), 3),
        'speed_ratio': round(float(sim_s) / active_s, 4) if active_s else None,
        'active_time_stalls': stalls,
        'slowest_10min_speed_ratio': None if worst is None else round(worst, 4),
    }
