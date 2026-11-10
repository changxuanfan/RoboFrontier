import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from robofrontier.engines.claude.run import run_task


class Store:
    def __init__(self, attached=False): self.attached = attached
    def get(self, key): return self.attached if key == 'execution_owner_attached' else None


class Policy:
    def __init__(self, *args, **kwargs): self.store = Store(); self.closed = False
    def close(self): self.closed = True


class Owner:
    pid = 1234
    def __init__(self, status): self.status = status
    def poll(self): return self.status


class RunTaskTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.run = Path(self.tmp.name) / 'run'
        for directory in ('private/inputs', 'private/outputs', 'private/state/connections', 'public/inputs'):
            (self.run / directory).mkdir(parents=True)
        (self.run / 'public/inputs/roles.json').write_text(json.dumps({'roles': {
            'Meta': {'kind': 'manager'}, 'Controller': {'kind': 'controller', 'robots': ['A1', 'A2']}}}))
        (self.run / 'private/inputs/claude.json').write_text(json.dumps({
            'schema': 'robofrontier.claude-launch.v2',
            'profile': {'env_key': 'FAKE_KEY', 'model': 'fake', 'effort': 'high'}}))
        (self.run / 'private/inputs/manifest.json').write_text(json.dumps({
            'status': 'prepared', 'engine': 'claude'}))
        (self.run / 'private/inputs/harness.json').write_text(json.dumps({'engine':'claude','topology':'centralized'}))
        (self.run / 'private/state/connections/Meta.json').write_text('{}')
        self.env = {'FAKE_KEY': 'secret', 'PATH': '/bin'}
        self.verify = patch('robofrontier.engines.claude.run.verify_inputs', return_value=[])
        self.verify.start()

    def tearDown(self): self.verify.stop(); self.tmp.cleanup()

    def run_case(self, **kwargs):
        return run_task(self.run, self.env, turn_budget_usd=.5, total_budget_usd=2, wall_limit_s=30,
                               policy_factory=Policy, **kwargs)

    def test_owner_failure_consumes_claim_and_prevents_replay(self):
        observed = []
        def create(*args, **kwargs):
            observed.append(kwargs['env']); return Owner(1)
        result = self.run_case(owner_factory=create)
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(result['reason'], 'launch_error')
        self.assertNotIn('FAKE_KEY', observed[0])
        status = (self.run / 'private/outputs/claude-engineering-status.json').read_text()
        with self.assertRaisesRegex(ValueError, 'never restart'):
            self.run_case(owner_factory=create)
        self.assertEqual(status, (self.run / 'private/outputs/claude-engineering-status.json').read_text())
        self.assertEqual(len(observed), 1)

    def test_stop_and_an_unprepared_run_fail_before_owner_or_claim(self):
        (self.run/'STOP').touch()
        with self.assertRaisesRegex(ValueError, 'stopped'):
            self.run_case(owner_factory=lambda *a, **k: self.fail('must not start'))
        self.assertFalse((self.run/'private/state/claude-engineering-claim.json').exists())
        (self.run/'STOP').unlink()
        path = self.run/'private/inputs/claude.json'; data = json.loads(path.read_text()); data['schema'] = 'other'
        path.write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, 'prepared for Claude'):
            self.run_case(owner_factory=lambda *a, **k: self.fail('must not start'))

    def test_ready_owner_delegates_to_supervisor_and_records_seal(self):
        class Attached(Policy):
            def __init__(self, *a, **k): super().__init__(*a, **k); self.store.attached = True
        (self.run/'private/state/connections/Meta.json').write_text('{"url":"http://127.0.0.1:1234"}')
        class Supervisor:
            def __init__(self, policy, owner_alive, **kwargs): self.owner_alive = owner_alive
            def run(self):
                assert self.owner_alive()
                return {'reason': 'world_ended', 'seal': {'sealed': True}}
        with patch('robofrontier.engines.claude.run.CentralizedSupervisor', Supervisor):
            result = run_task(self.run, self.env, turn_budget_usd=.5, total_budget_usd=2, wall_limit_s=30,
                                     policy_factory=Attached, owner_factory=lambda *a, **k: Owner(None))
        self.assertEqual(result['status'], 'needs_review')
        self.assertFalse(result['scored'])
        self.assertTrue(result['owner_alive'])  # live owner is recorded, never killed implicitly

    def test_standing_launch_creates_one_run_ledger_before_world(self):
        for topology in ('hierarchical', 'peer'):
            with self.subTest(topology=topology), tempfile.TemporaryDirectory() as tmp:
                import shutil
                run = Path(tmp)/'run'; shutil.copytree(self.run, run)
                (run/'private/inputs/harness.json').write_text(json.dumps({
                    'engine':'claude','topology':topology,'startup_protocol':'direct_team_v3'}))
                seen = []
                def standing(run, profile, env, ledger, **kwargs):
                    seen.append((ledger.snapshot()['limit_usd'], kwargs))
                    return Policy()
                result = run_task(run, self.env, turn_budget_usd=.5, total_budget_usd=2,
                    standing_policy_factory=standing, owner_factory=lambda *a, **k: Owner(1))
                self.assertEqual(result['status'], 'needs_review')
                self.assertEqual(seen, [('2', {'turn_budget_usd':.5})])
                self.assertTrue((run/'private/state/claude-budget.sqlite').is_file())

    def test_adaptive_launch_creates_shared_run_budget_before_world(self):
        (self.run/'private/inputs/harness.json').write_text(json.dumps({'engine':'claude','topology':'adaptive'}))
        seen = []
        def adaptive(run, profile, env, ledger, **kwargs):
            seen.append((ledger.snapshot()['limit_usd'], kwargs))
            return Policy()
        result = run_task(self.run, self.env, turn_budget_usd=.5, total_budget_usd=2, wall_limit_s=30,
                                 adaptive_policy_factory=adaptive, owner_factory=lambda *a, **k: Owner(1))
        self.assertEqual(result['status'], 'needs_review')
        self.assertEqual(seen[0][0], '2')
        self.assertEqual(seen[0][1], {'turn_budget_usd': .5})
        self.assertTrue((self.run/'private/state/claude-budget.sqlite').exists())

    def test_default_adaptive_launch_has_an_uncapped_shared_ledger(self):
        (self.run/'private/inputs/harness.json').write_text(json.dumps({'engine':'claude','topology':'adaptive'}))
        seen = []
        def adaptive(run, profile, env, ledger, **kwargs):
            seen.append((ledger.snapshot(), kwargs))
            return Policy()
        run_task(self.run, self.env, adaptive_policy_factory=adaptive,
                        owner_factory=lambda *a, **k: Owner(1))
        self.assertEqual(len(seen), 1)
        self.assertIsNone(seen[0][0]['limit_usd'])
        self.assertIsNone(seen[0][1]['turn_budget_usd'])
        self.assertNotIn('setup_budget_usd', seen[0][1])

    def test_uncertain_shared_budget_requires_review_even_when_world_sealed(self):
        (self.run/'private/inputs/harness.json').write_text(json.dumps({'engine':'claude','topology':'adaptive'}))
        (self.run/'private/state/connections/Meta.json').write_text('{"url":"http://127.0.0.1:1234"}')
        def adaptive(run, profile, env, ledger, **kwargs):
            ledger.reserve('interrupted-turn','Controller',.5)
            ledger.settle('interrupted-turn',None,outcome_known=False)
            policy=Policy(); policy.store.attached=True
            return policy
        class ExitingOwner(Owner):
            def wait(self,timeout): self.status=0
        class Supervisor:
            def __init__(self,*a,**k): pass
            def run(self): return {'reason':'wall_limit','seal':{'sealed':True,'unresolved_action_ids':[]}}
        with patch('robofrontier.engines.claude.run.CentralizedSupervisor',Supervisor):
            result=run_task(self.run,self.env,turn_budget_usd=.5,total_budget_usd=2,wall_limit_s=30,
                                   adaptive_policy_factory=adaptive,owner_factory=lambda *a,**k: ExitingOwner(None))
        self.assertTrue(result['seal']['sealed'])
        self.assertFalse(result['owner_alive'])
        self.assertEqual(result['budget_status'],'uncertain')
        self.assertTrue(result['budget_review_required'])
        self.assertEqual(result['status'],'needs_review')

    def test_requested_unreadable_recording_requires_review_even_after_seal(self):
        config = self.run/'private/inputs/harness.json'
        config.write_text(json.dumps({'engine':'claude','topology':'centralized','record_realtime_video':True}))
        (self.run/'private/state/connections/Meta.json').write_text('{"url":"http://127.0.0.1:1234"}')
        class Attached(Policy):
            def __init__(self,*a,**k): super().__init__(*a,**k); self.store.attached = True
        class ExitingOwner(Owner):
            def wait(self,timeout): self.status=0
        class Supervisor:
            def __init__(self,*a,**k): pass
            def run(self): return {'reason':'world_ended','seal':{'sealed':True,'video':{'readable':False}}}
        with patch('robofrontier.engines.claude.run.CentralizedSupervisor', Supervisor):
            result=run_task(self.run,self.env,turn_budget_usd=.5,total_budget_usd=2,wall_limit_s=30,
                                   policy_factory=Attached,owner_factory=lambda *a,**k: ExitingOwner(None))
        self.assertTrue(result['video_required'])
        self.assertFalse(result['owner_alive'])
        self.assertEqual(result['status'],'needs_review')

    def test_seal_needs_explicit_empty_unresolved_actions(self):
        for unresolved, expected in (([], 'finished'), (['action-1'], 'needs_review'), (None, 'needs_review')):
            with self.subTest(unresolved=unresolved), tempfile.TemporaryDirectory() as tmp:
                run = Path(tmp)/'run'
                import shutil
                shutil.copytree(self.run, run)
                (run/'private/outputs/evaluation.json').write_text('{"task_success":false}')
                (run/'private/state/connections/Meta.json').write_text('{"url":"http://127.0.0.1:1234"}')
                class Attached(Policy):
                    def __init__(self,*a,**k): super().__init__(*a,**k); self.store.attached = True
                class ExitingOwner(Owner):
                    def wait(self,timeout): self.status=0
                class Supervisor:
                    def __init__(self,*a,**k): pass
                    def run(self):
                        seal={'sealed':True}
                        if unresolved is not None: seal['unresolved_action_ids']=unresolved
                        return {'reason':'world_ended','seal':seal,'finish_turns_drained':True}
                with patch('robofrontier.engines.claude.run.CentralizedSupervisor', Supervisor):
                    result=run_task(run,self.env,turn_budget_usd=.5,total_budget_usd=2,wall_limit_s=30,
                                           policy_factory=Attached,owner_factory=lambda *a,**k: ExitingOwner(None))
                self.assertEqual(result['status'], expected)

    def test_ended_world_requires_readable_boolean_evaluation(self):
        for content, expected in ((None,False),('{broken',False),('{}',False),
                                  ('{"task_success":"false"}',False),('{"task_success":false}',True)):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as tmp:
                import shutil
                run=Path(tmp)/'run'; shutil.copytree(self.run,run)
                (run/'private/state/connections/Meta.json').write_text('{"url":"http://127.0.0.1:1234"}')
                if content is not None: (run/'private/outputs/evaluation.json').write_text(content)
                class Attached(Policy):
                    def __init__(self,*a,**k): super().__init__(*a,**k); self.store.attached=True
                class ExitingOwner(Owner):
                    def wait(self,timeout): self.status=0
                class Supervisor:
                    def __init__(self,*a,**k): pass
                    def run(self): return {'reason':'world_ended','seal':{'sealed':True,'unresolved_action_ids':[]},
                                          'finish_turns_drained':True}
                with patch('robofrontier.engines.claude.run.CentralizedSupervisor',Supervisor):
                    result=run_task(run,self.env,turn_budget_usd=.5,total_budget_usd=2,wall_limit_s=30,
                                           policy_factory=Attached,owner_factory=lambda *a,**k: ExitingOwner(None))
                self.assertTrue(result['evaluation_required'])
                self.assertEqual(result['evaluation_present'],expected)
                self.assertEqual(result['status'],'finished' if expected else 'needs_review')


    def test_a_task_cap_that_concurrent_roles_could_exhaust_is_refused_before_any_claim(self):
        claim = self.run/'private/state/claude-engineering-claim.json'
        (self.run/'public/inputs/roles.json').write_text(json.dumps({'roles': {
            'Meta': {'kind': 'manager'}, 'Coordinator': {'kind': 'team-controller'},
            'A1': {'kind': 'worker', 'robot': 'A1'}, 'A2': {'kind': 'worker', 'robot': 'A2'}}}))
        for topology, turn, total in (('hierarchical', None, 1), ('hierarchical', .5, 1), ('peer', .6, 1.7)):
            with self.subTest(topology=topology, turn=turn, total=total):
                (self.run/'private/inputs/harness.json').write_text(json.dumps({'engine': 'claude', 'topology': topology}))
                with self.assertRaisesRegex(ValueError, 'budget'):
                    run_task(self.run, self.env, turn_budget_usd=turn, total_budget_usd=total,
                                    standing_policy_factory=lambda *a, **k: self.fail('must not start'),
                                    owner_factory=lambda *a, **k: self.fail('must not start'))
                self.assertFalse(claim.exists())
                self.assertFalse((self.run/'private/state/claude-budget.sqlite').exists())
        # Adaptive: the Controller and one delegate per arm.
        (self.run/'private/inputs/harness.json').write_text(json.dumps({'engine': 'claude', 'topology': 'adaptive'}))
        (self.run/'public/inputs/roles.json').write_text(json.dumps({'roles': {
            'Meta': {'kind': 'manager'}, 'Controller': {'kind': 'controller', 'robots': ['A1', 'A2', 'A3']}}}))
        with self.assertRaisesRegex(ValueError, '4 concurrent roles'):
            run_task(self.run, self.env, turn_budget_usd=.5, total_budget_usd=1.9,
                            adaptive_policy_factory=lambda *a, **k: self.fail('must not start'),
                            owner_factory=lambda *a, **k: self.fail('must not start'))
        self.assertFalse(claim.exists())
        result = run_task(self.run, self.env, turn_budget_usd=.5, total_budget_usd=2,
                                 adaptive_policy_factory=lambda *a, **k: Policy(), owner_factory=lambda *a, **k: Owner(1))
        self.assertEqual(result['reason'], 'launch_error')


    def test_a_centralized_launch_failing_before_its_claim_can_be_retried(self):
        attempts = []
        def policy(*args, **kwargs):
            attempts.append(kwargs)
            if len(attempts) == 1: raise ValueError('transient input check')
            return Policy()
        with self.assertRaisesRegex(ValueError, 'transient'):
            run_task(self.run, self.env, turn_budget_usd=.5, total_budget_usd=2, wall_limit_s=30,
                            policy_factory=policy, owner_factory=lambda *a, **k: self.fail('must not start'))
        self.assertFalse((self.run/'private/state/claude-engineering-claim.json').exists())
        self.assertFalse(list((self.run/'private/state').glob('claude-budget.sqlite*')))
        result = run_task(self.run, self.env, turn_budget_usd=.5, total_budget_usd=2, wall_limit_s=30,
                                 policy_factory=policy, owner_factory=lambda *a, **k: Owner(1))
        self.assertEqual(len(attempts), 2)
        self.assertEqual(result['reason'], 'launch_error')
        self.assertEqual(result['error_type'], 'RuntimeError')
        self.assertTrue((self.run/'private/state/claude-budget.sqlite').is_file())


if __name__ == '__main__': unittest.main()
