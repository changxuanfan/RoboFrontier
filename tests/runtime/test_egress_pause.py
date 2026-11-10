"""Infrastructure pauses retain one world and settle original calls once."""
import json,os,sys,tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from tests.fake_pipeline import FakeWorld,fake_capture
from robofrontier.runtime.setup import prepare_run
from robofrontier.runtime.service import RuntimeService
from robofrontier.batch.slurm_proxy import atomic

class SteppingWorld(FakeWorld):
    def step(self): self.time += .02

class EgressPauseTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name).resolve();self.private=self.root/'engine';self.private.mkdir(mode=0o700)
        self.marker=self.private/'EGRESS_PAUSED';self.run=self.root/'run';prepare_run(self.run)
        self.env=patch.dict(os.environ,{'ROBOFRONTIER_EGRESS_PAUSE_FILE':str(self.marker),'ROBOFRONTIER_EGRESS_INSTANCE':'a'*32,'SLURM_JOB_ID':'123'})
        self.env.start();self.addCleanup(self.env.stop)
        self.service=RuntimeService(self.run,SteppingWorld,fake_capture);self.addCleanup(self.service.close)
        self.counter=0
        for actor in ('Controller','A','B','C','D'):
            self.call(actor,'ready');self.call('Meta','bind',{'actor':actor,'thread_id':'thread-'+actor})
            self.service.store.observe_session(actor,'idle','turn-'+actor,time.time(),'codex.wait_threads')
        self.call('Meta','start')
    def call(self,actor,op,data=None,call_id=None):
        self.counter+=1
        job=self.service.accept(actor,op,data or {},call_id or str(self.counter));self.service.pump();return job
    def pause(self):
        atomic(self.marker,{'schema':'robofrontier.egress-pause.v1','job_id':'123','instance':'a'*32,'claim':'fixture','at':time.time()})
        self.service.pump()
    def test_pause_freezes_world_and_holds_new_actions_then_resumes_original_once(self):
        first=self.call('A','gripper',{'state':'close','wait':False},'original')
        world=self.service.world;self.service.step_physics();sim=world.time
        self.pause()
        for _ in range(20):self.service.step_physics()
        self.assertEqual(world.time,sim)
        queued=self.call('B','gripper',{'state':'open','wait':False},'during-outage')
        self.assertFalse(queued['done'].is_set());self.assertEqual(len(world.executed),1)
        self.marker.unlink();self.service.pump()
        self.assertIs(self.service.world,world);self.assertTrue(queued['done'].is_set())
        self.assertEqual([x[1] for x in world.executed],['original','during-outage'])
        duplicate=self.call('B','gripper',{'state':'open','wait':False},'during-outage')
        self.assertEqual(duplicate['result'],queued['result']);self.assertEqual(len(world.executed),2)
        world.complete('A');world.complete('B');self.service.pump()
        self.assertEqual(self.service.store.actions()['original']['status'],'completed')
    def test_operator_pause_is_never_cleared_by_network_recovery(self):
        self.pause()
        self.service.store.put('dispatch_paused',True)
        self.service.store.event('DISPATCH_PAUSED','Meta',{'reason':'operator'})
        self.marker.unlink();self.service.pump()
        self.assertTrue(self.service.store.get('dispatch_paused'))
        self.assertFalse(self.service.step_physics())
    def test_changed_ownership_fences_instead_of_thawing(self):
        self.pause();self.service.store.put('robot_owners',{'A':'different-owner'})
        self.marker.unlink();self.service.pump()
        self.assertFalse(self.service.step_physics())
        self.assertTrue((self.private/'EGRESS_ERROR').exists())

    def test_unsafe_pause_record_fences_without_physics(self):
        self.pause();self.marker.chmod(0o644);self.service.pump()
        self.assertFalse(self.service.step_physics());self.assertTrue(self.service.shutdown)

    def test_network_continuation_waits_for_original_receipt_and_claims_only_once(self):
        from robofrontier.runtime.cli import execute
        self.call('A','gripper',{'state':'close','wait':False},'original-before-network')
        self.pause();self.marker.unlink();self.service.pump()
        data={'actor':'A','thread_id':'thread-A','failed_turn_id':'failed-native-turn','error_observed_at':time.time()}
        claim=lambda:execute(self.service.store,'network-recovery',data,'Meta',time.time())
        self.assertFalse(claim()['allowed'])
        self.service.world.complete('A');self.service.pump()
        original=self.service.store.call('original-before-network')
        self.assertTrue(claim()['allowed']);self.assertFalse(claim()['allowed'])
        self.assertEqual(original,self.service.store.call('original-before-network'))
        execute(self.service.store,'network-recovery-uncertain',{'actor':'A','thread_id':'thread-A'},'Meta',time.time())
        self.assertFalse(self.service.step_physics());self.assertTrue(self.service.store.get('dispatch_paused'))

    def test_world_that_missed_a_short_resume_continues_the_pause_unfenced(self):
        # B-12: the watcher resumed and re-paused between two reads of this world.
        from robofrontier.batch.slurm_proxy import pause_marker
        world=self.service.world;self.service.step_physics();sim=world.time;watcher='w'*32
        atomic(self.marker,pause_marker('123','a'*32,watcher,1,'first-pause'));self.service.pump()
        time.sleep(.02)
        atomic(self.marker,pause_marker('123','a'*32,watcher,2,'second-pause'));self.service.pump()
        for _ in range(5):self.assertFalse(self.service.step_physics())
        self.assertEqual(world.time,sim)
        self.assertFalse((self.private/'EGRESS_ERROR').exists());self.assertFalse(self.service.shutdown)
        self.marker.unlink();self.service.pump()
        self.assertTrue(self.service.step_physics());self.assertIs(self.service.world,world)
        kinds=[e['kind'] for e in self.service.store.events() if e['kind'].startswith('EGRESS_')]
        self.assertEqual(kinds,['EGRESS_PAUSED','EGRESS_PAUSE_CONTINUED','EGRESS_RESUMED'])
        self.assertEqual(self.service.store.get('egress_recovery')['claim'],'second-pause')
        self.assertGreaterEqual(self.service.store.get('downtime_s'),.02)

    def test_new_claim_from_another_watcher_or_an_older_pause_still_fences(self):
        from robofrontier.batch.slurm_proxy import pause_marker
        for watcher,pause_id in (('x'*32,2),('w'*32,1),('w'*32,'2')):
            with self.subTest(watcher=watcher,pause_id=pause_id):
                self.setUp()
                atomic(self.marker,pause_marker('123','a'*32,'w'*32,1,'first-pause'));self.service.pump()
                atomic(self.marker,{**pause_marker('123','a'*32,watcher,1,'other-claim'),'pause_id':pause_id})
                self.service.pump()
                self.assertTrue(self.service.shutdown);self.assertTrue((self.private/'EGRESS_ERROR').exists())

