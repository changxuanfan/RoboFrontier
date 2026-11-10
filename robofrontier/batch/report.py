"""Read-only audit of a finished v3 run; writes derived outputs only."""
import argparse
from collections import Counter
import json
from pathlib import Path

from robofrontier.runtime import layout as run_layout
from robofrontier.runtime.store import RuntimeStore
from robofrontier.runtime.setup import write_json, verify_inputs
from robofrontier.runtime.action_batch import external_wait
from robofrontier.batch.metrics import export_metrics, native_codex_sessions, native_subagent_calls, open_session, run_skills, session_glob


def occupancy(intervals, start, end):
    changes=[(start,0),(end,0)]
    for low,high in intervals:
        low,high=max(start,low),min(end,high)
        if high>low:changes.extend([(low,1),(high,-1)])
    active=peak=0;previous=start;durations=Counter()
    for instant,delta in sorted(changes,key=lambda pair:(pair[0],pair[1])):
        durations[active]+=instant-previous
        active+=delta;peak=max(peak,active);previous=instant
    return {'seconds_by_active_arm_count':dict(sorted(durations.items())), 'peak':peak,
            'overlap_seconds':sum(value for key,value in durations.items() if key>=2)}


def model_evidence(directory, actor, thread, config, codex_home=None):
    if config.get('engine', 'codex') == 'claude':
        # CLI reports are useful observations but do not establish the effective
        # provider model or rule out remapping and auxiliary requests.
        turns=[]
        evidence=run_layout.path(directory,'engine_turns','claude')
        for path in evidence.glob('*-summary.json'):
            try:
                data=json.loads(path.read_text())
                if data.get('actor') != actor or data.get('session_id') != thread or not thread:
                    continue
                summary=(data.get('record') or {}).get('summary') or {}
                turns.append({'turn_id':data.get('turn_id'), 'reported_model':summary.get('reported_model'),
                              'status':data.get('status')})
            except (OSError, ValueError, AttributeError, TypeError):
                continue
        config_dir=run_layout.path(directory,'engine_config','claude')/'projects'
        transcripts=[p for p in session_glob(config_dir,thread+'.jsonl') if p.parent.parent==config_dir] if thread else []
        return {'thread_id':thread, 'turns':turns, 'verified':False,
                'native_subagent_calls':native_subagent_calls(transcripts),
                'source':'claude_host_reported_model_not_provider_identity'}
    turns=[]
    paths=native_codex_sessions(directory, thread, codex_home)
    for path in paths:
        with open_session(path) as stream:
            for line in stream:
                if '"turn_context"' not in line:continue
                record=json.loads(line)
                if record.get('type')=='turn_context':
                    value=record['payload'];turns.append({k:value.get(k) for k in ('turn_id','model','effort')})
    return {'thread_id':thread,'turns':turns,'native_subagent_calls':native_subagent_calls(paths),
            'verified':bool(turns) and all(t['model']==config['model'] and t['effort']==config['effort'] for t in turns)}


