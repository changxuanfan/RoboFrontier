"""Opt-in real physics evaluation smoke using a local synthetic policy."""
import hashlib
import http.server
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading
import unittest

from test_claude_adaptive_integration import StubModel
from robofrontier.engines.claude.run import run_engineering
from robofrontier.batch.claude_benchmark import prepare_draft
from robofrontier.batch.report import export


class FinishModel(StubModel):
    requests=[]
    def choose_tool(self,names,text,blocks,has_result):
        # This synthetic policy always proposes an early finish on its first
        # tool-enabled request. Do not depend on the CLI's prompt serialization.
        if names and not has_result:
            return {'op':'finish','data':{'note':'synthetic early finish'}},'toolu_finish'
        return super().choose_tool(names,text,blocks,has_result)


@unittest.skipUnless(os.environ.get('ROBOFRONTIER_PHYSICS_FINISH')=='1' and shutil.which('claude'),
                     'Opt-in physics finish smoke requires Claude CLI and scene assets')
class FinishPhysicsSmokeTests(unittest.TestCase):
    def test_early_finish_produces_failed_evaluation_and_report(self):
        directory=Path(tempfile.mkdtemp(prefix='claude-finish-physics-'))
        server=http.server.ThreadingHTTPServer(('127.0.0.1',0),FinishModel)
        threading.Thread(target=server.serve_forever,daemon=True).start()
        result=None; passed=False
        FinishModel.requests.clear()
        try:
            batch=directory/'batch'; case='transport-a04-d1'
            prepare_draft(batch,['opus'],cases=[case],topology='centralized')
            run=batch/'opus'/case
            launch=run/'private/inputs/claude.json'; data=json.loads(launch.read_text())
            data['profile'].update(base_url=f'http://127.0.0.1:{server.server_port}',env_key='FAKE_KEY')
            launch.write_text(json.dumps(data))
            manifest=run/'private/inputs/manifest.json'; frozen=json.loads(manifest.read_text())
            frozen['input_sha256']['private/inputs/claude.json']=hashlib.sha256(launch.read_bytes()).hexdigest()
            manifest.write_text(json.dumps(frozen))
            env={'PATH':os.environ['PATH'],'HOME':os.environ['HOME'],'FAKE_KEY':'synthetic'}
            result=run_engineering(run,env,turn_budget_usd=.5,total_budget_usd=2,wall_limit_s=30,poll_s=.1)
            self.assertEqual(result['status'],'finished',result)
            request_tools = [b.get('input', {}).get('op') for req in FinishModel.requests
                             for msg in req.get('messages', []) if msg.get('role') == 'assistant'
                             for b in (msg.get('content') or []) if isinstance(b, dict) and b.get('type') == 'tool_use']
            self.assertEqual(result['reason'],'world_ended',{'result':result, 'ops':request_tools,
                'requests':[(bool(r.get('tools')),str(r.get('messages',[])[-1].get('content',''))[-900:])
                            for r in FinishModel.requests[-3:]], 'retained':str(directory)})
            self.assertTrue(result['seal']['sealed'],result)
            self.assertFalse(result['owner_alive'],result)
            evaluation=json.loads((run/'private/outputs/evaluation.json').read_text())
            self.assertFalse(evaluation['task_success'],evaluation)
            report=export(run)
            self.assertEqual(report['lifecycle'],'ended')
            self.assertEqual(report['evaluation'],evaluation)
            self.assertEqual(report['engine'],'claude')
            self.assertFalse(report['benchmark_qualified'])
            self.assertIn('not qualified for formal benchmark scoring',(run/'private/outputs/report.md').read_text())
            self.assertFalse(report['all_requested_models_verified'])
            self.assertEqual(report['changed_inputs'],[])
            passed=True
        finally:
            server.shutdown();server.server_close()
            if passed and result and not result.get('owner_alive'): shutil.rmtree(directory)
            else: print('Uncertain finish smoke retained for review:',directory)


if __name__=='__main__': unittest.main()
