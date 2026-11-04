# Access-only subscription attachments

An explicitly selected `ROBOFRONTIER_BORROWED_AUTH` may reference the configured
credential store's `current.json` when another running allocation step already
owns its native refresh lease. This permits a separately prepared physical batch
to use its own gateway and Codex home without stopping the existing batch.

The attachment uses native `chatgptAuthTokens` login and ephemeral credential
storage. Only access/account/plan fields enter that native request. It creates no
`auth.json`, does not acquire the refresh lease, does not perform custom OAuth,
and never falls back to an API key. The private canonical store and both engine
roots remain denied by every frozen policy permission table.

The original native owner alone refreshes credentials. Attachments watch the
canonical account identity and expiry. On an unauthorized native request they
wait at most eight seconds for the original owner to publish a changed access
token, then return those new access fields through the native renewal callback.
If no valid new generation is available, they fail closed rather than becoming
a competing refresh owner. If the original owner ends, existing unexpired
access can still be used; renewal is unavailable until custody is explicitly
established again. Check validity against the entire planned run before START.

This is authentication reuse, not session takeover. Fresh trials use fresh run
directories, ledgers, native sessions and physical worlds. They do not read or
replay interrupted trials' actions. Discarded trials remain identified as such
and cleanup waits for any existing collector that still owns their evidence.

Validation uses synthetic credentials and loopback provider responses with the
real pinned CLI: the original 36-task engine remains alive while an access-only
two-task engine starts roles, invokes tools, forks children and releases them.
The canonical credential owner and its cache remain unchanged by the attachment.
