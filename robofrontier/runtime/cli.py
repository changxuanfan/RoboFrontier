"""Local administrative operations for Meta's deterministic dispatcher.

This module never calls Codex or controls a robot.
"""
import argparse
import json
from pathlib import Path
import time
from .store import RuntimeStore
from . import layout as run_layout
from .scheduling import Scheduler
from .delegation import Delegations


def fork_provenance(parent, child):
    """Verify native lineage without exposing conversation contents to policy."""
    import hashlib
    import re
    if any(not re.fullmatch(r'[0-9a-f-]{36}',v) for v in (parent,child)):
        raise ValueError('Expected native session UUIDs')
    def records(tid):
        import os
        home=Path(os.environ.get('CODEX_HOME',Path.home()/'.codex'))
        paths=[p for directory in ('sessions','archived_sessions')
               for p in (home/directory).glob('**/*'+tid+'*.jsonl')]
        indexed={}
        for path in paths:
            rows=[json.loads(line) for line in path.read_text().splitlines()]
            meta=next((r['payload'] for r in rows if r['type']=='session_meta'),{})
            if meta.get('id')!=tid:continue  # parent IDs can appear in fork filenames
            for row in rows:
                ordinal=row.get('ordinal')
                if type(ordinal) is not int:raise ValueError('Native ordinal missing')
                previous=indexed.get(ordinal)
                if previous is not None and previous!=row:
                    raise ValueError('Conflicting native history segments')
                indexed[ordinal]=row
        if not indexed:raise ValueError('Native session provenance missing')
        return [indexed[k] for k in sorted(indexed)]
    rows=records(child)
    meta=next(r['payload'] for r in rows if r['type']=='session_meta')
    cutoff=meta.get('forked_from_ordinal_exclusive')
    if meta.get('forked_from_id')!=parent or type(cutoff) is not int:
        raise ValueError('Native fork lineage does not match requested parent')
    prefix=[r for r in records(parent) if r['ordinal']<cutoff]
    return {'source_thread_id':parent,'source_ordinal':cutoff,
            'source_sha256':hashlib.sha256(json.dumps(prefix,sort_keys=True).encode()).hexdigest()}


def native_fork_provenance(store, parent, child):
    """Dispatch lineage verification to the evidence format of this run's engine."""
    engine=store.get('config').get('engine','codex')
    if engine=='claude':
        from ..engines.claude.provenance import fork_provenance as claude_provenance
        from ..engines.claude.native_home import history_directory
        return claude_provenance(parent,child,history_directory(store.path.parents[2]))
    return fork_provenance(parent,child)


