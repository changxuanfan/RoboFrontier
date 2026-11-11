"""Stop a policy command and its descendants when its MCP owner disappears."""
import json
import os
import select
import signal
import subprocess
import sys


def main():
    lease = int(sys.argv[1])
    command = json.loads(sys.argv[2])
    # The guardian owns the lifetime pipe; the sandboxed command cannot signal
    # it and does not inherit the lifetime pipe. EOF also handles SIGKILL of
    # the MCP host, where Python finally blocks cannot run.
    child = subprocess.Popen(command, close_fds=True, process_group=0)
    try:
        while child.poll() is None:
            ready, _, _ = select.select([lease], [], [], .1)
            if ready and not os.read(lease, 1):
                break
        if child.poll() is not None:
            return child.returncode
    finally:
        os.close(lease)
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()
    return 1


if __name__ == '__main__':
    sys.exit(main())
