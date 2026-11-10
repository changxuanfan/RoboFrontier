"""Blue-handle support counts only over continuously sampled time."""
import unittest

from robofrontier.tasks.evaluate import SupportQualification


class SupportQualificationTests(unittest.TestCase):
    def test_support_short_gap_does_not_amplify_into_a_new_full_dwell(self):
        q=SupportQualification()
        for i in range(15):q.update(i*.02,True)
        self.assertFalse(q.update(.30,False));self.assertTrue(q.update(.32,True))
        for i in range(17,22):q.update(i*.02,False)
        self.assertFalse(q.update(.44,True))
        for i in range(23,37):ready=q.update(i*.02,True)
        self.assertTrue(ready)

    def test_support_cannot_be_qualified_across_an_unsampled_interval(self):
        q=SupportQualification()
        q.update(0.,True);self.assertFalse(q.update(1.,True))


if __name__ == '__main__':
    unittest.main()
