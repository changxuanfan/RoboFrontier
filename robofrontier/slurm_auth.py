"""Private, serialized custody of native-managed Codex credentials.

No OAuth client, login, model call or scheduler submission lives here. The
operator provisions auth.json once in a private directory outside the checkout.
Only the native app-server refreshes it. current.json is an atomic generation
containing the latest cache; an old bootstrap file never overrides that state.
The site's shared filesystem must support flock and atomic rename durably.
"""
import base64
import fcntl
import json
import os
from pathlib import Path
import stat
import shutil
import tempfile
import threading
import time


class CredentialError(RuntimeError):
    """Messages deliberately contain no native response or credential content."""


def _private_directory(path):
    path = Path(path).absolute()
    if path.is_symlink() or path.resolve() != path:
        raise CredentialError('Credential directories must not traverse symlinks')
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise CredentialError('Credential directory must be owned by this user with mode 0700')
    return path


def _read_private(path):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise CredentialError('Credential file must be private, regular and unlinked')
            value = stream.read(1_048_577)
            if len(value) > 1_048_576:
                raise CredentialError('Credential file exceeds the size limit')
            return value
    except OSError:
        raise CredentialError('Cannot read private credential file') from None


def _decode(data):
    try:
        return json.loads(data)
    except (ValueError, UnicodeError):
        raise CredentialError('Incomplete or invalid native credential cache') from None


def credential_owner(auth):
    """Bind a native cache to its account and subject, without logging tokens.

    JWT decoding here establishes consistency with the provisioned seed only;
    provider authentication, not this decoder, establishes token validity.
    """
    try:
        if auth.get('auth_mode') != 'chatgpt' or auth.get('OPENAI_API_KEY'):
            raise ValueError()
        tokens = auth['tokens']
        if any(not isinstance(tokens[k], str) or not tokens[k] for k in
               ('id_token', 'access_token', 'refresh_token', 'account_id')):
            raise ValueError()
        encoded = tokens['id_token'].split('.')[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4)))
        subject = claims['sub']
        account = claims.get('https://api.openai.com/auth', {}).get('chatgpt_account_id')
        if not isinstance(subject, str) or not subject or (account and account != tokens['account_id']):
            raise ValueError()
        return {'account_id': tokens['account_id'], 'subject': subject}
    except (AttributeError, KeyError, IndexError, TypeError, ValueError, UnicodeError):
        raise CredentialError('A valid managed ChatGPT credential cache is required') from None


