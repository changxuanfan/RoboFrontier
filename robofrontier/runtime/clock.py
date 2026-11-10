"""Explicit user-authorized bounded policy trials, without Oracle readiness claims.

Uses the existing world, public tools and action-stop path. Only the run budget
and closure are deterministic; this module never chooses a robot task or motion.
"""
import argparse
import json
import math
import time
from pathlib import Path

from .setup import write_json

PROBE_READINESS='user_authorized_bounded_policy_probe'


WALL_CLOCK='START_wall_time'
CLOCKS=(WALL_CLOCK,'active_time_v1')
# Active time: one owner tick more than this after the previous one is a stall (a frozen or
# sleeping host) and adds nothing. Ticks normally come every few milliseconds.
STALL_S=5.
# The accumulated active time is saved at most this often, and at the cutoff and on close.
PERSIST_S=1.


def run_clock(run_protocol):
    """The clock a frozen policy run protocol uses; runs frozen without one use START wall time."""
    return run_protocol.get('clock',WALL_CLOCK)


def wall_backstop_s(run_protocol):
    """The frozen wall backstop of an active-time run (task_families.WALL_BACKSTOP_S), or None."""
    value=run_protocol.get('wall_backstop_s')
    if run_clock(run_protocol)==WALL_CLOCK or value is None:return None
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or value<=0:
        raise ValueError('Invalid wall backstop')
    return float(value)


def backstop_since(store):
    """Wall time the backstop counts from: START, or an operator's authorized continuation after
    an earlier backstop stop (run_segments.prepare_retry)."""
    waived=store.get('wall_backstop_waived') or {}
    return max(store.get('start_at'),waived.get('at') or 0.)


def protocol(seconds=1200.,clock=WALL_CLOCK):
    return validate_protocol(dict(kind='bounded_policy_trial',authorization='explicit_user_request',
        wall_limit_s=seconds,clock=clock,oracle_readiness_claimed=False))


def validate_protocol(value):
    expected={'kind','authorization','wall_limit_s','clock','oracle_readiness_claimed'}
    if not isinstance(value,dict) or set(value)!=expected:raise ValueError('Explicit bounded policy protocol required')
    if (value['kind']!='bounded_policy_trial' or value['authorization']!='explicit_user_request'
            or value['clock'] not in CLOCKS or value['oracle_readiness_claimed'] is not False):
        raise ValueError('Invalid bounded policy authorization or clock')
    limit=value['wall_limit_s']
    if isinstance(limit,bool) or not isinstance(limit,(int,float)) or not math.isfinite(limit) or not 0<limit<=86400:
        raise ValueError('Positive finite wall budget required')
    return dict(value)


def counting(store):
    """True while the trial's active time runs: started, not ended and not paused.

    A pause by the experiment manager, a Slurm egress pause, a network-outage pause and the
    budget cutoff itself all set dispatch_paused or leave physics not running."""
    return (store.get('lifecycle')=='running' and store.get('physics_state')=='running'
            and not store.get('dispatch_paused',False) and not store.get('egress_review_hold',False))


