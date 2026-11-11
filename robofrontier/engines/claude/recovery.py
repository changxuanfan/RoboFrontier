"""Claude native history adapter for the shared recovery rules and error parsers."""
from robofrontier.engines.common.session_recovery import *
from robofrontier.engines.common.session_recovery import recover as _recover, recover_network as _recover_network, _active_time
from robofrontier.engines.claude.native_home import history_directory
from robofrontier.engines.claude.provenance import history, transcript_rows


def recover(host, store, now=None):
    return _recover(host, store, now, history_available=lambda:
        bool(history(transcript_rows(history_directory(host.run), host.session_id), host.session_id)))


def recover_network(host, store, now=None):
    return _recover_network(host, store, now, active_time=_active_time)
