from concurrent.futures import ThreadPoolExecutor
import threading
import time
import unittest

from robofrontier.batch.launch_schedule import LaunchSchedule


class LaunchScheduleTests(unittest.TestCase):
    def test_concurrent_launches_use_one_gate_without_serializing_work(self):
        gate = LaunchSchedule(.015)
        starts = []
        working = threading.Event()

        def start():
            starts.append(time.monotonic())
            return working

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(lambda _: gate.launch(start), range(8)))
        self.assertTrue(all(result is working for result in results))
        self.assertTrue(all(b-a >= .014 for a, b in zip(starts, starts[1:])))
        self.assertFalse(working.is_set())  # The gate never waited for completion.

    def test_stop_during_a_queued_launch_prevents_creation(self):
        now = [0.]
        stopping = [False]
        def sleep(seconds):
            now[0] += seconds
            stopping[0] = True
        gate = LaunchSchedule(1, clock=lambda: now[0], sleep=sleep)
        calls = []
        gate.launch(lambda: calls.append('first'))
        result = gate.launch(lambda: calls.append('second'), stopped=lambda: stopping[0])
        self.assertIsNone(result)
        self.assertEqual(calls, ['first'])

    def test_invalid_intervals_fail_immediately(self):
        for value in (True, -.1, float('nan'), float('inf')):
            with self.subTest(value=value), self.assertRaises(ValueError):
                LaunchSchedule(value)


if __name__ == '__main__':
    unittest.main()
