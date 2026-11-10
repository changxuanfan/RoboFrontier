"""Closing a shared connection must wait for its current transaction to finish."""
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest

from robofrontier.engines.claude.budget import BudgetLedger
from robofrontier.runtime.store import RuntimeStore


class ConnectionLifecycleTests(unittest.TestCase):
    def check_close_during_transaction(self, resource):
        attempted = threading.Event()
        entered_close = threading.Event()
        allow_close = threading.Event()
        errors = []
        connection, lock = resource.db, resource.lock

        class ObservedLock:
            def __enter__(self):
                if threading.current_thread() is closer:
                    attempted.set()
                return lock.__enter__()

            def __exit__(self, *args):
                return lock.__exit__(*args)

        class ObservedConnection:
            def __getattr__(self, name):
                return getattr(connection, name)

            def close(self):
                entered_close.set()
                attempted.set()
                # Keep the regression safe even on the original unlocked close:
                # observe entry, but let COMMIT finish before native sqlite close.
                if not allow_close.wait(3):
                    raise TimeoutError('Transaction did not finish before close')
                connection.close()

        def close():
            try:
                resource.close()
            except BaseException as error:
                errors.append(error)

        resource.lock, resource.db = ObservedLock(), ObservedConnection()
        closer = threading.Thread(target=close)
        try:
            with resource.transaction():
                resource.db.execute('CREATE TABLE close_probe (value TEXT)')
                resource.db.execute("INSERT INTO close_probe VALUES ('committed')")
                closer.start()
                self.assertTrue(attempted.wait(3), 'Close thread did not run')
                closed_before_commit = entered_close.is_set()
        finally:
            allow_close.set()
            if closer.ident is not None:
                closer.join(3)
            resource.db, resource.lock = connection, lock
        self.assertFalse(closer.is_alive(), 'Close did not finish after commit')
        self.assertEqual(errors, [])
        self.assertFalse(closed_before_commit, 'Native close entered during a transaction')
        with sqlite3.connect(resource.path) as reopened:
            self.assertEqual(reopened.execute('SELECT value FROM close_probe').fetchone(), ('committed',))

    def test_budget_close_waits_for_transaction_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = BudgetLedger.create(Path(tmp) / 'budget.sqlite', 1)
            try:
                self.check_close_during_transaction(ledger)
            finally:
                ledger.close()

    def test_runtime_close_waits_for_transaction_commit(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = RuntimeStore(Path(tmp) / 'runtime.sqlite')
            try:
                self.check_close_during_transaction(store)
            finally:
                store.close()


if __name__ == '__main__':
    unittest.main()
