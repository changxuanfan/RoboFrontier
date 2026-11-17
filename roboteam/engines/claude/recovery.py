"""Claude native history adapter for the shared recovery rules and error parsers."""
from roboteam.engines.common.session_recovery import *
from roboteam.engines.common.session_recovery import recover as _recover
from roboteam.engines.claude.native_home import history_directory
from roboteam.engines.claude.provenance import history, transcript_rows


def recover(host, store, now=None):
    return _recover(host, store, now, history_available=lambda:
        bool(history(transcript_rows(history_directory(host.run), host.session_id), host.session_id)))