def export(directory, codex_home=None):
    directory=Path(directory).resolve();output=directory/'private/outputs'
    manifest=directory/'private/inputs/manifest.json'
    if not manifest.is_file() or json.loads(manifest.read_text()).get('schema_version')!=3 or not (directory/'private/state/runtime.sqlite').is_file():
        raise ValueError('Existing v3 run required; historical layouts are not migrated')
    store=RuntimeStore(directory/'private/state/runtime.sqlite')
    try:
        lifecycle=store.get('lifecycle')
        if lifecycle not in ('ended','interrupted','recovery_required'):
            raise ValueError('Do not export a final report for a running/prepared trial')
        events=store.events();actions=store.actions();agents=store.agents();config=store.get('config')
        start_sim_time=store.get('start_sim_time');run_id=store.get('run_id');robot_count=len(store.get('robots',[]))
        messages=[store._message(row) for row in store.db.execute('SELECT * FROM messages ORDER BY seq')]
        async_actions=sum('started_sim_s' in a and not external_wait(store,a) for a in actions.values())
        # A run continued after an unexpected exit (docs/running/continuation.md) counts as one trial.
        segments={'count':len(store.get('segments') or [{}]),'continued':store.get('segment',0)>0,
                  'downtime_s':store.get('downtime_s',0.),'segments':store.get('segments') or []}
        from robofrontier.runtime.segments import motion_dirs, process_summary
        segments['process']=process_summary(directory)
        # Every segment's motion recording, in order; their timelines are continuous.
        segments['motion']=[str(p.relative_to(directory)) for p in motion_dirs(directory)]
    finally:store.close()
    start=next((e for e in events if e['kind']=='START'),None)
    end=next((e for e in events if e['kind']=='TEAM_FINISH_PROPOSED'),None)
    starts={e['details']['action_id']:e['created_at'] for e in events if e['kind']=='ACTION_STARTED'}
    finishes={e['details']['action_id']:e['created_at'] for e in events if e['kind']=='ACTION_FINISHED'}
    models={}
    for actor,agent in agents.items():
        if agent['kind']=='manager':continue
        models[actor]=model_evidence(directory, actor, agent['thread_id'], config, codex_home)
    evaluation_path=output/'evaluation.json'
    evaluation=json.loads(evaluation_path.read_text()) if evaluation_path.exists() else None
    metric_evaluation=evaluation
    if metric_evaluation is None and (output/'interruption-evaluation.json').exists():
        metric_evaluation=json.loads((output/'interruption-evaluation.json').read_text()).get('evaluation')
    report={'lifecycle':lifecycle,'evaluation':evaluation,
            'host_metrics': export_metrics(directory, config.get('engine', 'codex')),
            'scope':'One run, potentially multiple native sessions; public initial information, RGB and robot feedback. No population or architecture superiority claim.',
            'topology':config['topology'],'robot_count':robot_count,
            'run_id':run_id,'start_sim_time_s':start_sim_time,
            'sim_seconds':end['details']['sim_time_s']-start_sim_time if end and start_sim_time is not None else None,
            'wall_seconds':end['created_at']-start['created_at'] if start and end else None,
            'actions_by_arm':dict(Counter(a['arm'] for a in actions.values())),
            'executed_actions_by_arm':dict(Counter(a['arm'] for a in actions.values() if 'started_sim_s' in a)),
            'unstarted_members':sum('started_sim_s' not in a for a in actions.values()),
            'action_status':dict(Counter(a['status'] for a in actions.values())),
            'messages':len(messages), 'turns_by_role':{a:len(v['turns']) for a,v in models.items()},
            'all_requested_models_verified':bool(models) and all(v['verified'] for v in models.values()),
            # Native sub-agents bypass robot delegate; any call needs review.
            'native_subagent_calls':{a:v['native_subagent_calls'] for a,v in models.items() if v.get('native_subagent_calls')},
            'native_subagent_review_required':any(v.get('native_subagent_calls') for v in models.values()),
            # The policy's shared lessons in this run: what it chose to record, entry by entry.
            'run_skills':run_skills(directory),
            # Engineering-only injected faults (robofrontier/runtime/fault_injection.py); never a scored trial.
            'fault_injection':json.loads((directory/'private/inputs/manifest.json').read_text()).get('fault_injection'),
            'segments':segments,
            'changed_inputs':verify_inputs(directory),
            'late_messages':sum(e['kind']=='LATE_MESSAGE_AFTER_FINISH' for e in events),
            'wait_returns':dict(Counter(e['details'].get('result',{}).get('wait_status') for e in events
                                if e['kind']=='TOOL_RETURN' and e['details'].get('op')=='wait_events')),
            'async_actions':async_actions,
            'interpretation':'Action overlap covers active tool executions, excluding idle pose/grasp holding. It does not establish independent useful work or an architecture advantage.'}
    if config.get('engine', 'codex') == 'claude':
        # The current Claude launcher only admits unqualified engineering
        # drafts. An evaluation is meaningful evidence, not qualification.
        report.update(engine='claude', benchmark_qualified=False,
                      qualification_reason='Claude engineering execution is not qualified for formal benchmark results')
    if isinstance(metric_evaluation,dict) and 'metrics' in metric_evaluation:
        report['task_metrics']={**metric_evaluation['metrics'],
            'robot_action_count':sum('started_sim_s' in a for a in actions.values()),
            'source':'final evaluation' if evaluation is not None else 'interruption snapshot; not a completed run'}
    if start and end:
        report['execution_occupancy']=occupancy([(starts[i],finishes[i]) for i in starts.keys() & finishes.keys()],start['created_at'],end['created_at'])
    snapshot=output/'runtime.json'
    if snapshot.exists():report['video']=json.loads(snapshot.read_text()).get('video')
    write_json(directory/'private/state/model-verification.json',models)
    write_json(output/'messages.json',messages);write_json(output/'report.json',report)
    lines=['# RoboFrontier run audit','',f"Lifecycle: {lifecycle}; goal evaluation: {evaluation}.",'',
           f"Wall time: {report['wall_seconds']} seconds; actions: {sum(report['actions_by_arm'].values())}; messages: {len(messages)}.",'',
           f"Requested model settings verified: {report['all_requested_models_verified']}; frozen input changes: {report['changed_inputs']}.",'',
           'Action overlap excludes idle holding. Interpret it alongside task progress and video; one pilot does not establish architectural superiority.']
    if config.get('engine', 'codex') == 'claude':
        lines[2:2]=['Claude engineering run: not qualified for formal benchmark scoring; do not report it as a scored result.','']
    if 'task_metrics' in report:
        lines+=['',f"Task metrics: {report['task_metrics']}."]
    (output/'report.md').write_text('\n'.join(lines)+'\n')
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('run_dir',type=Path)
    p.add_argument('--codex-home', type=Path, help='Explicit native session home; otherwise use collected mapping/batch marker/environment')
    args=p.parse_args()
    print(json.dumps(export(args.run_dir, args.codex_home),ensure_ascii=False,indent=2))
