import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

from roboteam.harness.adapters.gpt_in_claude import auth


class PlanAuthenticationTests(unittest.TestCase):
    def tokens(self):
        return {'access_token': 'test-access', 'refresh_token': 'test-refresh', 'expires_in': 3600,
                'scope': 'resource.invoke chatgpt.tokens.use.direct'}

    def test_identity_without_plan_permission_is_not_authorized(self):
        tokens = self.tokens()
        tokens['scope'] = 'openid profile'
        with self.assertRaises(ValueError):
            auth.credentials(tokens, 'test-client', 'urn:uuid:test', {'sub': 'test-subject'})

    def test_scope_omitted_on_refresh_preserves_original_grant(self):
        saved = auth.credentials(self.tokens(), 'test-client', 'urn:uuid:test', {'sub': 'test-subject'})
        renewed = self.tokens()
        renewed.pop('scope')
        self.assertEqual(auth.credentials(renewed, 'test-client', 'urn:uuid:test', {'sub': 'test-subject'}, saved)['scopes'], saved['scopes'])

    def test_refresh_rotates_credentials_together(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'account.json'
            saved = auth.credentials(self.tokens(), 'test-client', 'urn:uuid:test', {'sub': 'test-subject'})
            saved['expires_at'] = 0
            auth.atomic_json(path, saved)
            renewed = {**self.tokens(), 'access_token': 'new-access', 'refresh_token': 'new-refresh'}
            with patch.object(auth, 'exchange', return_value=renewed):
                self.assertEqual(auth.CredentialStore(path).access_token(), 'new-access')
            result = json.loads(path.read_text())
            self.assertEqual(result['refresh_token'], 'new-refresh')
            self.assertGreater(result['expires_at'], time.time())
            self.assertEqual(list(Path(temporary).glob('*.tmp')), [])

    def test_changed_refresh_identity_keeps_original_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'account.json'
            saved = auth.credentials(self.tokens(), 'test-client', 'urn:uuid:test', {'sub': 'test-subject'})
            saved['expires_at'] = 0
            auth.atomic_json(path, saved)
            before = path.read_bytes()
            with patch.object(auth, 'exchange', return_value={**self.tokens(), 'id_token': 'new-id'}), \
                 patch.object(auth, 'validate_identity', return_value={'sub': 'different-subject'}), self.assertRaises(ValueError):
                auth.CredentialStore(path).access_token()
            self.assertEqual(path.read_bytes(), before)

    def test_explicit_refresh_uses_same_granted_account(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)/'account.json'
            auth.atomic_json(path, auth.credentials(self.tokens(), 'test-client', 'urn:uuid:test', {'sub': 'test-subject'}))
            with patch.object(auth, 'exchange', return_value={**self.tokens(), 'access_token': 'renewed'}) as exchange:
                self.assertEqual(auth.CredentialStore(path).access_token(force_refresh=True), 'renewed')
                self.assertEqual(exchange.call_args.args[0]['client_id'], 'test-client')


if __name__ == '__main__':
    unittest.main()