def execute(store, op, data, owner, now):
    cfg=store.get('config')
    if op=='seal':
        from .seal import seal_run
        if set(data)-{'timeout_s'}:raise ValueError('Seal accepts only an engineering timeout_s')
        return seal_run(store,data.get('timeout_s',30))
    if op=='snapshot':
        return {'lifecycle':store.get('lifecycle'),'paused':store.get('dispatch_paused',False),
                'egress_paused':store.get('physics_state')=='paused_by_egress' or store.get('egress_review_hold',False),
                'egress_recovery':store.get('egress_recovery'),
                'egress_review_hold':store.get('egress_review_hold',False),
                'dispatcher_health':store.get('dispatcher_health',{}),
                'config':{**{k:cfg[k] for k in ('poll_interval_s','session_observation_ttl_s','model','effort')},
                          'engine':cfg.get('engine','codex')},
                'agents':{a:{k:x for k,x in v.items() if k!='note'} for a,v in store.agents().items()},
                'delegations':Delegations(store).active() if cfg['topology']=='adaptive' else [],
                'pending':{a:store.pending(a) for a,v in store.agents().items() if v['kind']!='manager'}}
    if op=='delegate-snapshot-bind':
        if cfg.get('engine','codex') != 'codex':
            raise ValueError('Claude adaptive delegation is not yet qualified')
        d=Delegations(store);key=data['id'];thread_id=data['thread_id']
        with store.transaction():
            store.lease(owner,now,cfg['manager_lease_s'])
            d.snapshot_created(key,thread_id,owner)
        provenance=native_fork_provenance(store,d.batch(key)['source_thread_id'],thread_id)
        with store.transaction():
            store.lease(owner,time.time(),cfg['manager_lease_s'])
            d.snapshot_bind(key,thread_id,provenance,owner)
        return {'recorded':True}
    if op=='delegate-bind':
        # Matching transcript prefixes alone do not authenticate a native fork.
        # Claude adaptive delegation stays closed until creation and role binding
        # can be verified together by the trusted host.
        if cfg.get('engine') == 'claude':
            raise ValueError('Claude adaptive delegation is not yet qualified')
        # Commit identity before reading platform files: a failed check must
        # not erase a native fork that already exists.
        d=Delegations(store);key=data['id']
        with store.transaction():
            store.lease(owner,now,cfg['manager_lease_s'])
            d.created(key,data['actor'],data['thread_id'],owner)
        batch=d.batch(key)
        if not batch.get('snapshot_thread_id') or not batch.get('snapshot_provenance'):
            raise ValueError('Verified delegation snapshot required')
        provenance=native_fork_provenance(store,batch['snapshot_thread_id'],data['thread_id'])
        with store.transaction():
            store.lease(owner,time.time(),cfg['manager_lease_s'])
            d.bind(key,data['actor'],data['thread_id'],provenance,owner)
        return {'recorded':True}
    if op.startswith('delegate-'):
        with store.transaction():
            store.lease(owner,now,cfg['manager_lease_s'])
            d=Delegations(store);key=data['id']
            if op=='delegate-claim':return {'delegation':d.claim(key,owner)}
            if op=='delegate-activate':d.activate(key,owner)
            elif op=='delegate-started':
                b=d.started(key,data['actor'],data['outcome'],owner)
                return {'recorded':True,'status':b['status']}
            elif op=='delegate-uncertain':
                # A new lease owner may flag an abandoned creation for review,
                # but must not acquire it and create another set of forks.
                d.uncertain(key,data['reason'],d.batch(key)['claimed_by'])
            else:raise ValueError('Unknown native delegation operation')
            return {'recorded':True}
    if op=='session-unavailable':
        with store.transaction():
            store.lease(owner,now,cfg['manager_lease_s'])
            a=store.agent(data['actor'])
            if a['thread_id']!=data['thread_id']:raise ValueError('Unavailable status has wrong role binding')
            store.update_agent(data['actor'],session_status='unknown',session_observed_at=None)
            health=store.get('dispatcher_health',{})
            health.update(owner=owner,last_cycle_at=now,last_error={'at':now,'actor':data['actor'],'reason':data['reason']})
            store.put('dispatcher_health',health)
            store.event('SESSION_STATUS_UNAVAILABLE',cfg['manager'],data)
        return {'recorded':True}
    if op=='observe-sessions':
        with store.transaction():
            store.lease(owner,now,cfg['manager_lease_s'])
            for item in data['observations']:
                agent=store.agent(item['actor'])
                if item['thread_id']!=agent['thread_id']:
                    raise ValueError('Observed thread does not match bound role')
                store.observe_session(item['actor'],item['status'],item['turn_id'],item['observed_at'],item['source'],item.get('turn_status'))
            if data['observations']:
                health=store.get('dispatcher_health',{})
                health.update(owner=owner,last_cycle_at=now,
                    last_successful_observation_at=max(item['observed_at'] for item in data['observations']))
                if 'cycle' in data:health['cycle']=data['cycle']
                store.put('dispatcher_health',health)
        return {'observed':len(data['observations'])}
    if op=='request-start':
        from .pipeline_client import client_call
        connection=store.path.parent/'connections'/f"{cfg['manager']}.json"
        call_id='start-'+__import__('hashlib').sha256(store.get('run_id').encode()).hexdigest()[:24]
        # Multiple benchmark runs share this Python process. Redirecting global
        # sys.stderr here would cross-wire logs and restore closed streams.
        log_path=run_layout.for_store(store.path,'admin_log');log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open('a') as log:
            print('call_id='+call_id,file=log,flush=True)
        return client_call(connection,'start',{},call_id,log_call_id=False)
    if op=='request-resume':
        # A continued run (docs/running/run-segments.md): the owner resumes the prepared segment
        # and returns each working role's frozen resume message.
        from .pipeline_client import client_call
        connection=store.path.parent/'connections'/f"{cfg['manager']}.json"
        call_id='resume-'+str(store.get('segment',0))+'-'+__import__('hashlib').sha256(store.get('run_id').encode()).hexdigest()[:24]
        log_path=run_layout.for_store(store.path,'admin_log');log_path.parent.mkdir(parents=True,exist_ok=True)
        with log_path.open('a') as log:
            print('call_id='+call_id,file=log,flush=True)
        return client_call(connection,'resume',{},call_id,log_call_id=False)
    if op=='plan':return {'commands':Scheduler(store).plan(owner,now)}
    if op=='claim':return {'command':Scheduler(store).claim(data['wake_id'],owner,now)}
    if op=='dispatch-result':
        store.record_dispatch(data['wake_id'],data['outcome'],data.get('result'))
        if data['outcome']=='sent':
            health=store.get('dispatcher_health',{});health['last_delivery_at']=now;store.put('dispatcher_health',health)
        return {'recorded':True}
    if op=='model-restart':
        from .bootstrap import MAX_MODEL_RESTARTS
        count=store.claim_model_restart(data.get('actor',cfg['manager']),data.get('engine','codex'),MAX_MODEL_RESTARTS)
        return {'allowed':count is not None,'restart':count}
    if op=='network-recovery':
        from .scheduling import blocks_model_recovery
        with store.transaction():
            recovery=store.get('egress_recovery');actor=data['actor'];agent=store.agent(actor)
            if (not recovery or store.get('lifecycle')!='running' or store.get('dispatch_paused',False)
                    or store.get('integrity_valid') is not True or agent.get('thread_id')!=data['thread_id']
                    or agent.get('kind')=='delegate' and agent.get('delegation_state')!='active'):
                return {'allowed':False}
            observed=data.get('error_observed_at',0)
            if not recovery['paused_at']-30<=observed<=recovery['resumed_at']+30:return {'allowed':False,'review_required':True}
            if (any(blocks_model_recovery(v) for v in store.actions(actor).values())
                    or store.db.execute("SELECT 1 FROM calls WHERE actor=? AND status IN ('accepted','running','uncertain') AND op IN ('move','gripper','action_batch','delegate') LIMIT 1",(actor,)).fetchone()):
                return {'allowed':False}
            claims=store.get('network_recovery_claims') or {};key=recovery['claim']+':'+actor
            if key in claims:return {'allowed':False,'review_required':True}
            claims[key]={'thread_id':data['thread_id'],'failed_turn_id':data['failed_turn_id'],'claimed_at':now}
            store.put('network_recovery_claims',claims);store.event('NETWORK_CONTINUATION_CLAIMED',cfg['manager'],claims[key])
            return {'allowed':True}
    if op=='network-recovery-uncertain':
        with store.transaction():
            if store.agent(data['actor']).get('thread_id')!=data['thread_id']:raise ValueError('Network review has wrong role binding')
            store.put('egress_review_hold',True);store.put('dispatch_paused',True);store.put('physics_state','paused_for_review')
            store.event('NETWORK_CONTINUATION_UNCERTAIN',cfg['manager'],{'actor':data['actor'],'thread_id':data['thread_id'],'automatic_replays':0})
        return {'paused':True}
    if op=='pause':
        store.put('dispatch_paused',True);store.event('DISPATCH_PAUSED',cfg['manager'],data)
        return {'paused':True}
    if op=='resume-dispatch':
        if store.get('lifecycle')!='running':raise ValueError('Run is not running')
        store.put('dispatch_paused',False);store.event('DISPATCH_RESUMED',cfg['manager'],data)
        return {'paused':False}
    if op=='export':
        store.export_events(Path(data['path']))
        return {'exported':data['path']}
    raise ValueError('Unknown runtime operation')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-dir',type=Path,required=True)
    p.add_argument('--owner',default='Meta')
    p.add_argument('op',choices=['snapshot','observe-sessions','request-start','request-resume','plan','claim','dispatch-result','pause','resume-dispatch','export','model-restart',
                               'delegate-claim','delegate-snapshot-bind','delegate-bind','delegate-activate','delegate-started','delegate-uncertain','session-unavailable','seal',
                               'network-recovery','network-recovery-uncertain'])
    p.add_argument('--data',default='{}')
    args=p.parse_args()
    path=args.run_dir.resolve()/'private/state/runtime.sqlite'
    if not path.is_file():raise SystemExit('Run is not prepared')
    store=RuntimeStore(path)
    try:print(json.dumps(execute(store,args.op,json.loads(args.data),args.owner,time.time()),ensure_ascii=False))
    finally:store.close()

if __name__=='__main__':main()
