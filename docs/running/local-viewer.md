# Read-only saved-run viewer

The local viewer shows a Codex or Claude batch from its saved JSON and images. It creates no
sessions, calls no model, advances no physics, opens no SQLite database and changes nothing in
the batch.

```sh
.venv/bin/python -m scripts.view_policy_batch runs/policy/my-batch
```

It prints a loopback URL (`127.0.0.1`, a free port; `--port 8088` picks one). Open it on the
same host, or through an SSH tunnel for a remote host. Ctrl-C stops the viewer, not the batch.

The page refreshes every three seconds from `batch.json`, `engineering-status.json` when present
and each run's saved `private/outputs/runtime.json`. Saved state can lag execution; the page shows
each snapshot's age and reports missing counts as missing, never as zero or as START. It does
not prove that a process is alive: use `robofrontier status` to supervise.

Each task row shows the profile, family, level, arm count, saved lifecycle, recorded completion
and the latest saved image (JPEG or PNG). An existing `private/outputs/global-realtime.mp4` is
streamed with HTTP Range requests; the viewer never records or renders one. Run directories must
stay inside the selected batch. The JSON it serves leaves out work notes, mail, connection
tokens and private evaluator details.

For Docker or Slurm runs, point it at saved or staged-out folders on the host filesystem; never
at a live container's or node's files from another filesystem namespace.
