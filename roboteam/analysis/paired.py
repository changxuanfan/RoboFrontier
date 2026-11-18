"""Paired comparisons between conditions that ran the same tasks.

Every condition runs the same tasks once, so two conditions are compared task by task: an exact
McNemar test on the tasks that only one of them completes, Holm's correction over a set of
such tests, and bootstrap intervals from resampling the tasks within each task type.

`results` maps a condition to `{task: (completed, hours)}`; `types` maps a task to its type.
"""

import random
import statistics
from math import comb


def discordant(results, a, b):
    """How many tasks only `a` completes, and how many only `b` completes."""
    tasks = results[a].keys() & results[b].keys()
    only_a = sum(1 for t in tasks if results[a][t][0] and not results[b][t][0])
    only_b = sum(1 for t in tasks if results[b][t][0] and not results[a][t][0])
    return only_a, only_b


def mcnemar_exact(only_a, only_b):
    """Two-sided exact McNemar p-value: a binomial test of the two discordant counts at 1/2."""
    n, k = only_a + only_b, min(only_a, only_b)
    return min(1.0, 2 * sum(comb(n, i) for i in range(k + 1)) / 2**n) if n else 1.0


def holm(p_values):
    """Holm's step-down correction; returns the adjusted p-values in the given order."""
    m = len(p_values)
    adjusted, running = [0.0] * m, 0.0
    for rank, i in enumerate(sorted(range(m), key=p_values.__getitem__)):
        running = max(running, min(1.0, (m - rank) * p_values[i]))
        adjusted[i] = running
    return adjusted


def compare(results, reference, others):
    """Each of `others` against `reference`: discordant counts, raw and Holm-corrected p."""
    counts = [discordant(results, reference, other) for other in others]
    raw = [mcnemar_exact(a, b) for a, b in counts]
    return [
        {'condition': other, 'only_reference': a, 'only_condition': b, 'p': p, 'p_holm': q}
        for other, (a, b), p, q in zip(others, counts, raw, holm(raw))
    ]


def _resample(types, rng):
    """One bootstrap sample of the tasks: drawn with replacement within each task type."""
    by_type = {}
    for task in sorted(types):
        by_type.setdefault(types[task], []).append(task)
    return [rng.choice(group) for _, group in sorted(by_type.items()) for _ in group]


def _interval(samples, level):
    samples = sorted(samples)
    tail = (1 - level) / 2
    return samples[int(tail * len(samples))], samples[int((1 - tail) * len(samples)) - 1]


def completed_interval(results, types, condition, resamples=20000, level=0.95, seed=0):
    """Bootstrap interval for the number of tasks a condition completes."""
    rng = random.Random(seed)
    return _interval(
        [sum(results[condition][t][0] for t in _resample(types, rng)) for _ in range(resamples)], level
    )


def speedup(results, slow, fast, tasks=None):
    """Median over the tasks both complete of the time of `slow` divided by the time of `fast`."""
    ratios = [
        results[slow][t][1] / results[fast][t][1]
        for t in (tasks or sorted(results[slow]))
        if results[slow][t][0] and results[fast][t][0]
    ]
    return statistics.median(ratios) if ratios else None


def speedup_interval(results, types, slow, fast, resamples=20000, level=0.95, seed=1):
    """Bootstrap interval for `speedup`; samples in which the two share no completed task are dropped."""
    rng = random.Random(seed)
    samples = [speedup(results, slow, fast, _resample(types, rng)) for _ in range(resamples)]
    return _interval([s for s in samples if s is not None], level)