def _atomic_private(path, value):
    data = json.dumps(value, sort_keys=True, allow_nan=False).encode() + b'\n'
    fd, temporary = tempfile.mkstemp(prefix='.credential-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def migrate_store(source, destination):
    """Move a stopped, initialized stream under both exclusive refresh locks.

    The old initialized marker remains, so even older runners refuse to reload
    its obsolete bootstrap. Only the latest generation crosses to the new store.
    No native cache, login, refresh or account request is performed here.
    """
    source = _private_directory(source)
    destination = Path(destination).absolute()
    if destination.resolve() != destination or destination.exists():
        raise CredentialError('Migration destination must be a new canonical directory')
    _private_directory(destination.parent)
    retired = False
    created = False
    fd = os.open(source/'lease.lock', os.O_RDWR | os.O_NOFOLLOW)
    with os.fdopen(fd, 'rb') as old_lock:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077 or info.st_nlink != 1):
            raise CredentialError('Unsafe credential migration lease')
        try:
            fcntl.flock(old_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise CredentialError('Credential stream is already leased; migration refused') from None
        current = _decode(_read_private(source/'current.json'))
        if (current.get('schema') != 'robofrontier.codex-auth.v1'
                or type(current.get('generation')) is not int or current['generation'] < 1
                or credential_owner(current.get('auth')) != current.get('owner')
                or not (source/'initialized.json').exists()):
            raise CredentialError('Migration requires a valid initialized canonical generation')
        try:
            destination.mkdir(mode=0o700); created = True
            with (destination/'lease.lock').open('xb') as new_lock:
                os.chmod(new_lock.name, 0o600)
                fcntl.flock(new_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                _atomic_private(destination/'initialized.json', {'schema':'robofrontier.codex-auth-initialized.v1'})
                _atomic_private(destination/'current.json', current)
                if (_decode(_read_private(destination/'current.json')) != current
                        or _decode(_read_private(source/'current.json')) != current):
                    raise CredentialError('Credential generation changed during migration')
                (source/'current.json').unlink(); retired = True
                (source/'auth.json').unlink(missing_ok=True)
                fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY)
                try: os.fsync(fd)
                finally: os.close(fd)
        except BaseException:
            # After retirement, retain the verified durable generation. Never
            # restore the old source or create two future refresh authorities.
            if created and not retired: shutil.rmtree(destination)
            raise
    return {'source':str(source), 'destination':str(destination),
            'generation':current['generation'], 'source_retired':retired,
            'native_refreshes':0}


class CredentialLease:
    """Own one refresh stream until the native server has closed and saved.

    A failed checkpoint stops admission/dispatch through on_failure. A final
    invalid/truncated cache fails closure rather than restoring an old seed.
    Hard node loss between native rotation and persistence still needs manual
    reauthentication; no filesystem watcher can make those two events atomic.
    """
    def __init__(self, store, home):
        self.store = Path(store).absolute()
        self.home = Path(home).absolute()
        self.lock = None
        self.error = None
        self.stop = threading.Event()
        self.watcher = None

    def __enter__(self):
        _private_directory(self.store)
        try:
            fd = os.open(self.store/'lease.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
            self.lock = os.fdopen(fd, 'rb')
            info = os.fstat(self.lock.fileno())
            if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                    or info.st_mode & 0o077 or info.st_nlink != 1):
                raise CredentialError('Unsafe credential stream lease file')
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise CredentialError('Credential stream is already leased; no concurrent refresh owners') from None
            state = self.store/'current.json'
            if os.path.lexists(state):
                current = _decode(_read_private(state))
                if (not isinstance(current, dict) or current.get('schema') != 'robofrontier.codex-auth.v1'
                        or type(current.get('generation')) is not int or current['generation'] < 1
                        or credential_owner(current.get('auth')) != current.get('owner')):
                    raise CredentialError('Invalid persisted credential generation')
                self.current = current
            else:
                if os.path.lexists(self.store/'initialized.json'):
                    raise CredentialError('Persisted credential generation is missing; never restore the old bootstrap seed')
                auth = _decode(_read_private(self.store/'auth.json'))
                self.current = {'schema': 'robofrontier.codex-auth.v1', 'generation': 1,
                                'owner': credential_owner(auth), 'auth': auth}
                _atomic_private(self.store/'initialized.json', {'schema': 'robofrontier.codex-auth-initialized.v1'})
                _atomic_private(state, self.current)
            self.home.mkdir(mode=0o700, parents=True, exist_ok=False)
            _private_directory(self.home)
            _atomic_private(self.home/'auth.json', self.current['auth'])
            return self
        except BaseException:
            self._unlock()
            raise

    def reconcile(self, *, final=False):
        try:
            auth = _decode(_read_private(self.home/'auth.json'))
        except CredentialError:
            if final:
                raise
            return False  # Native storage may be between truncate and write.
        if credential_owner(auth) != self.current['owner']:
            raise CredentialError('Native credential owner changed; stream fenced')
        # Even while holding the lease, reject unexpected store replacement.
        persisted = _decode(_read_private(self.store/'current.json'))
        if persisted != self.current:
            raise CredentialError('Credential generation changed outside its lease; stream fenced')
        if auth == self.current['auth']:
            return False
        current = {**self.current, 'generation': self.current['generation'] + 1, 'auth': auth}
        _atomic_private(self.store/'current.json', current)
        self.current = current
        return True

    def watch(self, on_failure, *, interval_s=1):
        if self.watcher is not None:
            raise CredentialError('Credential watcher already started')
        def work():
            while not self.stop.wait(interval_s):
                try:
                    self.reconcile()
                except Exception:
                    self.error = CredentialError('Credential persistence failed; stop and inspect the private store')
                    on_failure()
                    return
        self.watcher = threading.Thread(target=work, name='codex-credential-custody', daemon=True)
        self.watcher.start()

    def _unlock(self):
        if self.lock is not None:
            self.lock.close()
            self.lock = None

    def __exit__(self, kind, value, traceback):
        # The caller must first close all native credential writers.
        self.stop.set()
        if self.watcher:
            self.watcher.join()
        try:
            if self.error:
                raise self.error
            self.reconcile(final=True)
        finally:
            self._unlock()


class BorrowedAccess(CredentialLease):
    """Read-only access stream; the existing native lease remains the refresh owner.

    A separate native server uses ephemeral chatgptAuthTokens authentication.
    It receives access/account/plan only, never this store's refresh token. The
    original native owner publishes renewed generations into the canonical file.
    """
    def __enter__(self):
        _private_directory(self.store)
        self.current = None
        self.reconcile()
        self.home.mkdir(mode=0o700, parents=True, exist_ok=False)
        _private_directory(self.home)
        return self

    def reconcile(self, *, final=False):
        current = _decode(_read_private(self.store/'current.json'))
        if (not isinstance(current, dict) or current.get('schema') != 'robofrontier.codex-auth.v1'
                or type(current.get('generation')) is not int or current['generation'] < 1
                or credential_owner(current.get('auth')) != current.get('owner')):
            raise CredentialError('Invalid canonical access generation')
        if self.current and current['owner'] != self.current['owner']:
            raise CredentialError('Borrowed credential owner changed')
        try:
            encoded = current['auth']['tokens']['access_token'].split('.')[1]
            claims = json.loads(base64.urlsafe_b64decode(encoded+'='*(-len(encoded)%4)))
            if claims['exp'] <= time.time()+30: raise ValueError()
        except (ValueError, KeyError, TypeError, IndexError):
            raise CredentialError('Canonical access expired or malformed') from None
        if (self.home/'auth.json').exists():
            raise CredentialError('An access-only native server unexpectedly wrote credentials')
        changed = current != self.current
        self.current = current
        return changed

    def __exit__(self, kind, value, traceback):
        self.stop.set()
        if self.watcher: self.watcher.join()
        if self.error: raise self.error
        self.reconcile(final=True)
