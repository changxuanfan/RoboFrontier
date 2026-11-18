# Sharing a Codex login on Slurm

A Codex subscription job on Slurm keeps its ChatGPT login in a credential store and is the only
process that renews it ([Slurm credential store](../hosts/slurm.md#codex-credential-store)). A
second Codex subscription batch can use the access token of a job that is already running,
without stopping that job and without renewing the login itself. This is called an
*access-only attachment*.

To use it, set `ROBOTEAM_BORROWED_AUTH` in the second batch's environment to the store's
`current.json` (`<slurm.credential_store>/current.json`; any other path is refused). The
running job keeps its own lock on the store.

What the attachment does:

- It logs Codex in with `chatgptAuthTokens` and storage that is not kept, passing only the
  access, account and plan fields. It writes no `auth.json`, takes no lock on the store, runs no
  sign-in of its own and never falls back to an API key.
- It watches the store's account identity and expiry. On an unauthorized response it waits up
  to eight seconds for the owning job to publish a new access token and passes that on. Without
  one it fails closed.
- If the owning job ends, unexpired access still works but cannot be renewed. Check that the
  access lasts the whole planned run before START.

The store and both harnesses' home folders stay closed to the agents in every run's access
table. The second batch has its own runs, records, sessions and worlds; it reads nothing from
the first.

Tests: `tests/launch/test_slurm_auth.py`, `tests/harness/codex/test_codex_borrowed_auth.js` and
`tests/harness/codex/test_slurm_gateway_native.py`, the last with the real pinned CLI, synthetic
credentials and a loopback provider.
