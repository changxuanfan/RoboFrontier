"""Codex entry point to the shared isolated file worker."""

import sys

from roboteam.harness.shared.tool_worker import main

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr)
        raise SystemExit(126)
