"""Synthetic caches only: never read the operator's login or contact a provider."""
import base64
import json
import os
from pathlib import Path
import tempfile
import unittest

from robofrontier.slurm_auth import CredentialError, CredentialLease


def auth(generation=0, account='fixture-account', subject='fixture-user'):
    claims = {'sub': subject, 'https://api.openai.com/auth': {'chatgpt_account_id': account}}
    token = 'fixture.' + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=') + '.fixture'
    return {'auth_mode': 'chatgpt', 'OPENAI_API_KEY': None,
            'tokens': {'id_token': token, 'access_token': 'fixture-access-'+str(generation),
                       'refresh_token': 'fixture-refresh-'+str(generation), 'account_id': account}}


def private_json(path, value):
    path.write_text(json.dumps(value))
    path.chmod(0o600)


class CredentialCustodyTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.store = self.root/'private-store'
        self.store.mkdir(mode=0o700)
        private_json(self.store/'auth.json', auth())

    def test_native_rotation_is_durable_and_next_job_ignores_old_seed(self):
        with CredentialLease(self.store, self.root/'job-one') as lease:
            private_json(lease.home/'auth.json', auth(1))
            self.assertTrue(lease.reconcile())
            self.assertEqual(lease.current['generation'], 2)
        # The still-present bootstrap must never undo the native rotation.
        with CredentialLease(self.store, self.root/'job-two') as lease:
            self.assertEqual(json.loads((lease.home/'auth.json').read_text()), auth(1))
        self.assertEqual((self.store/'current.json').stat().st_mode & 0o777, 0o600)

    def test_second_owner_cannot_seed_or_refresh_until_first_closes(self):
        with CredentialLease(self.store, self.root/'job-one'):
            with self.assertRaisesRegex(CredentialError, 'already leased'):
                with CredentialLease(self.store, self.root/'job-two'):
                    self.fail('A second native manager acquired the credential stream')
            self.assertFalse((self.root/'job-two').exists())
        with CredentialLease(self.store, self.root/'job-two'):
            pass

    def test_partial_native_write_does_not_overwrite_valid_persisted_generation(self):
        with CredentialLease(self.store, self.root/'job') as lease:
            before = (self.store/'current.json').read_bytes()
            (lease.home/'auth.json').write_bytes(b'{"tokens":')
            self.assertFalse(lease.reconcile())
            self.assertEqual((self.store/'current.json').read_bytes(), before)
            private_json(lease.home/'auth.json', auth(2))
        with CredentialLease(self.store, self.root/'next') as lease:
            self.assertEqual(lease.current['auth'], auth(2))

    def test_final_truncation_is_a_failure_and_old_seed_is_never_restored(self):
        with self.assertRaises(CredentialError):
            with CredentialLease(self.store, self.root/'job') as lease:
                (lease.home/'auth.json').write_bytes(b'')
        self.assertEqual((self.root/'job/auth.json').read_bytes(), b'')

    def test_missing_persisted_generation_does_not_fall_back_to_bootstrap(self):
        with CredentialLease(self.store, self.root/'job') as lease:
            private_json(lease.home/'auth.json', auth(1))
        (self.store/'current.json').unlink()
        with self.assertRaisesRegex(CredentialError, 'never restore'):
            with CredentialLease(self.store, self.root/'next'):
                pass

    def test_wrong_owner_and_out_of_band_generation_change_are_fenced(self):
        with CredentialLease(self.store, self.root/'job') as lease:
            private_json(lease.home/'auth.json', auth(1, account='other-account'))
            with self.assertRaisesRegex(CredentialError, 'owner changed'):
                lease.reconcile()
            private_json(lease.home/'auth.json', auth())
            previous = dict(lease.current)
            private_json(self.store/'current.json', {**previous, 'generation': 77})
            with self.assertRaisesRegex(CredentialError, 'outside its lease'):
                lease.reconcile()
            private_json(self.store/'current.json', previous)

    def test_bad_cache_and_unsafe_files_never_expose_cache_contents_in_errors(self):
        secret = 'FIXTURE_SECRET_MUST_NOT_APPEAR'
        for value in ({'tokens': secret}, {'auth_mode': 'apikey', 'OPENAI_API_KEY': secret}):
            private_json(self.store/'auth.json', value)
            with self.assertRaises(CredentialError) as caught:
                with CredentialLease(self.store, self.root/'job'):
                    pass
            self.assertNotIn(secret, str(caught.exception))
        private_json(self.store/'auth.json', auth())
        (self.store/'auth.json').chmod(0o644)
        with self.assertRaises(CredentialError):
            with CredentialLease(self.store, self.root/'job'):
                pass
        (self.store/'auth.json').unlink()
        (self.store/'auth.json').symlink_to(self.root/'unrelated')
        with self.assertRaises(CredentialError):
            with CredentialLease(self.store, self.root/'job'):
                pass

    def test_watcher_failure_stops_admission_and_final_close_reports_failure(self):
        import threading
        stopped = threading.Event()
        with self.assertRaisesRegex(CredentialError, 'persistence failed'):
            with CredentialLease(self.store, self.root/'job') as lease:
                private_json(lease.home/'auth.json', auth(1, subject='wrong-subject'))
                lease.watch(stopped.set, interval_s=.01)
                self.assertTrue(stopped.wait(2))


if __name__ == '__main__':
    unittest.main()