class BudgetGuard:
    """No new requests past the deadline; bounded braking is recorded separately.

    START_wall_time: the deadline is START plus the limit plus recorded downtime, on the wall clock.
    active_time_v1: the limit is active running time, accumulated by the owner tick by tick while
    the world runs unpaused (`counting`) and saved in the run store as `active_s`, so a continued
    segment or a restarted owner carries it on and never re-counts a gap. A gap of more than
    `stall_s` between ticks (a frozen, suspended or sleeping host) adds nothing.

    Wall backstop (active-time runs frozen with `wall_backstop_s`): a run whose active-time cutoff
    has not fired once that much wall time has passed since START (`backstop_since`) stops the same
    way, even while a pause holds the world, but is recorded as `wall_backstop`: needs review and
    not counted. It keeps its own records (POLICY_WALL_BACKSTOP, POLICY_BACKSTOP_CLOSED), so it is
    not a normal end and a continuation can be authorized explicitly (run_segments)."""
    def __init__(self,run_protocol,grace_s=10.,stall_s=STALL_S,persist_s=PERSIST_S,wall_backstop_s=None):
        self.protocol=validate_protocol(run_protocol);self.deadline=None;self.cutoff=None
        self.cutoff_evaluation=None;self.completed=False;self.grace_s=grace_s
        self.active_clock=self.protocol['clock']!=WALL_CLOCK
        self.stall_s=stall_s;self.persist_s=persist_s
        self.active=None;self.saved=None;self.last_tick=None;self.stalls=0
        self.wall_backstop_s=wall_backstop_s if self.active_clock else None;self.backstopped=False
        self.backstop_checked=None

    def backstop_due(self,store,wall_now):
        if self.wall_backstop_s is None or self.cutoff is not None or self.completed:return False
        if store.get('lifecycle')!='running' or store.get('start_at') is None:return False
        return wall_now-backstop_since(store)>=self.wall_backstop_s

    def backstop_pending(self,service,wall_now=None):
        """The backstop is due or its stop is under way: it then runs even through a pause."""
        if self.backstopped:return not self.completed
        if self.wall_backstop_s is None:return False
        wall_now=time.time() if wall_now is None else wall_now
        # A held world's owner loops fast; the store is read at most once a second here.
        if self.backstop_checked is not None and 0<=wall_now-self.backstop_checked<1.:return False
        self.backstop_checked=wall_now
        return self.backstop_due(service.store,wall_now)

    def interrupt(self):
        """The world was paused outside the tick (egress or outage pause): restart the interval."""
        self.last_tick=None

    def retract(self,service,seconds):
        """Take back up to `seconds` just counted (an outage found only after its failed probes)."""
        if not self.active_clock or self.cutoff is not None:return 0.
        if self.active is None:self.active=self.saved=float(service.store.get('active_s',0.) or 0.)
        taken=min(max(0.,seconds),self.active);self.active-=taken;self.flush(service.store)
        return taken

    def flush(self,store):
        if self.active is not None and self.active!=self.saved:
            store.put('active_s',self.active);self.saved=self.active

    def accumulate(self,service,mono_now):
        """Add the interval since the previous tick when the world ran unpaused at both ends."""
        store=service.store
        if self.active is None:self.active=self.saved=float(store.get('active_s',0.) or 0.)
        running=counting(store)
        if running and self.last_tick is not None:
            gap=mono_now-self.last_tick
            if 0<=gap<=self.stall_s:self.active+=gap
            elif gap>self.stall_s:
                self.stalls+=1
                store.event('ACTIVE_TIME_STALL','Meta',dict(gap_s=gap,active_s=self.active,counted_s=0.))
        self.last_tick=mono_now if running else None
        if self.active-self.saved>=self.persist_s:self.flush(store)

    def begin_cutoff(self,service,wall_now,mono_now,backstop=False):
        """Score now, pause dispatch, stop the arms; the run closes after the braking grace."""
        self.cutoff=mono_now;self.backstopped=backstop;cutoff_sim_s=float(service.world.time)
        self.cutoff_evaluation=service.settled_evaluation()
        service.store.put('dispatch_paused',True);service.store.put('physics_state','paused_by_user')
        clock=dict(active_s=self.active,clock=self.protocol['clock']) if self.active_clock else {}
        if backstop:
            wall=dict(wall_backstop_s=self.wall_backstop_s,wall_since_start_s=wall_now-backstop_since(service.store))
            service.store.put('wall_backstop',dict(wall,at=wall_now,segment=service.store.get('segment',0)))
            service.store.event('POLICY_WALL_BACKSTOP','Meta',dict(wall_limit_s=self.protocol['wall_limit_s'],
                sim_time_s=cutoff_sim_s,**clock,**wall))
        else:
            service.store.event('POLICY_WALL_LIMIT','Meta',dict(wall_limit_s=self.protocol['wall_limit_s'],sim_time_s=cutoff_sim_s,**clock))
        from .action_batch import cancel_collecting
        cancel_collecting(service.store,'policy_wall_limit',cutoff_sim_s)
        for actor in service.policy_roles:
            service.store.signal(actor,dict(event='policy_wall_limit',text='The trial budget has ended. Stop new work; retain real action outcomes and end this native turn.'))
        write_json(service.directory/'private/outputs/budget-cutoff.json',dict(
            protocol=self.protocol,cutoff_unix_s=wall_now,sim_time_s=cutoff_sim_s,
            **({'active_s':self.active,'active_time_stalls':self.stalls} if self.active_clock else {}),
            **({'wall_backstop':True,'needs_review':True,'wall_backstop_s':self.wall_backstop_s} if backstop else {}),
            evaluation=self.cutoff_evaluation))

    def tick(self,service,wall_now=None,mono_now=None):
        wall_now=time.time() if wall_now is None else wall_now
        mono_now=time.monotonic() if mono_now is None else mono_now
        if service.store.get('lifecycle')!='running' or self.completed:
            self.last_tick=None;return
        if self.active_clock:
            if self.cutoff is None:
                self.accumulate(service,mono_now)
                if self.active>=self.protocol['wall_limit_s']:self.flush(service.store);self.begin_cutoff(service,wall_now,mono_now)
                elif self.backstop_due(service.store,wall_now):
                    self.flush(service.store);self.begin_cutoff(service,wall_now,mono_now,backstop=True)
        else:
            if self.deadline is None:
                # Downtime between segments of a continued run does not count (run_segments.deadline).
                left=service.store.get('start_at')+self.protocol['wall_limit_s']+service.store.get('downtime_s',0.)-wall_now
                self.deadline=mono_now+max(0.,left)
            if self.cutoff is None and mono_now>=self.deadline:self.begin_cutoff(service,wall_now,mono_now)
        if self.cutoff is None:return
        active=[robot for robot,arm in service.world.arms.items() if arm.job is not None]
        if active and mono_now-self.cutoff<self.grace_s:return
        if active:
            for robot in active:
                ident=service.world.arms[robot].job
                if ident in service.store.actions() and service.store.actions()[ident]['status'] in ('pending','running'):
                    action=service.store.uncertain_action(ident,'Budget stop did not settle before closure grace expired')
                    job=service.requests.get(ident)
                    if job is not None:
                        service.respond(job,dict(execution_status='uncertain',execution=action,run_ended=True));job['done'].set()
            service.shutdown=True
        # Capture before closing the recorder. Grace never starts a new action.
        images={};capture_error=None
        try:
            cameras=[c for c in ('global','global_rear') if c in service.task.get('cameras',[])]
            if cameras:images=service.capture(cameras)
        except Exception as error:capture_error=str(error)[:500]
        unknown=[key for key,a in service.store.actions().items() if a['status'] in ('pending','running','uncertain')]
        post_stop=service.world.evaluate()
        service.world.end_trial()
        service.store.put('lifecycle','ended');service.store.put('physics_state','finished')
        reason='wall_backstop' if self.backstopped else 'wall_limit'
        service.store.put('termination_reason',reason)
        service.store.event('POLICY_BACKSTOP_CLOSED' if self.backstopped else 'POLICY_BUDGET_CLOSED','Meta',
                            dict(unresolved_action_ids=unknown,active_robots=active,stopping_overrun_wall_s=mono_now-self.cutoff))
        service.stop_video()
        result=dict(self.cutoff_evaluation,termination_reason=reason,budget_exhausted=not self.backstopped,
            task_success=bool(self.cutoff_evaluation.get('task_success') and not unknown),
            budget_wall_limit_s=self.protocol['wall_limit_s'],post_stop_evaluation=post_stop,
            **({'budget_clock':self.protocol['clock'],'budget_active_s':self.active} if self.active_clock else {}),
            # Stopped by wall time, not the active-time limit: not a scored result.
            **({'wall_backstop':True,'needs_review':True} if self.backstopped else {}),
            unresolved_action_ids=unknown,stopping_overrun_wall_s=mono_now-self.cutoff,
            final_observation=images,final_capture_error=capture_error)
        write_json(service.directory/'private/outputs/evaluation.json',result)
        service.save_evaluation_evidence('evaluation-window.json');service.export_records()
        self.completed=True


def main():
    from .pipeline import Service
    import glfw
    class BoundedService(Service):
        def __init__(self,run,hidden=False):
            task=json.loads((run/'private/inputs/task.json').read_text())
            if task.get('execution_readiness')!=PROBE_READINESS:raise ValueError('Prepare an explicit bounded policy run')
            self.budget=BudgetGuard(task['run_protocol']);self.closing_at=None;self.titled=False
            super().__init__(run,hidden)
        def pump(self):
            if not self.titled and hasattr(self,'window'):
                glfw.set_window_title(self.window,'RoboFrontier — '+self.task['id']+' — GPT 20 min');self.titled=True
            self.budget.tick(self)
            super().pump()
            self.budget.tick(self)
            if self.ended:
                if self.closing_at is None:self.closing_at=time.monotonic()+2
                elif time.monotonic()>=self.closing_at:self.shutdown=True
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--run-dir',type=Path,required=True);p.add_argument('--hidden',action='store_true')
    args=p.parse_args();BoundedService(args.run_dir.resolve(),args.hidden).run()


if __name__=='__main__':main()
