"""One monotonic launch gate per supervisor, shared by all task launchers."""
import math
import threading
import time


class LaunchSchedule:
    def __init__(self, interval_s=.3, *, clock=time.monotonic, sleep=time.sleep):
        if type(interval_s) not in (int, float) or not math.isfinite(interval_s) or interval_s < 0:
            raise ValueError('Startup interval must be finite and nonnegative')
        self.interval_s = interval_s
        self.clock, self.sleep = clock, sleep
        self._lock = threading.Lock()
        self._last_launch = None

    def launch(self, start, *, stopped=lambda: False):
        """Run only process creation under the gate, never wait for its result.

        Queued launches recheck STOP after waiting. The first launch is immediate.
        A failed creation also consumes its slot to avoid a launch retry storm.
        """
        with self._lock:
            while self._last_launch is not None:
                if stopped():
                    return None
                remaining = self._last_launch + self.interval_s - self.clock()
                if remaining <= 0:
                    break
                self.sleep(min(remaining, .1))
            if stopped():
                return None
            self._last_launch = self.clock()
            return start()
