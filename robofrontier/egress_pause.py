"""Hold one live world through a temporary route outage, without replay."""
import json,os,time
from pathlib import Path

from .run_layout import path as run_path
from .run_setup import verify_inputs


class WorldPause:
    def __init__(self, service):
        self.service=service;self.store=service.store;self.world=service.world
        self.path=Path(os.environ['ROBOFRONTIER_EGRESS_PAUSE_FILE']) if os.environ.get('ROBOFRONTIER_EGRESS_PAUSE_FILE') else None
        self.instance=os.environ.get('ROBOFRONTIER_EGRESS_INSTANCE')
        self.job=os.environ.get('SLURM_JOB_ID');self.claim=None;self.failed=False;self.operator_hold=False

    def ownership(self):
        return {'run_id':self.store.get('run_id'),'segment':self.store.get('segment',0),
                'lifecycle':self.store.get('lifecycle'),'robots':self.store.get('robot_owners'),
                'threads':{k:v.get('thread_id') for k,v in self.store.agents().items()},
                'actions':self.store.actions()}

    def same_ownership(self):
        current=self.ownership();before_threads=self.before['threads'];after_threads=current['threads']
        if set(before_threads)!=set(after_threads):return False
        additions={value for key,value in after_threads.items() if value!=before_threads[key]}
        if any(before_threads[key] is not None and value!=before_threads[key] for key,value in after_threads.items()):return False
        if additions:
            # A fork acknowledged before pause may finish binding while paused.
            # Its native ID must already belong to this exact trusted gateway task.
            try:
                records=json.loads((self.path.parent/'control/ownership.json').read_text())
                owned={tid for row in records if row['run']==str(self.service.directory) for tid in row['threads']}
            except (OSError,ValueError,KeyError):return False
            if not additions<=owned:return False
        current['threads']=before_threads
        return current==self.before

    def fence(self):
        self.failed=True;self.store.put('dispatch_paused',True)
        self.store.event('EGRESS_RESUME_REFUSED','Meta',{'reason':'Original world, input integrity or ownership changed; no replay'})
        (self.path.parent/'EGRESS_ERROR').touch(mode=0o600)
        self.service.shutdown=True
        return True

    def close(self):
        if self.claim is not None:
            elapsed=time.monotonic()-self.started
            if self.before['lifecycle']=='running':self.store.put('downtime_s',self.store.get('downtime_s',0.)+elapsed)
            self.store.event('EGRESS_PAUSE_CLOSED','Meta',{'paused_s':elapsed,'automatic_replays':0})
            self.claim=None

    def sync(self):
        if not self.path:return False
        if self.failed:return True
        if any((self.path.parent/name).exists() for name in ('EGRESS_ERROR','CREDENTIAL_ERROR')):
            self.failed=True;self.service.shutdown=True
            return True
        if self.operator_hold:return self.store.get('dispatch_paused',True)
        try:
            from .slurm_proxy import read_record,EgressError
            marker=read_record(self.path)
        except FileNotFoundError:
            marker=None
        except (OSError,ValueError,EgressError):return self.fence()
        if marker is not None:
            if (marker.get('schema')!='robofrontier.egress-pause.v1' or marker.get('job_id')!=self.job
                    or marker.get('instance')!=self.instance or not isinstance(marker.get('claim'),str)):
                return self.fence()
            if self.claim is None:
                self.claim=marker['claim'];self.started=time.monotonic();self.before=self.ownership()
                self.wall_started=time.time()
                self.prior_dispatch=self.store.get('dispatch_paused',False)
                self.prior_physics=self.store.get('physics_state')
                self.receipts={r[0]:tuple(r) for r in self.store.db.execute("SELECT * FROM calls WHERE op IN ('move','gripper','action_batch') AND status IN ('completed','failed')")}
                with self.store.transaction():
                    self.store.put('dispatch_paused',True);self.store.put('physics_state','paused_by_egress')
                    self.event_seq=self.store.event('EGRESS_PAUSED','Meta',{'instance':self.instance,'claim':self.claim,'sim_time_s':float(self.world.time)})
            elif marker['claim']!=self.claim:return self.fence()
            return True
        if self.claim is None:return False
        unchanged=all(tuple(self.store.db.execute('SELECT * FROM calls WHERE id=?',(key,)).fetchone() or ())==value for key,value in self.receipts.items())
        if (self.world is not self.service.world or not self.same_ownership() or not unchanged
                or self.store.get('integrity_valid') is not True or verify_inputs(self.service.directory)
                or run_path(self.service.directory,'stop').exists()
                or self.store.get('physics_state')!='paused_by_egress'):
            return self.fence()
        manual=bool(self.store.db.execute("SELECT 1 FROM events WHERE seq>? AND kind IN ('DISPATCH_PAUSED','DISPATCH_RESUMED') LIMIT 1",(self.event_seq,)).fetchone())
        elapsed=time.monotonic()-self.started
        with self.store.transaction():
            if self.before['lifecycle']=='running':self.store.put('downtime_s',self.store.get('downtime_s',0.)+elapsed)
            self.store.put('dispatch_paused',True if manual else self.prior_dispatch)
            self.store.put('physics_state','paused_by_user' if manual else self.prior_physics)
            self.store.event('EGRESS_HELD_FOR_REVIEW' if manual else 'EGRESS_RESUMED','Meta',
                             {'instance':self.instance,'claim':self.claim,'paused_s':elapsed,'automatic_replays':0})
            self.store.put('egress_recovery',{'instance':self.instance,'claim':self.claim,
                                            'paused_at':self.wall_started,'resumed_at':time.time()})
        budget=self.service.policy_budget
        if budget is not None and budget.deadline is not None:budget.deadline+=elapsed
        if budget is not None and budget.cutoff is not None:budget.cutoff+=elapsed
        for waiter in self.service.waiters.values():waiter['deadline']+=elapsed
        for actor,agent in self.store.agents().items():
            if agent.get('next_check') is not None:self.store.update_agent(actor,next_check=agent['next_check']+elapsed)
        # Native setup has its own wall timeout. Infrastructure downtime must
        # not manufacture an uncertain fork when the same owner resumes.
        delegations=self.store.get('delegations') or {}
        for batch in delegations.values():
            if batch.get('status') not in ('finished','needs_review') and 'setup_deadline' in batch:
                batch['setup_deadline']+=elapsed
        if delegations:self.store.put('delegations',delegations)
        self.claim=None;self.operator_hold=manual
        return manual
