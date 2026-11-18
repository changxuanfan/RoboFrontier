"""Every harness serves one robot tool description (harness/shared/robot_tool.json, E2)."""
import json
import subprocess
import shutil
import unittest

from roboteam.io import ROOT
from roboteam.harness.shared import robot_mcp
from roboteam.harness.codex import desktop_robot_mcp


class RobotToolTextTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('node'), 'needs Node.js')
    def test_claude_desktop_and_codex_serve_the_same_tool(self):
        shared = json.loads((ROOT/'roboteam/harness/shared/robot_tool.json').read_text())
        self.assertEqual(robot_mcp.TOOL, shared)
        self.assertEqual(desktop_robot_mcp.TOOL, shared)
        codex = json.loads(subprocess.run(['node', '-e', "const h=require('./roboteam/harness/codex/host/policy_host.js');"
                                           "const {type,...tool}=h.robotTool;process.stdout.write(JSON.stringify(tool))"],
                                          cwd=ROOT, capture_output=True, text=True, check=True).stdout)
        self.assertEqual(codex, shared)

    def test_the_description_says_calls_run_in_order(self):
        text = json.loads((ROOT/'roboteam/harness/shared/robot_tool.json').read_text())['description']
        self.assertIn('run in order', text); self.assertIn('action_batch', text); self.assertIn('wait:false', text)


if __name__ == '__main__':
    unittest.main()
