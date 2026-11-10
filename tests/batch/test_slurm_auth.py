"""Synthetic caches only: never read the operator's login or contact a provider."""
import base64
import json
import os
from pathlib import Path
import tempfile
import time
import unittest

from robofrontier.batch.slurm_auth import CredentialError, CredentialLease, BorrowedAccess


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
    def test_migration_preserves_latest_generation_and_retires_old_refresh_store(self):
        from robofrontier.batch.slurm_auth import migrate_store
        with CredentialLease(self.store,self.root/'first-home') as lease:
            private_json(lease.home/'auth.json',auth(7));lease.reconcile()
        current=(self.store/'current.json').read_bytes()
        destination=self.root/'durable-store'
        report=migrate_store(self.store,destination)
        self.assertTrue(report['source_retired'])
        self.assertEqual(json.loads(current),json.loads((destination/'current.json').read_bytes()))
        self.assertFalse((self.store/'auth.json').exists())
        self.assertFalse((self.store/'current.json').exists())
        self.assertFalse((destination/'auth.json').exists())
        with self.assertRaises(CredentialError):
            with CredentialLease(self.store,self.root/'old-home'):pass
        with CredentialLease(destination,self.root/'next-home') as lease:
            self.assertEqual(json.loads(current)['auth'],json.loads((lease.home/'auth.json').read_text()))

    def test_migration_refuses_a_live_refresh_owner_without_copying_credentials(self):
        from robofrontier.batch.slurm_auth import migrate_store
        destination=self.root/'durable-store'
        with CredentialLease(self.store,self.root/'owner'):
            with self.assertRaisesRegex(CredentialError,'leased'):
                migrate_store(self.store,destination)
        self.assertFalse(destination.exists())

    def test_migration_does_not_replace_an_existing_destination(self):
        from robofrontier.batch.slurm_auth import migrate_store
        with CredentialLease(self.store,self.root/'owner'):pass
        before=(self.store/'current.json').read_bytes()
        destination=self.root/'durable-store';destination.mkdir(mode=0o700)
        with self.assertRaises((CredentialError,FileExistsError)):
            migrate_store(self.store,destination)
        self.assertEqual((self.store/'current.json').read_bytes(),before)

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.store = self.root/'private-store'
        self.store.mkdir(mode=0o700)
        private_json(self.store/'auth.json', auth())

    def access_auth(self, generation=0, *, expires=None):
        value=auth(generation)
        claims={'sub':'fixture-user','exp':expires if expires is not None else time.time()+3600,
                'generation':generation,'https://api.openai.com/auth':{'chatgpt_account_id':'fixture-account'}}
        value['tokens']['access_token']='fixture.'+base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip('=')+'.fixture'
        return value

    def test_access_only_attachment_follows_rotation_without_a_second_refresh_lease(self):
        private_json(self.store/'auth.json',self.access_auth())
        with CredentialLease(self.store,self.root/'owner') as owner:
            before=(self.store/'current.json').read_bytes()
            with BorrowedAccess(self.store,self.root/'borrower') as reader:
                self.assertEqual((self.store/'current.json').read_bytes(),before)
                self.assertFalse((reader.home/'auth.json').exists())
                with self.assertRaisesRegex(CredentialError,'already leased'):
                    with CredentialLease(self.store,self.root/'forbidden'):pass
                private_json(owner.home/'auth.json',self.access_auth(1));owner.reconcile()
                self.assertTrue(reader.reconcile())
                self.assertEqual(reader.current['generation'],2)
            self.assertFalse((self.root/'borrower/auth.json').exists())

    def test_expired_borrowed_access_is_refused_without_creating_a_cache(self):
        private_json(self.store/'auth.json',self.access_auth(expires=time.time()-10))
        with CredentialLease(self.store,self.root/'owner'):
            with self.assertRaisesRegex(CredentialError,'expired'):
                with BorrowedAccess(self.store,self.root/'borrower'):pass
            self.assertFalse((self.root/'borrower').exists())

    def test_access_only_engine_cannot_write_its_own_refresh_cache(self):
        private_json(self.store/'auth.json',self.access_auth())
        with CredentialLease(self.store,self.root/'owner'):
            with self.assertRaisesRegex(CredentialError,'unexpectedly wrote'):
                with BorrowedAccess(self.store,self.root/'borrower') as reader:
                    private_json(reader.home/'auth.json',self.access_auth())

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

    def test_a_bootstrap_lost_between_its_two_writes_leaves_a_usable_store(self):
        from unittest.mock import patch
        from robofrontier.batch import slurm_auth
        original, writes = slurm_auth._atomic_private, []
        def lost_after_first(path, value):
            if writes: raise KeyboardInterrupt('job killed')
            writes.append(path.name); original(path, value)
        with patch.object(slurm_auth, '_atomic_private', side_effect=lost_after_first):
            with self.assertRaises(KeyboardInterrupt):
                with CredentialLease(self.store, self.root/'job'):
                    pass
        with CredentialLease(self.store, self.root/'next') as lease:
            self.assertEqual(lease.current['generation'], 1)
        self.assertTrue((self.store/'initialized.json').exists())

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
