# Read-only saved-run viewer

The optional local viewer displays existing Codex or Claude batch metadata and
saved observations. It does not create sessions, call models, advance physics,
open SQLite databases or modify the selected run.

```sh
.venv/bin/python -m scripts.view_policy_batch runs/policy/my-batch
```

The command prints a loopback URL with an automatically selected port. Open that
URL on the same host, or use an SSH tunnel for a remote host. `--port 8088` chooses
a specific local port. Stop the viewer with Ctrl-C; this does not stop the batch.

The page refreshes every three seconds from `batch.json`, an existing
`engineering-status.json` and saved per-task `private/state/runtime.json`
snapshots. Saved state can lag behind execution. Snapshot age is displayed;
missing counts and lifecycle information are reported as missing, not fabricated
as zero or inferred as START. The page does not prove that an owner process is
currently alive. Use the unified lifecycle/status commands for supervision.

Task rows show the model profile, family, level, arm count, saved lifecycle,
recorded completion flag and latest available image. JPEG and PNG are served with
their respective MIME types. The viewer can stream an already-recorded real-time
video with HTTP Range requests, but does not create one or render motion.
Real-time video remains disabled by default.

Current `jobs` batches and legacy `cases` batches are accepted. Run directories
must remain inside the selected batch; an artifact with stale absolute paths
must be restored through the supported evidence workflow. Repeated case IDs
across profiles use separate row keys; ambiguous bare case-ID requests are
rejected. The JSON response excludes work notes, mail, connection tokens and
private evaluator details.

For container or Slurm runs, view saved/staged JSON and images within their
existing filesystem layout. Do not directly open a live container's SQLite
database from another filesystem namespace. No SQLite workaround is required
by this viewer because it never opens one.
