"""Codex entry point to the shared isolated file worker."""
from robofrontier.engines.common.tool_worker import *

if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(type(error).__name__+': '+str(error), file=sys.stderr)
        raise SystemExit(126)
