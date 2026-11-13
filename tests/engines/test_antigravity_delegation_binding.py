"""Native SQLite tool boundaries qualify a fork; parallel tails never do."""
import json
from pathlib import Path
import tempfile
import unittest
import uuid
from unittest.mock import Mock, patch

from robofrontier.engines.antigravity.robot_mcp import Router, binding_path
from robofrontier.engines.common.robot_mcp import DelegationBindingError, RobotBridge
from tests.engines.test_antigravity_accounting import history, tool_metadata


class BindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.run = Path(self.tmp.name)/'run'
        self.home = Path(self.tmp.name)/'native'
        self.session, self.trajectory = str(uuid.uuid4()), str(uuid.uuid4())
        self.args = {'op': 'delegate', 'data': {'scopes': [{'robots': ['Robot_1'], 'goal': 'synthetic', 'done_when': 'synthetic'}]}}
        self.router = Router.__new__(Router)
        self.router.run = self.run
        path = self.run/'private/inputs/antigravity.json'
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({'native_home':str(self.home)}))

    def native(self, tail=False, status=2):
        rows = [(14,3,b'input',b'm0'), (15,3,b'plan',b'm1'),
                (132,status,b'tool',tool_metadata('delegate-call','mcp_robofrontier_robot',
                                               {**self.args,'toolSummary':'Delegate'}))]
        if tail:
            rows.append((132,2,b'parallel',tool_metadata('other-call','mcp_robofrontier_policy_image',{})))
        history(self.home,self.session,rows)

    def bind(self, args=None):
        self.router.bind(self.run,'Controller',args or self.args,'batch',
                         session=self.session,progress=self.trajectory+':2')

    def test_exclusive_pending_step_keeps_verified_identity(self):
        self.native()
        self.bind()
        saved=json.loads(binding_path(self.run,'batch').read_text())
        self.assertEqual((saved['step'],saved['tool_id'],saved['session_id']), (2,'delegate-call',self.session))

    def test_parallel_tail_is_immediately_rejected_with_recovery_hint(self):
        self.native(tail=True)
        with patch('robofrontier.engines.antigravity.robot_mcp.time.sleep') as sleep:
            with self.assertRaises(DelegationBindingError) as caught:
                self.bind()
        self.assertEqual(caught.exception.code,'DELEGATE_REQUIRES_EXCLUSIVE_STEP')
        self.assertIn('delegate alone',caught.exception.note)
        sleep.assert_not_called()
        self.assertFalse(binding_path(self.run,'batch').exists())

    def test_parallel_tail_does_not_mask_wrong_arguments(self):
        self.native(tail=True)
        with self.assertRaisesRegex(ValueError,'parameters differ') as caught:
            self.bind({'op':'delegate','data':{'scopes':[]}})
        self.assertNotIsInstance(caught.exception,DelegationBindingError)

    def test_completed_call_cannot_be_bound(self):
        self.native(status=3)
        with self.assertRaisesRegex(ValueError,'not pending'):
            self.bind()

    def test_bridge_rejection_never_submits_a_runtime_delegation(self):
        self.native(tail=True)
        connection=self.run/'private/state/connections/Controller.json'
        connection.parent.mkdir(parents=True)
        connection.write_text(json.dumps({'run_id':'run','actor':'Controller'}))
        invoke=Mock()
        bridge=RobotBridge(self.run,connection,invoke,bind_delegation=lambda *args:self.bind())
        result=bridge.call(self.args)
        value=json.loads(result['content'][0]['text'])
        self.assertEqual((value['error_code'],value['execution_status']),
                         ('DELEGATE_REQUIRES_EXCLUSIVE_STEP','not_submitted'))
        invoke.assert_not_called()


if __name__=='__main__':
    unittest.main()
