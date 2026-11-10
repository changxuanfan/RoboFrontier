"""Hold one live world through a temporary route outage or a usage limit, without replay.

Three sources pause the world the same way (physics and dispatch held, original calls kept,
the paused time counted neither as active time nor by the wall backstop): a Slurm egress pause
marker; on a local active-time run the network-outage monitor (robofrontier/runtime/outage.py),
which probes the model API hosts; and on every platform a host's request after a turn failed
on the plan's usage limit (runtime/quota.py), held until the limit resets.
"""
import json,os,time
from pathlib import Path

from .layout import path as run_path
from .setup import verify_inputs


class WorldPause:
    def __init__(self, service, outage=None):
        self.service=service;self.store=service.store;self.world=service.world
        self.path=Path(os.environ['ROBOFRONTIER_EGRESS_PAUSE_FILE']) if os.environ.get('ROBOFRONTIER_EGRESS_PAUSE_FILE') else None
        self.instance=os.environ.get('ROBOFRONTIER_EGRESS_INSTANCE')
        self.job=os.environ.get('SLURM_JOB_ID');self.claim=None;self.failed=False;self.operator_hold=False
        self.watcher=None;self.pause_id=None
        # A Slurm egress route has its own pause; the outage monitor serves only local runs.
        self.outage=None if self.path else outage
        self.prefix='OUTAGE' if self.outage is not None else 'EGRESS'
        self.outages=0
        self.quotas=0;self.quota=None;self.quota_checked=None

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
            if self.path is None:return False
            try:
                records=json.loads((self.path.parent/'control/ownership.json').read_text())
                owned={tid for row in records if row['run']==str(self.service.directory) for tid in row['threads']}
            except (OSError,ValueError,KeyError):return False
            if not additions<=owned:return False
        current['threads']=before_threads
        return current==self.before

    def fence(self):
        self.failed=True;self.store.put('dispatch_paused',True)
        self.store.event(self.prefix+'_RESUME_REFUSED','Meta',{'reason':'Original world, input integrity or ownership changed; no replay'})
        if self.path is not None:(self.path.parent/'EGRESS_ERROR').touch(mode=0o600)
        self.service.shutdown=True
        return True

    def continues(self,marker):
        """A later pause from the same route watcher (slurm_proxy.pause_marker).
        This world missed the short resume between the two pauses and never
        left its pause, so the outage continues; any other new claim fences."""
        watcher,pause_id=marker.get('watcher'),marker.get('pause_id')
        return (isinstance(watcher,str) and len(watcher)==32 and watcher==self.watcher
                and type(pause_id) is int and type(self.pause_id) is int and pause_id>self.pause_id)

    def close(self):
        if self.outage is not None:self.outage.stop()
        if self.claim is not None:
            elapsed=time.monotonic()-self.started
            if self.before['lifecycle']=='running':self.store.put('downtime_s',self.store.get('downtime_s',0.)+elapsed)
            self.count_pause()
            self.store.event(self.prefix+'_PAUSE_CLOSED','Meta',{'paused_s':elapsed,'automatic_replays':0})
            self.claim=None

    def begin(self,claim,details):
        self.claim=claim;self.started=time.monotonic();self.before=self.ownership()
        self.wall_started=time.time()
        self.prior_dispatch=self.store.get('dispatch_paused',False)
        self.prior_physics=self.store.get('physics_state')
        self.receipts={r[0]:tuple(r) for r in self.store.db.execute("SELECT * FROM calls WHERE op IN ('move','gripper','action_batch') AND status IN ('completed','failed')")}
        with self.store.transaction():
            self.store.put('dispatch_paused',True);self.store.put('physics_state','paused_by_egress')
            self.store.put('pause_since_wall',self.wall_started)
            self.event_seq=self.store.event(self.prefix+'_PAUSED','Meta',{**details,'claim':self.claim,'sim_time_s':float(self.world.time)})
        budget=getattr(self.service,'policy_budget',None)
        if budget is not None:budget.interrupt()

    def count_pause(self):
        """Add the pause that just ended to the wall time the backstop leaves out (clock.backstop_elapsed)."""
        since=self.store.get('pause_since_wall')
        if since is not None:
            self.store.put('pause_wall_s',float(self.store.get('pause_wall_s',0.) or 0.)+max(0.,time.time()-since))
            self.store.put('pause_since_wall',None)

    def sync(self):
        # A run stopped by the wall backstop is ending; no new pause holds its world (policy_probe).
        if self.claim is None and self.store.get('wall_backstop'):return False
        held=self.sync_quota()
        if held is not None:return held
        if not self.path:
            return self.sync_outage() if self.outage is not None else False
        if self.failed:return True
        if any((self.path.parent/name).exists() for name in ('EGRESS_ERROR','CREDENTIAL_ERROR')):
            self.failed=True;self.service.shutdown=True
            return True
        if self.operator_hold:return self.store.get('dispatch_paused',True)
        try:
            from ..batch.slurm_proxy import read_record,EgressError
            marker=read_record(self.path)
        except FileNotFoundError:
            marker=None
        except (OSError,ValueError,EgressError):return self.fence()
        if marker is not None:
            if (marker.get('schema')!='robofrontier.egress-pause.v1' or marker.get('job_id')!=self.job
                    or marker.get('instance')!=self.instance or not isinstance(marker.get('claim'),str)):
                return self.fence()
            if self.claim is None:
                self.begin(marker['claim'],{'instance':self.instance})
                self.watcher=marker.get('watcher');self.pause_id=marker.get('pause_id')
            elif marker['claim']!=self.claim:
                if not self.continues(marker):return self.fence()
                self.store.event('EGRESS_PAUSE_CONTINUED','Meta',{'instance':self.instance,'claim':marker['claim'],
                                                                'previous_claim':self.claim,'pause_id':marker['pause_id']})
                self.claim=marker['claim'];self.pause_id=marker['pause_id']
            return True
        if self.claim is None:return False
        return self.resume({'instance':self.instance})

    def sync_quota(self):
        """Pause for a usage limit a host reported, until it resets; None leaves the other sources."""
        from .quota import resume_at
        if self.quota is None:
            if self.claim is not None:return None  # another pause holds the world; the request waits
            now=time.monotonic()
            if self.quota_checked is not None and 0<=now-self.quota_checked<1.:return None
            self.quota_checked=now
            request=self.store.get('quota_pause')
            if not request or self.store.get('lifecycle')!='running' or self.store.get('physics_state')!='running':return None
            self.quotas+=1;self.quota={**request,'paused_at':time.time(),'prefix':self.prefix};self.prefix='QUOTA'
            self.begin('quota-%d'%self.quotas,{'resets_at':request.get('resets_at'),'resume_at':resume_at(self.quota),
                                               'actor':request.get('actor')})
            notify(self.service.directory,'Usage limit reached; the run is paused until %s'%_local(resume_at(self.quota)))
            return True
        if self.failed:return True
        if time.time()<resume_at(self.quota):return True
        request=self.quota;self.quota=None
        held=self.resume({'resets_at':request.get('resets_at')})
        self.store.put('quota_pause',None);self.prefix=request['prefix']
        notify(self.service.directory,'Usage limit reset; the run resumed' if not held else
               'Usage limit reset; the run stays paused for review')
        return held

    def sync_outage(self):
        """Pause a running world while its model API is down; resume once it answers again."""
        if self.failed:return True
        for kind,value in self.outage.take_notes():self.store.event(kind,'Meta',value)
        if self.operator_hold:return self.store.get('dispatch_paused',True)
        state=self.outage.state()
        if self.claim is None:
            # Only a running trial pauses: not before START, after the budget cutoff or at an end.
            if not state['down'] or self.store.get('lifecycle')!='running' or self.store.get('physics_state')!='running':
                return False
            self.outages+=1
            # The probes that failed before the pause found the API already down; that time does not count either.
            budget=getattr(self.service,'policy_budget',None);retracted=0.
            if budget is not None and state['streak_started'] is not None:
                retracted=budget.retract(self.service,max(0.,self.outage.clock()-state['streak_started']))
            self.begin('outage-%d'%self.outages,{'hosts':list(self.outage.hosts),'failed_probes':state['failures'],
                                                 'retracted_active_s':retracted})
            return True
        if state['down']:return True
        return self.resume({'hosts':list(self.outage.hosts)})

    def resume(self,details):
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
            self.store.event(self.prefix+('_HELD_FOR_REVIEW' if manual else '_RESUMED'),'Meta',
                             {**details,'claim':self.claim,'paused_s':elapsed,'automatic_replays':0})
            self.count_pause()
            # The hosts' one network continuation per role and pause reads this (runtime_cli network-recovery).
            self.store.put('egress_recovery',{'instance':self.instance,'claim':self.claim,
                                            'paused_at':self.wall_started,'resumed_at':time.time()})
        budget=self.service.policy_budget
        if budget is not None and budget.deadline is not None:budget.deadline+=elapsed
        if budget is not None and budget.cutoff is not None:budget.cutoff+=elapsed
        if budget is not None:budget.interrupt()
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


def _local(epoch):
    return time.strftime('%Y-%m-%d %H:%M', time.localtime(epoch))


def notify(run, text):
    """Tell the operator: a line in the run's notifications log and, on macOS, a notification."""
    import subprocess,sys
    try:
        with (Path(run)/'private/outputs/notifications.jsonl').open('a') as log:
            log.write(json.dumps({'at':time.time(),'text':text})+'\n')
    except OSError:pass
    if sys.platform=='darwin' and not os.environ.get('ROBOFRONTIER_NO_NOTIFY'):
        script='display notification %s with title "RoboFrontier"'%json.dumps(Path(run).name+': '+text)
        try:subprocess.Popen(['osascript','-e',script],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        except OSError:pass
