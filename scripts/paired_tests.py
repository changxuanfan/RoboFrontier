#!/usr/bin/env python3
"""Compare conditions task by task: exact McNemar tests with Holm's correction, and bootstrap intervals.

Data never lives in the repository: pass a JSON file of outcomes.

  paired_tests.py outcomes.json --reference Adaptive [--baseline Single-agent] [--out report.json]

`outcomes.json` holds `{"types": {task: type}, "results": {condition: {task: [completed, hours]}}}`.
Every other condition is compared with `--reference`. With `--baseline`, the report also gives how
many times as fast each condition is as the baseline on the tasks both complete.
"""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from roboteam.analysis import paired  # noqa: E402


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument('outcomes', type=Path)
    p.add_argument('--reference', required=True)
    p.add_argument('--baseline')
    p.add_argument('--resamples', type=int, default=20000)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    document = json.loads(a.outcomes.read_text())
    results, types = document['results'], document['types']
    others = [c for c in results if c != a.reference]
    report = {'reference': a.reference, 'paired': paired.compare(results, a.reference, others),
              'completed': {c: {'tasks': sum(v[0] for v in results[c].values()),
                                'interval': paired.completed_interval(results, types, c, a.resamples)}
                            for c in results}}
    if a.baseline:
        report['speedup'] = {c: {'median': paired.speedup(results, a.baseline, c),
                                 'interval': paired.speedup_interval(results, types, a.baseline, c, a.resamples)}
                             for c in results if c != a.baseline}
    text = json.dumps(report, indent=2)
    if a.out: a.out.write_text(text + '\n')
    else: print(text)


if __name__ == '__main__':
    main()
