"""The egress readiness record a Slurm job's relay publishes and a world reads.

The relay (roboteam/launch/slurm/proxy.py) writes the record; a world's outage pause
(egress_pause.py) reads it. Only the safe read lives here, so the runtime does not import
the launcher.
"""

import json
import os
import stat


class EgressError(RuntimeError):
    pass


def read_record(path):
    for _ in range(4):
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            info = os.fstat(stream.fileno())
            if (
                not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.getuid()
                or info.st_mode & 0o077
                or info.st_size > 16384
                or info.st_nlink > 1
            ):
                raise EgressError('Unsafe egress readiness record')
            if info.st_nlink == 0:
                # Atomic heartbeat publication can unlink the inode after open
                # but before fstat. Reopen the path; never admit that old inode.
                continue
            return json.loads(stream.read(16385))
    raise EgressError('Egress readiness record kept changing during read')
