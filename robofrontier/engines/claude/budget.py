"""Durable shared reservations against CLI-reported estimates, not provider bills."""
from contextlib import contextmanager
from decimal import Decimal, InvalidOperation
import os
from pathlib import Path
import sqlite3
import threading
import time

from ...runtime.sqlite_busy import BUSY_TIMEOUT_SECONDS, begin_immediate

UNLIMITED = 'unlimited'


class BudgetExhausted(ValueError):
    """The task cap has no allowance left: a turn was refused before anything launched."""


def _money(value, *, positive=True):
    if isinstance(value, bool): raise ValueError('Invalid monetary amount')
    try: result = Decimal(str(value))
    except (InvalidOperation, ValueError) as error: raise ValueError('Invalid monetary amount') from error
    if not result.is_finite() or (result <= 0 if positive else result < 0):
        raise ValueError('Invalid monetary amount')
    return result


class BudgetLedger:
    """Serialize task-wide CLI cost reservations across sessions and processes.

    A reservation with an unknown outcome blocks further spending and is never
    released automatically. Account statements and provider-enforced limits
    remain authoritative; CLI totals are estimates that can be absent or wrong.
    """
    def __init__(self, path):
        self.path = Path(path)
        if not self.path.is_file(): raise ValueError('Budget ledger does not exist')
        self.lock = threading.RLock()
        self.db = sqlite3.connect(self.path, isolation_level=None, check_same_thread=False, timeout=BUSY_TIMEOUT_SECONDS)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA journal_mode=WAL'); self.db.execute('PRAGMA synchronous=FULL')
        if self.db.execute("SELECT value FROM meta WHERE key='limit'").fetchone() is None:
            self.db.close(); raise ValueError('Budget ledger is not initialized')

    @classmethod
    def create(cls, path, total_usd=None):
        total = _money(total_usd) if total_usd is not None else UNLIMITED
        path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600); os.close(fd)
        db = sqlite3.connect(path)
        try:
            db.executescript('''CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE reservations (id TEXT PRIMARY KEY, actor TEXT NOT NULL, allowance TEXT NOT NULL,
                  cost TEXT, status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL);''')
            db.execute('INSERT INTO meta VALUES (?,?)', ('limit', str(total))); db.commit()
        finally: db.close()
        return cls(path)

    @contextmanager
    def transaction(self):
        with self.lock:
            begin_immediate(self.db, self.path)
            try:
                yield
                self.db.execute('COMMIT')
            except BaseException:
                self.db.execute('ROLLBACK')
                raise

    def _snapshot(self):
        stored_limit = self.db.execute("SELECT value FROM meta WHERE key='limit'").fetchone()[0]
        limit = None if stored_limit == UNLIMITED else Decimal(stored_limit)
        rows = [dict(r) for r in self.db.execute('SELECT * FROM reservations ORDER BY created, id')]
        for row in rows:
            if row['allowance'] == UNLIMITED: row['allowance'] = None
        spent = sum((Decimal(r['cost']) for r in rows if r['status'] == 'settled' and r['cost'] is not None), Decimal('0'))
        reserved = sum((Decimal(r['allowance']) for r in rows if r['status'] == 'reserved' and r['allowance'] is not None), Decimal('0'))
        unknown = any(r['status'] == 'uncertain' for r in rows)
        return {'limit_usd': str(limit) if limit is not None else None,
                'reported_spend_usd': str(spent), 'reserved_usd': str(reserved),
                'uncapped_pending_count': sum(r['status'] == 'reserved' and r['allowance'] is None for r in rows),
                'unreported_cost_count': sum(r['status'] == 'settled' and r['cost'] is None for r in rows),
                'available_usd': str(max(Decimal('0'), limit-spent-reserved)) if limit is not None else None,
                'status': 'uncertain' if unknown else 'exhausted' if limit is not None and limit-spent-reserved <= 0 else 'tracking',
                'reservations': rows, 'source': 'cli_reported_estimates_not_provider_bill'}

    def snapshot(self):
        with self.transaction(): return self._snapshot()

    def settle_interrupted(self):
        """Before a run continues in a new segment (docs/running/run-segments.md): turns cut off by
        the unexpected exit have ended, with an unknown cost. Without a task cap that cost
        cannot breach anything, so they become settled with no reported cost; under a cap
        they become uncertain and keep blocking, since the cut-off turn may have spent
        more than its allowance."""
        with self.transaction():
            if self._snapshot()['limit_usd'] is None:
                # A cut-off turn whose CLI still reported a cost keeps it; only an absent cost stays absent.
                self.db.execute("UPDATE reservations SET status='settled', updated=? "
                                "WHERE status IN ('reserved','uncertain')", (time.time(),))
            else:
                self.db.execute("UPDATE reservations SET status='uncertain', updated=? WHERE status='reserved'",
                                (time.time(),))
            return self._snapshot()

    def reserve(self, reservation_id, actor, maximum_usd=None):
        maximum = _money(maximum_usd) if maximum_usd is not None else None
        if not isinstance(reservation_id, str) or not reservation_id or not isinstance(actor, str) or not actor:
            raise ValueError('Reservation identity required')
        with self.transaction():
            state = self._snapshot()
            if state['status'] == 'exhausted': raise BudgetExhausted('Budget is exhausted or uncertain')
            if state['status'] != 'tracking': raise ValueError('Budget is exhausted or uncertain')
            available = Decimal(state['available_usd']) if state['available_usd'] is not None else None
            allowance = maximum if maximum is not None else available
            if available is not None and allowance is not None:
                allowance = min(allowance, available)
            now = time.time()
            try:
                self.db.execute('INSERT INTO reservations VALUES (?,?,?,?,?,?,?)',
                                (reservation_id, actor, str(allowance) if allowance is not None else UNLIMITED, None, 'reserved', now, now))
            except sqlite3.IntegrityError as error:
                raise ValueError('Reservation identity already used; never replay') from error
            return float(allowance) if allowance is not None else None

    def settle(self, reservation_id, reported_usd, *, outcome_known):
        with self.transaction():
            row = self.db.execute('SELECT * FROM reservations WHERE id=?', (reservation_id,)).fetchone()
            if not row or row['status'] != 'reserved': raise ValueError('Reservation is not pending')
            capped = row['allowance'] != UNLIMITED
            try:
                cost = _money(reported_usd, positive=capped)
                known = outcome_known is True and (not capped or cost <= Decimal(row['allowance']))
            except ValueError:
                cost = None
                # Missing cost is accounting evidence, not an unknown execution.
                # With a cap it still blocks spending; uncapped runs keep going.
                known = outcome_known is True and not capped
            self.db.execute('UPDATE reservations SET status=?, cost=?, updated=? WHERE id=?',
                            ('settled' if known else 'uncertain', str(cost) if cost is not None else None,
                             time.time(), reservation_id))
            return self._snapshot()

    def abandon_before_launch(self, reservation_id):
        """Release only when the caller knows no process/thread was launched."""
        with self.transaction():
            updated = self.db.execute("UPDATE reservations SET status='not_launched', updated=? WHERE id=? AND status='reserved'",
                                      (time.time(), reservation_id)).rowcount
            if updated != 1: raise ValueError('Reservation is not pending')

    def close(self):
        with self.lock:
            self.db.close()