@unittest.skipUnless(sys.platform=='linux','MuJoCo qualification runs on allocated Linux CPU')
class RealPhysicsPauseTests(unittest.TestCase):
    def test_qpos_qvel_and_sim_time_remain_exactly_frozen_in_original_world(self):
        from robofrontier.runtime.pipeline import World
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve();private=root/'engine';private.mkdir(mode=0o700)
            run=root/'run';prepare_run(run);marker=private/'EGRESS_PAUSED'
            with patch.dict(os.environ,{'ROBOFRONTIER_EGRESS_PAUSE_FILE':str(marker),'ROBOFRONTIER_EGRESS_INSTANCE':'a'*32,'SLURM_JOB_ID':'123'}):
                service=RuntimeService(run,World,fake_capture)
                try:
                    for i,actor in enumerate(('Controller','A','B','C','D')):
                        for op,data in [('ready',{}),('bind',{'actor':actor,'thread_id':'fixture-'+actor})]:
                            job=service.accept('Meta' if op=='bind' else actor,op,data,actor+op);service.pump()
                            self.assertNotIn('error',job['result'])
                        service.store.observe_session(actor,'idle','fixture-turn',time.time(),'codex.wait_threads')
                    job=service.accept('Meta','start',{},'start');service.pump();self.assertTrue(job['result']['started'])
                    service.step_physics();world=service.world
                    before=(world.data.qpos.tobytes(),world.data.qvel.tobytes(),world.time)
                    atomic(marker,{'schema':'robofrontier.egress-pause.v1','job_id':'123','instance':'a'*32,'claim':'real-physics','at':time.time()})
                    service.pump()
                    for _ in range(100):self.assertFalse(service.step_physics())
                    self.assertEqual(before,(world.data.qpos.tobytes(),world.data.qvel.tobytes(),world.time))
                    marker.unlink();service.pump();self.assertTrue(service.step_physics())
                    self.assertIs(service.world,world);self.assertGreater(world.time,before[2])
                finally:service.close()
