"""A plan's usage limit is told apart from a short rate limit, and its reset time is read."""
from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

from robofrontier.runtime.quota import MARGIN_S, PAST_RESET_S, RECHECK_S, resume_at, usage_limit

NY = ZoneInfo('America/New_York')
NOW = datetime(2026, 11, 10, 14, 31, tzinfo=NY).timestamp()


class QuotaTests(unittest.TestCase):
    def test_claude_reset_today_and_on_a_date(self):
        found = usage_limit("You've hit your limit · resets 3pm (America/New_York)", NOW)
        self.assertEqual(found['resets_at'], datetime(2026, 11, 10, 15, 0, tzinfo=NY).timestamp())
        found = usage_limit("You've hit your weekly limit · resets Nov 14, 9am (America/New_York)", NOW)
        self.assertEqual(found['resets_at'], datetime(2026, 11, 14, 9, 0, tzinfo=NY).timestamp())
        # A time that passed more than three hours ago is tomorrow's; a more recent one is today's,
        # a reset still under way.
        found = usage_limit("You've hit your session limit · resets 10am (America/New_York)", NOW)
        self.assertEqual(found['resets_at'], datetime(2026, 11, 11, 10, 0, tzinfo=NY).timestamp())
        found = usage_limit("You've hit your session limit · resets 1:30pm (America/New_York)", NOW)
        self.assertEqual(found['resets_at'], datetime(2026, 11, 10, 13, 30, tzinfo=NY).timestamp())

    def test_a_limit_that_outlasts_its_stated_reset(self):
        # 2026-11-13: worlds resumed at 15:21 after "resets 3:20pm"; the continuation failed again
        # with the same text. It was read as tomorrow's 3:20pm, and in other runs it ended the new
        # pause at once, spending the roles' one continuation on a limit still in force.
        hk = ZoneInfo('Asia/Hong_Kong')
        now = datetime(2026, 11, 13, 15, 21, tzinfo=hk).timestamp()
        found = usage_limit("You've hit your 5-hour limit \u00b7 resets 3:20pm (Asia/Hong_Kong)", now)
        self.assertEqual(found['resets_at'], datetime(2026, 11, 13, 15, 20, tzinfo=hk).timestamp())
        self.assertEqual(resume_at({'resets_at': found['resets_at'], 'paused_at': now}), now + PAST_RESET_S)

    def test_a_hyphenated_window_name_is_a_usage_limit(self):
        # The message that stopped ten Opus runs on 2026-11-11: it was read as a session error.
        now = datetime(2026, 11, 11, 17, 45, tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp()
        found = usage_limit("You've hit your 5-hour limit \u00b7 resets 9:10pm (Asia/Hong_Kong)", now)
        self.assertIsNotNone(found)
        self.assertEqual(found['resets_at'], datetime(2026, 11, 11, 21, 10, tzinfo=ZoneInfo('Asia/Hong_Kong')).timestamp())
        self.assertIsNotNone(usage_limit("You\u2019ve hit your 7-day limit \u00b7 resets Nov 14, 9am (America/New_York)", now))

    def test_older_claude_and_codex_texts(self):
        self.assertEqual(usage_limit('Claude AI usage limit reached|1700000000', NOW)['resets_at'], None)  # far past
        self.assertEqual(usage_limit('Claude AI usage limit reached|%d' % (NOW + 600), NOW)['resets_at'], NOW + 600)
        found = usage_limit({'message': "You've hit your usage limit. Upgrade to Pro or try again in 2 days 4 hours."}, NOW)
        self.assertEqual(found['resets_at'], NOW + 2 * 86400 + 4 * 3600)
        found = usage_limit({'codexErrorInfo': {'usageLimitExceeded': {}}, 'message': 'limit'}, NOW)
        self.assertEqual(found['resets_at'], None)

    def test_the_codex_record_seen_on_2026_11_11(self):
        error = {'message': 'You\u2019ve hit your usage limit. Visit https://chatgpt.com/settings/usage to purchase more '
                            'credits or try again at 7:52 AM.', 'codexErrorInfo': 'usageLimitExceeded', 'additionalDetails': None}
        now = datetime(2026, 11, 11, 7, 49).astimezone().timestamp()
        for value in (error, error['message']):
            found = usage_limit(value, now)
            self.assertEqual(found['resets_at'], datetime(2026, 11, 11, 7, 52).astimezone().timestamp())

    def test_a_rate_limit_is_not_a_plan_limit(self):
        for text in ('rate_limit_error: 429 Too Many Requests', 'overloaded_error', 'server_overloaded'):
            self.assertIsNone(usage_limit(text, NOW))

    def test_the_world_resumes_after_the_reset_or_rechecks(self):
        self.assertEqual(resume_at({'resets_at': NOW + 100, 'paused_at': NOW}), NOW + 100 + MARGIN_S)
        self.assertEqual(resume_at({'resets_at': None, 'paused_at': NOW}), NOW + RECHECK_S)


if __name__ == '__main__': unittest.main()


import os
import time
from unittest.mock import patch

from runtime import test_active_time as active


class WorldQuotaPauseTests(active.Fixture):
    """A host's quota-pause request holds the world until the reset, then it resumes by itself."""
    def setUp(self):
        super().setUp()
        patcher = patch.dict(os.environ, {'ROBOFRONTIER_NO_NOTIFY': '1'}); patcher.start(); self.addCleanup(patcher.stop)
        from robofrontier.runtime.egress_pause import WorldPause
        self.s.egress_pause = WorldPause(self.s, None)
        self.s.store.put('physics_state', 'running')

    def test_held_until_the_reset_then_resumed_with_a_continuation_window(self):
        from robofrontier.runtime.cli import execute
        request = {'actor': 'Controller', 'thread_id': 'Controller', 'resets_at': time.time() + 100,
                   'text': "You've hit your limit · resets 3pm"}
        self.assertTrue(execute(self.s.store, 'quota-pause', request, 'host', time.time())['paused'])
        # A second role's request joins the first.
        execute(self.s.store, 'quota-pause', {**request, 'actor': 'A', 'thread_id': 'A'}, 'host', time.time())
        self.s.pump()
        self.assertEqual(self.s.store.get('physics_state'), 'paused_by_egress')
        self.assertEqual(len(self.events('QUOTA_PAUSED')), 1)
        self.s.pump(); self.assertEqual(self.events('QUOTA_RESUMED'), [])
        # The pause began before its reset, and the reset has passed.
        self.s.egress_pause.quota.update(paused_at=time.time() - 300, resets_at=time.time() - 120)
        self.s.pump()
        self.assertEqual(len(self.events('QUOTA_RESUMED')), 1)
        self.assertIsNone(self.s.store.get('quota_pause'))
        self.assertEqual(self.s.store.get('egress_recovery')['claim'], 'quota-1')
        self.assertEqual(self.s.store.get('physics_state'), 'running')
        self.assertGreaterEqual(self.s.store.get('pause_wall_s'), 0.)
        lines = (self.run/'private/outputs/notifications.jsonl').read_text().splitlines()
        self.assertEqual(len(lines), 2)
