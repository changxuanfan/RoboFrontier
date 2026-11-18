"""Claude role binding around the shared robot MCP implementation."""

import argparse
from pathlib import Path

from roboteam.harness.claude.systems.request_identity import bind_delegate
from roboteam.harness.shared.robot_mcp import RobotBridge as SharedRobotBridge
from roboteam.harness.shared.robot_mcp import serve
from roboteam.runtime.tools.pipeline_client import client_call


class RobotBridge(SharedRobotBridge):
    def __init__(self, run, connection, invoke=client_call):
        super().__init__(run, connection, invoke, bind_delegation=bind_delegate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-dir', type=Path, required=True)
    parser.add_argument('--connection', type=Path, required=True)
    args = parser.parse_args()
    serve(RobotBridge(args.run_dir, args.connection))


if __name__ == '__main__':
    main()
