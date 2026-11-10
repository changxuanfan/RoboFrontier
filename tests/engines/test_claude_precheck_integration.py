"""Real CLI precheck with local synthetic inference; no real provider calls."""
import http.server
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch

from robofrontier.engines.claude import preflight as claude_precheck
from robofrontier.engines.claude.runner import build_command,build_env
from engines.test_claude_adaptive_integration import StubModel


class PrecheckModel(StubModel):
    requests = []
    auth_headers = []
    def do_POST(self):
        # Record presence only, never the synthetic credential itself.
        self.auth_headers.append({'x_api_key': bool(self.headers.get('x-api-key')),
                                  'bearer': self.headers.get('Authorization', '').startswith('Bearer ')})
        super().do_POST()
    def reply_text(self, body, text, blocks):
        return 'READY' if not any('Without calling' in str(m.get('content','')) or
                                  'Call the robot tool once' in str(m.get('content',''))
                                  for m in body.get('messages',[])) else 'green red'
    def choose_tool(self, names, text, blocks, has_result):
        if names and not has_result and 'Call the robot tool once' in text:
            return {'op':'observe','data':{},'views':['top']}, 'toolu_precheck_image'
        return None, None


@unittest.skipUnless(shutil.which('claude'), 'Claude CLI is not installed')
class PrecheckIntegrationTests(unittest.TestCase):
    def test_native_budget_is_per_invocation_while_cost_report_is_cumulative(self):
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),PrecheckModel)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);home=root/'native';home.mkdir()
                selected={'model':'claude-opus-5-5','effort':'high','env_key':'FAKE_KEY',
                          'base_url':f'http://127.0.0.1:{server.server_port}'}
                env=build_env(selected,{'PATH':os.environ['PATH'],'FAKE_KEY':'synthetic'},home)
                sid=str(uuid.uuid4());totals=[]
                for first in (True,False):
                    command=build_command(selected['model'],'high',None,'Reply READY',
                        session_id=sid if first else None,resume=None if first else sid,
                        enable_robot=False,max_budget_usd=.00013)
                    result=subprocess.run(command,cwd=root,env=env,stdin=subprocess.DEVNULL,
                                          capture_output=True,text=True,timeout=20)
                    self.assertEqual(result.returncode,0,result.stderr)
                    rows=[json.loads(line) for line in result.stdout.splitlines()]
                    final=next(row for row in reversed(rows) if row.get('type')=='result')
                    self.assertFalse(final.get('is_error'),final)
                    totals.append(final['total_cost_usd'])
                self.assertLess(totals[0],.00013)
                self.assertGreater(totals[1],.00013)
        finally:
            server.shutdown();server.server_close()

    def setUp(self):
        color=patch.object(claude_precheck.preflight_probe,'choose',return_value=('green','red'))
        color.start(); self.addCleanup(color.stop)
    def test_precheck_with_native_idle_fork_and_local_fake_provider(self):
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),PrecheckModel)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        PrecheckModel.requests.clear()
        PrecheckModel.auth_headers.clear()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                profile={'model':'claude-opus-5-5','effort':'high','env_key':'FAKE_KEY',
                         'base_url':f'http://127.0.0.1:{server.server_port}'}
                env={'PATH':os.environ['PATH'],'FAKE_KEY':'synthetic'}
                with patch.object(claude_precheck,'profile',return_value=profile):
                    result=claude_precheck.run_precheck('synthetic',Path(tmp)/'out',2,env,check_fork=True)
                self.assertTrue(result['passed'],result)
                self.assertEqual([x['name'] for x in result['checks']],['text','tool_image','resume','fork'])
                self.assertTrue(result['checks'][-1]['checks']['native_history_prefix'])
                self.assertTrue(any(not req.get('tools') for req in PrecheckModel.requests))
                self.assertTrue(PrecheckModel.auth_headers)
                self.assertTrue(all(h['x_api_key'] and not h['bearer'] for h in PrecheckModel.auth_headers))
                # The native fork carries the parent's complete cost history.
                # Summed new work must equal that final cumulative counter,
                # rather than charging inherited usage once per invocation.
                events=Path(tmp)/'out/run/private/evidence/fork.jsonl'
                native=[json.loads(line) for line in events.read_text().splitlines()]
                total=next(row['total_cost_usd'] for row in reversed(native) if row.get('type')=='result')
                self.assertAlmostEqual(result['total_cost_usd'],total,places=10)
        finally:
            server.shutdown();server.server_close()


if __name__=='__main__': unittest.main()
