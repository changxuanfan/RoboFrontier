"""Claude native history adapter for the shared recovery rules and error parsers."""

from roboteam.harness.claude.session.native_home import history_directory
from roboteam.harness.claude.session.session_recovery import recover as _recover
from roboteam.harness.claude.systems.provenance import history, transcript_rows


def recover(host, store, now=None):
    return _recover(
        host,
        store,
        now,
        history_available=lambda: bool(
            history(transcript_rows(history_directory(host.run), host.session_id), host.session_id)
        ),
    )
