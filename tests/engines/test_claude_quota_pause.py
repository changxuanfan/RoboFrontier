"""A Claude turn that failed on the plan's usage limit pauses the world until the reset and is
then continued once in the same session (runtime/quota.py); the Codex host does the same."""
import json
import os
import time
import unittest
from unittest.mock import patch

from engines.test_claude_network_resend import NetworkResendTests, turn

LIMIT = {'type': 'assistant', 'isApiErrorMessage': True, 'error': 'rate_limit',
         'message': {'content': [{'type': 'text', 'text': "You've hit your limit · resets 3pm (America/New_York)"}]}}


class QuotaPauseTests(NetworkResendTests):
    def setUp(self):
        super().setUp()
        patcher = patch.dict(os.environ, {'ROBOFRONTIER_NO_NOTIFY': '1'}); patcher.start(); self.addCleanup(patcher.stop)
        self.quota_notice = (self.run/'private/inputs/bootstrap/quota-resume.md').read_text()

    def test_a_usage_limit_is_not_a_capacity_error(self):
        summary = turn('s', LIMIT)['summary']
        self.assertIsNone(summary['capacity_error_code'])
        self.assertIn("hit your limit", summary['usage_limit']['text'])

    def test_the_world_pauses_until_the_reset_and_the_turn_continues_once(self):
        self.fail(LIMIT)
        self.assertTrue(self.recover())
        self.assertIsNotNone(self.s.store.get('quota_pause'))
        self.s.pump(); self.assertEqual(self.s.store.get('physics_state'), 'paused_by_egress')
        self.assertTrue(self.recover()); self.assertEqual(len(self.calls), 1)  # waiting for the reset
        self.s.egress_pause.quota['resets_at'] = time.time() - 120
        self.s.pump(); self.assertEqual(self.s.store.get('physics_state'), 'running')
        self.assertTrue(self.recover())
        self.host.wait(3)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.prompts[1], self.quota_notice)
        self.assertEqual(self.calls[1]['resume'], self.host.session_id)
        self.assertFalse(self.recover())  # handled; nothing more


del NetworkResendTests

if __name__ == '__main__': unittest.main()
