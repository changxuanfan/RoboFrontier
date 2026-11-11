# Access-only Codex subscription attachments

On Slurm, a second Codex subscription batch can use the login of a job that is already running,
without stopping it and without becoming a second refresh owner. Set
`ROBOFRONTIER_BORROWED_AUTH` to the configured credential store's `current.json`
(`<slurm.credential_store>/current.json`; any other path is refused) in the second batch's
environment. The running job keeps its own lease on the store
([Slurm credential store](slurm.md#codex-credential-store)).

What the attachment does:

- It logs native Codex in with `chatgptAuthTokens` and ephemeral storage, passing only the
  access, account and plan fields. It writes no `auth.json`, takes no lease, runs no OAuth of
  its own and never falls back to an API key.
- It watches the store's account identity and expiry. On an unauthorized response it waits up
  to eight seconds for the owning job to publish a new access token and passes that on. Without
  one it fails closed.
- If the owning job ends, unexpired access still works but cannot be renewed. Check that the
  access lasts the whole planned run before START.

The store and both engine homes stay closed in every run's access table. The second batch has
its own runs, ledgers, sessions and worlds; it reads nothing from the first.

Tests: `tests/batch/test_slurm_auth.py`, `tests/engines/test_codex_borrowed_auth.js` and
`tests/engines/test_slurm_gateway_native.py`, the last with the real pinned CLI, synthetic
credentials and a loopback provider.
