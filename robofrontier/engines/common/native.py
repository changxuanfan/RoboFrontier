"""Shared native transport lifecycle errors."""

class PreLaunchCancelled(InterruptedError):
    """Cancellation was observed before a CLI subprocess was created."""
