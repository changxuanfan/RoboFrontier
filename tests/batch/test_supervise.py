"""The per-run loop both batch supervisors share (batch/supervise.py)."""
import unittest

from robofrontier.batch.supervise import supervise_run


class SuperviseRunTests(unittest.TestCase):
    def run_case(self, results, answers, *, continuing=False, state='prepared'):
        results, answers, records = list(results), list(answers), []
        outcome = supervise_run('run', lambda: results.pop(0), continuing=continuing, lifecycle=lambda run: state,
                                try_continue=lambda run, why: answers.pop(0), final=lambda r: r == 'final',
                                reason=str, record=lambda r, ok, why: records.append((r, ok)))
        return outcome, records

    def test_an_unexpected_end_continues_until_the_table_says_no(self):
        outcome, records = self.run_case(['crash', 'crash'], [(True, None), (False, 'already continued')])
        self.assertEqual(outcome, ('ended', 'crash', True))
        self.assertEqual(records, [('crash', True), ('crash', False)])

    def test_a_final_end_asks_nothing(self):
        self.assertEqual(self.run_case(['final'], []), (('ended', 'final', False), []))

    def test_a_continuing_batch_prepares_a_started_run_or_reports_why_not(self):
        outcome, records = self.run_case(['final'], [(True, None)], continuing=True, state='interrupted')
        self.assertEqual((outcome, records), (('ended', 'final', True), [(None, True)]))
        outcome, _ = self.run_case([], [(False, 'integrity')], continuing=True, state='ended')
        self.assertEqual(outcome, ('refused', 'integrity', False))
        self.assertEqual(self.run_case(['final'], [], continuing=True, state='resuming')[0], ('ended', 'final', True))


if __name__ == '__main__': unittest.main()
