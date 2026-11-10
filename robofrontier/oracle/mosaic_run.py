"""The Mosaic Oracle's run: one live trial, its review loop, and its execution strategies.

Serial witness scopes: Interpret complete serial witnesses, including recorded same-world repairs. Repair intervals are explicit serial barriers. Their physical commands remain in the recipe; an omitted goal_attempt never means the repaired goal is copied.

Equivalent replay: Fresh canonical L3 actuator execution of a qualified equivalent L2 recipe.

Source-bound concurrency: Private source-bound finite-job concurrency, with conservative dependencies. This is a bounded engineering strategy, not a policy API or optimal planner. Conflicting swept envelopes retain source order. Any number of independent ready scopes can run; physical feedback/evaluation remain authoritative.

Asynchronous concurrency: Single physics owner, independently polled finite Mosaic operations. Starts only the source plan's enabled nonconflicting operations. A shorter operation can enable its successor while unrelated arms are still executing. Known failures stop new admission and drain admitted work before owner review; uncertain execution is fenced and never replayed.

Parallel endpoint screens: Parallel, isolated nominal goal endpoint screens for Mosaic planning. Workers never access the live MjData or issue actions. Each reconstructs its own model and robot IK from an immutable trial scene and captured references. The owner retains responsibility for all physical and collision checks.

Streaming prefixes: Fresh native execution of immutable, completed Mosaic command prefixes. The source may still be running. Only complete recorded scopes covered by finalized motion chunks are candidates. They never constitute a full source qualification. Every target goal requires new native dynamics and evaluation.

Forward recovery and review: Mosaic-only, forward recovery in one live Trial and physics owner thread. File requests contain finite ordinary commands or named frozen reference calls. No Python is loaded from requests. Repeated reviews do not transfer ownership, reset the world, erase feedback, or change the physical evaluator.

Merged on 2026-11-11 from mosaic_source_scopes, mosaic_replay, mosaic_concurrency, mosaic_async,
mosaic_parallel, mosaic_stream and mosaic_run. Same-named entry points were renamed:
prepare_replay/execute_replay, execute_plan (serial) and execute_plan_async, execute_stream.
"""
from copy import deepcopy
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import re
import shutil
import time
from types import SimpleNamespace

import numpy as np
import mujoco

from ..media.mosaic_equivalence import check
from ..media.motion_recording import MotionReader
from ..tasks.evaluate import Monitor
from ..physics.robot_control import PandaArm, rotation_vector
from ..runtime.setup import write_json
from . import placement as placement_oracle
from ..tasks.config import physical_control_fingerprint
from ..tasks.provenance import environment_logic_manifest
from .trial import ProcessViolation, ReferenceStopped
from . import mosaic as reference
from .protocol import process_blocks, unresolved_robots


# ---- Serial witness scopes
def source_scopes(actions, events, final_assignments, object_names):
    initial=[a for a in actions if a['label']=='clear-idle-arms']
    if len(initial)!=1 or not actions or actions[0] is not initial[0]:
        raise ValueError('Require exactly one initial parking before manipulation')
    if any(any(r['status']!='completed' for r in a['results'].values()) for a in actions):
        raise ValueError('Source needs explicit treatment of failed actions, never blind replay')
    previous=actions[0]['end_sim_s']
    for a in actions[1:]:
        if a['start_sim_s']<previous-1e-8:raise ValueError('Require a serial physical source witness')
        previous=a['end_sim_s']
    seen={};scopes=[];cursor=1
    for event in events:
        kind=event['event']
        if kind not in ('goal_attempt','mosaic_resume_from_actual_progress'):continue
        barrier=kind!='goal_attempt'
        pairs=(dict(event['protected_assignments']) if barrier else {event['goal']:event['object']})
        if any(final_assignments.get(g)!=name for g,name in pairs.items()):
            raise ValueError('Source scope and final physical object pairing disagree')
        if barrier and any(pairs.get(g)!=name for g,name in seen.items()):
            raise ValueError('Repair marker lost an earlier completed pairing')
        added={g:name for g,name in pairs.items() if g not in seen}
        commands=[]
        while cursor<len(actions) and actions[cursor]['end_sim_s']<=event['sim_time_s']+1e-8:
            commands.append(actions[cursor]);cursor+=1
        if not commands:
            if added:raise ValueError('New physical goal has no recorded command prefix')
            continue
        robots=sorted({r for a in commands for r in a['commands']})
        scopes.append(dict(goal_id=f'@review-{len(scopes)}' if barrier else event['goal'],
            object=None if barrier else event['object'],objects=list(object_names) if barrier else [event['object']],
            path=robots if barrier else event['path'],robots=robots,barrier=barrier,
            expected_assignments=added,actions=commands,end_sim_s=event['sim_time_s']))
        seen.update(added)
    if cursor!=len(actions):raise ValueError('Unassigned trailing physical actions')
    if seen!=final_assignments:raise ValueError('Recorded scope markers do not cover every final goal')
    return initial[0],scopes


# ---- Equivalent replay
def prepare_replay(source,target):
    source=Path(source).resolve();target=Path(target).resolve()
    report=json.loads((source/'report.json').read_text());payload=(source/'actions.json').read_bytes();actions=json.loads(payload)
    if (not report.get('passed') or report.get('error') or report.get('unresolved_robot_actions') or
            report.get('failed_robot_actions')):raise ValueError('Require a complete clean L2 command witness')
    previous=0.
    for action in actions:
        if action['start_sim_s']<previous-1e-8 or any(r['status']!='completed' for r in action['results'].values()):
            raise ValueError('Sequential replay does not silently serialize overlapping/failed source actions')
        previous=action['end_sim_s']
    equivalence=check(source,target)
    if not equivalence['equivalent_for_command_candidate']:raise ValueError('L2/L3 physical equivalence failed: '+str(equivalence['differences']))
    ends=[json.loads(line) for line in (source/'trace.jsonl').read_text().splitlines() if '"event": "goal_attempt"' in line]
    jobs=[];cursor=0
    for action in actions:
        while cursor<len(ends) and action['start_sim_s']>=ends[cursor]['sim_time_s']-1e-8:cursor+=1
        event=ends[cursor] if cursor<len(ends) else None
        jobs.append(None if action['label']=='clear-idle-arms' or event is None else dict(goal_id=event['goal'],object=event['object'],path=event['path']))
    buffers=json.loads((source/'supply-plan.json').read_text())['table_buffers']
    return dict(source=str(source),source_report=report,actions=actions,jobs=jobs,buffers=buffers,equivalence=equivalence,
        actions_sha256=hashlib.sha256(payload).hexdigest(),scope='New live actuator execution with source inter-command waits; no qpos replay, success copying or checkpoint restoration')


def execute_replay(trial,recipe):
    report=recipe['source_report']
    if trial.physical_control_sha256!=report['physical_control_sha256'] or trial.environment_logic_sha256!=report['environment_logic_sha256']:
        raise ValueError('Equivalent replay controller/evaluator changed')
    trial.mosaic_edges={frozenset(row['robots']):np.asarray(row['position_m']) for row in recipe['buffers']}
    trial.parking_q={r:np.asarray(command[1]['joint_rad']) for r,command in recipe['actions'][0]['commands'].items()}
    trial.mosaic_protected_assignments={};previous=recipe['actions'][0]['start_sim_s'];count=0
    for index,action in enumerate(recipe['actions']):
        trial.mosaic_current_job=recipe['jobs'][index]
        trial.wait(max(0.,action['start_sim_s']-previous))
        commands=deepcopy(action['commands'])
        try:trial.execute('equivalent-'+action['label'],commands)
        finally:
            job=trial.mosaic_current_job
            for robot,(operation,parameters) in commands.items():
                if job and operation=='gripper' and parameters.get('mode')=='grasp' and trial.arms[robot].grasp_force is not None and trial.finger_contacts(robot,job['object']):
                    trial.held[robot]=job['object']
                if robot in trial.held and trial.arms[robot].grasp_force is None and trial.monitor.released(trial.monitor.geoms[trial.held[robot]]):
                    trial.held.pop(robot)
        previous=action['end_sim_s']
        current=trial.monitor.result().get('assignments',{})
        for goal,name in trial.mosaic_protected_assignments.items():
            if current.get(goal)!=name:raise RuntimeError('Equivalent replay disturbed completed pairing '+goal)
        trial.mosaic_protected_assignments=dict(current)
        if len(current)>count:
            count=len(current);print(f"{trial.task['id']} equivalent {count}/{len(trial.task['goals'])} validated",flush=True)
            callback=getattr(trial,'mosaic_after_goal',None)
            if callback is not None:callback(trial)
    trial.wait(max(0.,report['evaluation']['sim_time_s']-previous))
    trial.mosaic_current_job=None
    return dict(reference_placed=len(trial.monitor.result().get('assignments',{})),total_goals=len(trial.task['goals']),
        commissioning_only=False,fresh_canonical_command_replay=True)


# ---- Source-bound concurrency
def overlap(a,b,reserve=.02):
    """A separating coordinate proves these conservative boxes disjoint."""
    return bool(np.max(np.maximum(np.asarray(a[0])-b[1],np.asarray(b[0])-a[1]))<=2*reserve)


def dependencies(jobs):
    result=[]
    for j,job in enumerate(jobs):
        result.append([i for i,earlier in enumerate(jobs[:j])
            if (job.get('barrier') or earlier.get('barrier') or
                set(job['robots'])&set(earlier['robots']) or
                (job.get('object') is not None and job.get('object')==earlier.get('object')) or
                overlap(job['bounds_m'],earlier['bounds_m']))])
    return result


def ready_scopes(predecessors,completed,active=()):
    completed=set(completed);active=set(active)
    return [i for i,pred in enumerate(predecessors) if i not in completed and i not in active and set(pred)<=completed]


class ReadyFrontier:
    """Visit each dependency edge once, never rescan it each physics step."""
    def __init__(self,predecessors):
        self.remaining=[len(p) for p in predecessors]
        self.successors=[[] for _ in predecessors]
        for node,pred in enumerate(predecessors):
            for parent in pred:self.successors[parent].append(node)
        self.ready={i for i,n in enumerate(self.remaining) if n==0}
        self.admitted=set();self.completed=set()

    def claim_ready(self):
        result=list(self.ready);self.ready.clear();self.admitted.update(result)
        return result

    def complete(self,node):
        if node not in self.admitted or node in self.completed:
            raise ValueError('Completion does not match an admitted unfinished operation')
        self.completed.add(node)
        for child in self.successors[node]:
            self.remaining[child]-=1
            if self.remaining[child]==0:self.ready.add(child)


def build_plan(source,*,candidate_prefix=False,after_sim_s=None):
    source=Path(source).resolve();began=time.monotonic()
    report=json.loads((source/'report.json').read_text())
    qualified=report.get('passed') if not candidate_prefix else (report.get('source_prefix_only') and not report.get('passed'))
    if (not qualified or report.get('error') or report.get('unresolved_robot_actions') or
            report['evaluation']['violations']):raise ValueError('A complete clean physical source witness is required')
    if len(report['evaluation']['assignments'])!=report['evaluation']['total_goals']:
        raise ValueError('Every original source goal must have a physical assignment')
    events=[json.loads(line) for line in (source/'trace.jsonl').read_text().splitlines()]
    actions=json.loads((source/'actions.json').read_text())
    task=json.loads((source/'task.json').read_text())
    initial,scopes=source_scopes(actions,events,report['evaluation']['assignments'],[o['id'] for o in task['objects']])
    if after_sim_s is not None:scopes=[s for s in scopes if s['end_sim_s']>after_sim_s+1e-8]
    if not scopes:raise ValueError('No new complete command scope')
    # Reserve individual finite operations rather than a whole multi-arm job.
    # Object order retains the actual custody/staging chain; disjoint robots
    # can prepare/execute other jobs between its operations.
    last_nodes={};last_pairs={};jobs=[]
    for scope in scopes:
        for i,action in enumerate(scope['actions']):
            end=(scope['actions'][i+1]['start_sim_s'] if i+1<len(scope['actions']) else scope['end_sim_s'])
            jobs.append(dict(goal_id=scope['goal_id'],object=scope['object'],path=scope['path'],
                objects=scope['objects'],barrier=scope['barrier'],
                robots=sorted(action['commands']),actions=[action],end_sim_s=end,
                bounds_m=[np.full(3,np.inf),np.full(3,-np.inf)]))
        last_nodes[len(jobs)-1]=scope['goal_id']
        last_pairs[len(jobs)-1]=scope['expected_assignments']
    model=mujoco.MjModel.from_xml_path(str(source/'scene.xml'));data=mujoco.MjData(model)
    task=json.loads((source/'task.json').read_text());monitor=Monitor(SimpleNamespace(model=model,data=data,task=task,arms=task['arms']))
    physical=(model.geom_contype!=0)|(model.geom_conaffinity!=0)
    geom_sets=[]
    for job in jobs:
        ids={g for name in job['objects'] for g in monitor.geoms[name]}
        for robot in job['robots']:
            ids.update(np.flatnonzero((monitor.geom_owner==monitor.robot_index[robot])&physical))
        geom_sets.append(np.asarray(sorted(ids),int))
    index=0;frames=0
    for stamp,qpos in MotionReader(source/'motion').frames():
        if candidate_prefix and stamp>report['source_prefix_cut_sim_s']+1e-8:break
        if after_sim_s is not None and stamp<after_sim_s:continue
        while index+1<len(jobs) and stamp>jobs[index]['end_sim_s']:
            index+=1
        data.qpos[:]=qpos;mujoco.mj_kinematics(model,data)
        ids=geom_sets[index];rotation=data.geom_xmat[ids].reshape(-1,3,3)
        center=data.geom_xpos[ids]+np.einsum('nij,nj->ni',rotation,model.geom_aabb[ids,:3])
        half=np.einsum('nij,nj->ni',abs(rotation),model.geom_aabb[ids,3:])
        box=jobs[index]['bounds_m'];box[0]=np.minimum(box[0],np.min(center-half,axis=0));box[1]=np.maximum(box[1],np.max(center+half,axis=0))
        frames+=1
        if frames%30000==0:print(json.dumps(dict(phase='concurrency-envelope-planning',frames=frames,scope=index+1)),flush=True)
    for job in jobs:job['bounds_m']=[v.tolist() for v in job['bounds_m']]
    pred=dependencies(jobs)
    critical=[0.]*len(jobs)
    durations=[j['end_sim_s']-j['actions'][0]['start_sim_s'] for j in jobs]
    critical=list(durations)
    for j in range(len(jobs)-1,-1,-1):
        for i in pred[j]:critical[i]=max(critical[i],durations[i]+critical[j])
    return dict(source=str(source),case_id=report['case_id'],jobs=jobs,predecessors=pred,critical_path_weights=critical,
        table_buffers=json.loads((source/'supply-plan.json').read_text())['table_buffers'],
        initial_commands=initial['commands'],source_physical_control_sha256=report['physical_control_sha256'],
        source_environment_logic_sha256=report['environment_logic_sha256'],source_scene_bundle_sha256=report['scene_bundle_sha256'],
        source_report_sha256=hashlib.sha256((source/'report.json').read_bytes()).hexdigest(),
        source_assisted=bool(report.get('assisted') or report.get('llm_used')),
        source_actions_sha256=hashlib.sha256((source/'actions.json').read_bytes()).hexdigest(),
        last_goal_nodes=last_nodes,last_goal_assignments=last_pairs,
        total_goals=sum(len(s['expected_assignments']) for s in scopes),source_prefix_only=bool(candidate_prefix),
        repair_barrier_count=sum(s['barrier'] for s in scopes),planning_granularity='ordinary_finite_action',
        frames_screened=frames,planning_wall_s=time.monotonic()-began,reserve_per_scope_m=.02,
        scope='Source-order dependencies for shared robots, object custody or overlapping sampled operation envelopes; no continuous safety or optimality certificate')


def execute_plan(trial,plan):
    if (trial.physical_control_sha256!=plan['source_physical_control_sha256'] or
            trial.environment_logic_sha256!=plan['source_environment_logic_sha256'] or
            trial.source_bundle['sha256']!=plan.get('target_scene_bundle_sha256',plan['source_scene_bundle_sha256'])):
        raise ValueError('Concurrent world must match source control/evaluator/assets')
    trial.execute('clear-idle-arms',deepcopy(plan['initial_commands']));trial.wait(.2)
    trial.parking_q={r:np.asarray(c[1]['joint_rad']) for r,c in plan['initial_commands'].items()}
    trial.mosaic_edges={frozenset(row['robots']):np.asarray(row['position_m']) for row in plan.get('table_buffers',[])}
    frontier=ReadyFrontier(plan['predecessors'])
    completed=frontier.completed;active={};peak=0;rounds=0;qualified=set();started={}
    jobs=plan['jobs'];trial.mosaic_protected_assignments={}
    last_goal_nodes={int(i):goal for i,goal in plan['last_goal_nodes'].items()}
    while len(completed)<len(jobs):
        ready=frontier.claim_ready()
        for index in sorted(ready,key=lambda i:-plan['critical_path_weights'][i]):
            active[index]=0
            job=jobs[index];started[job['goal_id']]=dict(goal_id=job['goal_id'],object=job['object'],path=job['path'])
        if not active:raise RuntimeError('No enabled scope in acyclic concurrency plan')
        peak=max(peak,len(active))
        trial.mosaic_active_jobs=list(started.values())
        trial.event('mosaic_concurrent_frontier',active=trial.mosaic_active_jobs,completed=len(completed))
        commands={};owners={}
        for i,cursor in active.items():
            for robot,command in jobs[i]['actions'][cursor]['commands'].items():
                if robot in commands:raise RuntimeError('Conflicting robot reservation in concurrency plan')
                commands[robot]=deepcopy(command);owners[robot]=i
        try:
            trial.execute(f'mosaic-concurrent-{rounds:04d}',commands)
        finally:
            # Bookkeeping follows measured grasp/release, never attaches a load.
            for robot,(operation,parameters) in commands.items():
                name=jobs[owners[robot]]['object']
                if name is not None and operation=='gripper' and parameters.get('mode')=='grasp' and trial.arms[robot].grasp_force is not None and trial.finger_contacts(robot,name):
                    trial.held[robot]=name
                if robot in trial.held and trial.arms[robot].grasp_force is None and trial.monitor.released(trial.monitor.geoms[trial.held[robot]]):
                    trial.held.pop(robot)
        rounds+=1;delays=[];finished=[]
        for i,cursor in active.items():
            actions=jobs[i]['actions'];end=actions[cursor]['end_sim_s'];cursor+=1;active[i]=cursor
            if cursor==len(actions):delays.append(max(0.,jobs[i]['end_sim_s']-end));finished.append(i)
            else:delays.append(max(0.,actions[cursor]['start_sim_s']-end))
        trial.wait(max(delays or [0.]))
        current=trial.monitor.result().get('assignments',{})
        for goal,name in trial.mosaic_protected_assignments.items():
            if current.get(goal)!=name:raise RuntimeError('Concurrent motion disturbed completed pairing '+goal)
        for i in finished:
            frontier.complete(i);active.pop(i)
            if i in last_goal_nodes:
                goal=last_goal_nodes[i]
                pairs=plan.get('last_goal_assignments',{}).get(str(i),plan.get('last_goal_assignments',{}).get(i,{goal:jobs[i]['object']}))
                if any(current.get(g)!=name for g,name in pairs.items()):
                    raise RuntimeError('Concurrent finite command scope did not satisfy original evaluator '+goal)
                qualified.update(pairs);started.pop(goal,None)
                trial.mosaic_protected_assignments=dict(current)
                print(f"{trial.task['id']} concurrent {len(qualified)}/{plan['total_goals']} validated",flush=True)
                callback=getattr(trial,'mosaic_after_goal',None)
                if callback is not None:callback(trial)
    trial.mosaic_active_jobs=[];trial.wait(2.4)
    return dict(reference_placed=len(qualified),total_goals=len(trial.task['goals']),
        commissioning_only=False,concurrent_scope_peak=peak,concurrent_rounds=rounds,
        strategy='Conservative source-bound dependency list scheduling; not proven optimal')


# ---- Asynchronous concurrency
def execute_plan_async(trial,plan,*,initialize=True):
    if (trial.physical_control_sha256!=plan['source_physical_control_sha256'] or
            trial.environment_logic_sha256!=plan['source_environment_logic_sha256'] or
            trial.source_bundle['sha256']!=plan.get('target_scene_bundle_sha256',plan['source_scene_bundle_sha256'])):
        raise ValueError('Async world must match source control/evaluator/assets')
    if initialize:
        trial.execute('clear-idle-arms',deepcopy(plan['initial_commands']));trial.wait(.2)
        trial.mosaic_concurrency_started_sim_s=trial.time
        trial.parking_q={r:np.asarray(c[1]['joint_rad']) for r,c in plan['initial_commands'].items()}
    elif not hasattr(trial,'parking_q') or trial.held or any(a.job is not None or a.grasp_force is not None for a in trial.arms.values()):
        raise ValueError('Continuation requires known idle released arms; never reset or repark')
    trial.mosaic_edges={frozenset(row['robots']):np.asarray(row['position_m']) for row in plan.get('table_buffers',[])}
    jobs=plan['jobs'];last_nodes={int(i):g for i,g in plan['last_goal_nodes'].items()}
    if any(len(j['actions'])!=1 for j in jobs):raise ValueError('Async admission requires operation-level nodes')
    frontier=ReadyFrontier(plan['predecessors'])
    completed=frontier.completed;active={};waiting={};qualified=set();started={};failures=[];peak=0
    if initialize:trial.mosaic_protected_assignments={}
    lower=np.asarray(trial.task['workspace_world_m']['lower']);upper=np.asarray(trial.task['workspace_world_m']['upper'])

    def bookkeeping(robot,command,node):
        operation,parameters=command;name=jobs[node]['object']
        if name is not None and operation=='gripper' and parameters.get('mode')=='grasp' and trial.arms[robot].grasp_force is not None and trial.finger_contacts(robot,name):
            trial.held[robot]=name
        if robot in trial.held and trial.arms[robot].grasp_force is None and trial.monitor.released(trial.monitor.geoms[trial.held[robot]]):
            trial.held.pop(robot)

    while len(completed)<len(jobs):
        trial.check_stop()
        current=trial.monitor.result().get('assignments',{})
        for goal,name in trial.mosaic_protected_assignments.items():
            if current.get(goal)!=name:
                failures.append('Async motion disturbed completed pairing '+goal)
        for node,ready_time in list(waiting.items()):
            if trial.time+1e-9<ready_time:continue
            waiting.pop(node);frontier.complete(node)
            if node in last_nodes:
                goal=last_nodes[node]
                pairs=plan.get('last_goal_assignments',{}).get(str(node),plan.get('last_goal_assignments',{}).get(node,{goal:jobs[node]['object']}))
                if any(current.get(g)!=name for g,name in pairs.items()):
                    failures.append('Async scope did not satisfy original evaluator '+goal)
                else:
                    qualified.update(pairs);started.pop(goal,None)
                    trial.mosaic_protected_assignments=dict(current)
                    print(f"{trial.task['id']} async {len(qualified)}/{plan['total_goals']} validated",flush=True)
                    callback=getattr(trial,'mosaic_after_goal',None)
                    if callback is not None:callback(trial)
        trial.mosaic_active_jobs=list(started.values())
        if failures and not active:
            raise RuntimeError('Known async failure after draining admitted work: '+failures[0])
        if not failures:
            ready=frontier.claim_ready()
            prepared={};robots=set()
            try:
                for node in sorted(ready,key=lambda i:-plan['critical_path_weights'][i]):
                    command=jobs[node]['actions'][0]['commands'];validated={}
                    for robot,(operation,parameters) in command.items():
                        if robot in robots or trial.arms[robot].job is not None:
                            raise RuntimeError('Source dependency plan admitted a busy robot')
                        validated[robot]=trial.arms[robot].validate(operation,parameters,trial.cfg,lower,upper)
                        robots.add(robot)
                    prepared[node]=validated
            except (ValueError,RuntimeError) as error:
                failures.append('Admission: '+str(error));prepared={}
                trial.event('mosaic_async_admission_rejected',reason=str(error))
            for node,validated in prepared.items():
                job=jobs[node];command=deepcopy(job['actions'][0]['commands']);label=f"{plan.get('operation_prefix','mosaic-async')}-{node:04d}"
                active[node]=dict(commands=command,label=label,start_sim_s=trial.time,pending=set(command),results={})
                started[job['goal_id']]=dict(goal_id=job['goal_id'],object=job['object'],path=job['path'])
                trial.event('action_start',label=label,commands=command)
                for robot,parameters in validated.items():
                    call_id=f'{label}-{robot}'
                    try:trial.arms[robot].start(call_id,parameters,trial.time)
                    except Exception as error:
                        result=dict(call_id=call_id,status='uncertain',reason='Async start acknowledgement failed: '+str(error))
                        trial.actions.append(dict(label=label,commands=command,results={robot:result},start_sim_s=trial.time,end_sim_s=trial.time))
                        trial.event('mosaic_async_unknown_start',robot=robot,result=result)
                        raise RuntimeError('Unknown async startup; original IDs retained') from error
            peak=max(peak,len(active))
            trial.mosaic_active_jobs=list(started.values())
        if not active and not waiting and len(completed)<len(jobs):
            raise RuntimeError('No enabled async operation')
        if len(completed)==len(jobs):break
        trial.step()
        if trial.tick%trial.stride:continue
        for node,record in list(active.items()):
            for robot in list(record['pending']):
                result=trial.arms[robot].poll(trial.time,15)
                if result is None:continue
                record['results'][robot]=deepcopy(result);record['pending'].remove(robot)
                bookkeeping(robot,record['commands'][robot],node)
                if result['status']=='uncertain':
                    trial.actions.append(dict(label=record['label'],commands=record['commands'],results=deepcopy(record['results']),start_sim_s=record['start_sim_s'],end_sim_s=trial.time))
                    trial.event('action_end',label=record['label'],results=record['results'])
                    raise RuntimeError('Unknown async execution; no replay permitted')
                if result['status']!='completed':failures.append(str(result))
            if record['pending']:continue
            trial.actions.append(dict(label=record['label'],commands=record['commands'],results=record['results'],start_sim_s=record['start_sim_s'],end_sim_s=trial.time))
            trial.event('action_end',label=record['label'],results=record['results'])
            active.pop(node)
            source=jobs[node]['actions'][0]
            waiting[node]=trial.time+jobs[node].get('wait_after_s',max(0.,jobs[node]['end_sim_s']-source['end_sim_s']))
    trial.mosaic_active_jobs=[];trial.wait(2.4)
    return dict(reference_placed=len(qualified),total_goals=len(trial.task['goals']),commissioning_only=False,
        concurrent_operation_peak=peak,strategy='Independent native controller polling with source-bound dependencies; not proven optimal')


# ---- Parallel endpoint screens
_scratch = None
_init_error = None


class _Scratch:
    def screen_ik(self, robot, target, rotation, seed=None):
        arm = self.arms[robot]
        q, error = arm.ik.solve(np.asarray(target), rotation,
                                arm.qref if seed is None else seed, 220)
        _, reached = arm.ik.pose(q)
        return q if error < .0018 and np.linalg.norm(rotation_vector(rotation, reached)) < .02 else None


def _initialize(scene, task, refs, env=None, qpos=None, home=None):
    global _scratch, _init_error
    _scratch = None
    _init_error = None
    try:
        _scratch = _build_scratch(scene, task, refs, env, qpos, home)
    except Exception as error:
        # Pool otherwise repeatedly respawns a failing initializer forever.
        # Report the failure through the first submitted work item instead.
        _init_error = f'{type(error).__name__}: {error}'


def _build_scratch(scene, task, refs, env=None, qpos=None, home=None):
    scratch = _Scratch()
    scratch.task = task
    scratch.model = mujoco.MjModel.from_xml_path(scene)
    scratch.data = mujoco.MjData(scratch.model)
    mujoco.mj_resetDataKeyframe(scratch.model, scratch.data, scratch.model.key('initial').id)
    if qpos is not None:
        scratch.data.qpos[:] = qpos
    mujoco.mj_forward(scratch.model, scratch.data)
    scratch.arms = {name: PandaArm(scratch.model, scratch.data, name) for name in refs}
    for name, ref in refs.items():
        scratch.arms[name].qref = np.asarray(ref, dtype=float)
    scratch.env = env
    scratch.home_q = {name: np.asarray(q, dtype=float) for name, q in (home or {}).items()}
    return scratch


def _require_scratch():
    if _init_error is not None:
        raise RuntimeError('Mosaic planning worker initialization failed: '+_init_error)
    if _scratch is None:
        raise RuntimeError('Mosaic planning worker has not initialized')


def _screen(goal):
    _require_scratch()
    original = _scratch.task
    _scratch.task = dict(original, goals=[goal])
    try:
        try:
            result = placement_oracle.goal_coverage(_scratch)[goal['goal_id']]
        except RuntimeError as error:
            if not str(error).startswith('No candidate goal approach/seat/withdraw endpoints '):
                raise
            result = None
        return goal['goal_id'], result
    finally:
        _scratch.task = original


def _screen_pickup(item):
    _require_scratch()
    from .mosaic import pickup_endpoint_candidates
    original = _scratch.env
    _scratch.env = dict(original, objects=[item])
    try:
        return item['id'], pickup_endpoint_candidates(_scratch)[item['id']]
    finally:
        _scratch.env = original


def _parallel_map(trial, workers, items, fn, phase):
    count = min(len(items), os.cpu_count() or 1) if workers == 0 else min(len(items), workers)
    if count < 1:
        raise ValueError('Planning workers must be nonnegative and goals must be present')
    refs = {name: arm.qref.tolist() for name, arm in trial.arms.items()}
    started = time.monotonic()
    last_progress = started
    last_item = None
    results = {}
    path = trial.directory / 'planning-status.json'
    def publish(state, error=None):
        write_json(path, dict(phase=phase, state=state, completed=len(results), total=len(items),
            workers=count, updated_at_unix_s=time.time(), elapsed_s=time.monotonic()-started,
            seconds_since_progress=time.monotonic()-last_progress, last_completed_item=last_item,
            error=error))
        trial._heartbeat('planning_'+phase)
    publish('running')
    pool = multiprocessing.get_context('spawn').Pool(count, initializer=_initialize,
        initargs=(str(trial.directory/'scene.xml'), trial.task, refs,
                  trial.env, trial.data.qpos.copy(),
                  {name: q.tolist() for name, q in trial.home_q.items()}))
    worker_pids = {worker.pid for worker in pool._pool}
    try:
        pending = pool.imap_unordered(fn, items, chunksize=1)
        while len(results) < len(items):
            trial.check_stop()
            try:
                name, options = pending.next(timeout=1.)
                results[name] = options
                last_progress = time.monotonic()
                last_item = name
            except multiprocessing.TimeoutError:
                pass
            # multiprocessing.Pool silently replaces a crashed process but
            # can lose its in-flight item forever.  No workers are configured
            # to retire normally; a changed PID is therefore a failure.
            if {worker.pid for worker in pool._pool} != worker_pids:
                raise RuntimeError('Mosaic planning worker exited unexpectedly; inspect worker logs')
            publish('running')
        pool.close()
        pool.join()
    except BaseException as error:
        pool.terminate()
        pool.join()
        publish('interrupted',f'{type(error).__name__}: {error}')
        raise
    publish('complete')
    return results


def nominal_goal_coverage(trial, workers):
    """Return nominal candidates or None when original fallback is needed."""
    goals = trial.task['goals']
    results = _parallel_map(trial, workers, goals, _screen, 'goal_endpoints')
    if any(results[g['goal_id']] is None for g in goals):
        return None
    return {g['goal_id']: results[g['goal_id']] for g in goals}


def pickup_coverage(trial, workers):
    """Return the same finite pickup endpoint map using isolated snapshots."""
    objects = trial.env['objects']
    results = _parallel_map(trial, workers, objects, _screen_pickup, 'pickup_endpoints')
    return {item['id']: results[item['id']] for item in objects}


# ---- Streaming prefixes
MARKERS=('goal_attempt','mosaic_resume_from_actual_progress')


def review_deliberation(plan,events):
    """Schedule fresh candidates without copying long human thinking pauses.

    Native actions and ordinary explicit settling remain intact. Within a
    resolved source review, replace only long idle gaps with 2.4s of settling.
    Source timing/envelopes remain archived, and new dynamics must still pass.
    """
    intervals=[];opened={}
    for e in events:
        if e['event']=='mosaic_review_opened':opened[e['review_id']]=e['sim_time_s']
        elif e['event']=='mosaic_review_resumed':
            start=opened.pop(e['review_id'],None)
            if start is None:raise ValueError('Resolved source review has no recorded opening')
            intervals.append((start,e['sim_time_s']))
    saved=0.;changes=[]
    for i,job in enumerate(plan['jobs']):
        start=job['actions'][0]['end_sim_s'];end=job['end_sim_s'];gap=max(0.,end-start)
        reviewed=sum(max(0.,min(end,b)-max(start,a)) for a,b in intervals)
        if reviewed<=5.:continue
        delay=gap-reviewed+2.4;job['wait_after_s']=max(0.,delay);saved+=gap-delay
        changes.append(dict(node=i,source_gap_s=gap,target_settle_s=delay))
    plan['review_deliberation_schedule']=dict(saved_source_idle_s=saved,changes=changes,
        scope='Fresh candidate scheduling only; native command protection and whole-task timing policy unchanged')
    return plan


def completed_prefix(events,available_until,after_sim_s=-1.,max_new_goals=24,previous_pairs=None):
    """Choose an immutable completed boundary; ignore an in-flight tail."""
    pairs={};chosen=None;old=previous_pairs or {}
    for index,e in enumerate(events):
        if e['sim_time_s']>available_until+1e-8:break
        if e['event']=='goal_attempt':pairs[e['goal']]=e['object']
        elif e['event']=='mosaic_resume_from_actual_progress':pairs.update(e['protected_assignments'])
        else:continue
        if any(pairs.get(g)!=name for g,name in old.items()):
            # Before the previous cut, its later goals need not exist yet.
            if e['sim_time_s']>after_sim_s+1e-8:raise ValueError('Source prefix lost an already consumed pairing')
        if e['sim_time_s']<=after_sim_s+1e-8:continue
        if len(set(pairs)-set(old))>max_new_goals:break
        chosen=(index,e['sim_time_s'],dict(pairs))
    if chosen is None:return None
    index,cut,pairs=chosen;selected=events[:index+1]
    actions=[];pending=None
    for e in selected:
        if e['event']=='action_start':
            if pending is not None:raise ValueError('Prefix source contains overlapping action batches')
            pending=dict(label=e['label'],commands=e['commands'],start_sim_s=e['sim_time_s'])
        elif e['event']=='action_end':
            if pending is None or pending['label']!=e['label']:raise ValueError('Prefix action acknowledgement does not match its original start')
            if any(r['status']!='completed' for r in e['results'].values()):
                raise ValueError('Failed or uncertain source actions need explicit owner review')
            pending.update(results=e['results'],end_sim_s=e['sim_time_s']);actions.append(pending);pending=None
    if pending is not None:raise ValueError('Completed source marker contains unresolved execution')
    return dict(cut=cut,assignments=pairs,actions=actions,events=selected)


def snapshot(source,destination,*,after_sim_s=-1.,previous_pairs=None,max_new_goals=24):
    """Capture source evidence only, with no physics step or state restoration."""
    source=Path(source).resolve();destination=Path(destination)
    status=json.loads((source/'runner-status.json').read_text())
    if status['evaluation']['violations']:raise ValueError('Source has retained physical violations')
    reader=MotionReader(source/'motion')
    if not reader.meta['chunks']:return None
    raw=(source/'trace.jsonl').read_bytes();lines=raw.splitlines(keepends=True)
    events=[json.loads(line) for line in lines if line.endswith(b'\n')]
    prefix=completed_prefix(events,reader.meta['chunks'][-1]['end_sim_s'],after_sim_s,max_new_goals,previous_pairs)
    if prefix is None:return None
    destination.mkdir(parents=True,exist_ok=False)
    for name in ('scene.xml','task.json','environment.json','supply-plan.json'):
        shutil.copyfile(source/name,destination/name)
    os.symlink(source/'assets',destination/'assets',target_is_directory=True)
    motion=destination/'motion';motion.mkdir();os.symlink(source/'motion/source',motion/'source',target_is_directory=True)
    meta=deepcopy(reader.meta)
    # Each XOR chunk contains its own preceding full base, so a later interval
    # is independently decodable without copying earlier motion states.
    meta['chunks']=[c for c in meta['chunks'] if c['end_sim_s']>=after_sim_s and c['start_sim_s']<=prefix['cut']]
    for chunk in meta['chunks']:os.link(source/'motion'/chunk['file'],motion/chunk['file'])
    meta.update(status='prefix_candidate',frames=sum(c['frames'] for c in meta['chunks']))
    write_json(motion/'stream.json',meta)
    (destination/'trace.jsonl').write_text(''.join(json.dumps(e)+'\n' for e in prefix['events']))
    write_json(destination/'actions.json',prefix['actions'])
    task=json.loads((source/'task.json').read_text());cfg=json.loads((source/'executor-source/effective-harness.json').read_text())
    hashes={str(p.relative_to(source/'executor-source')):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (source/'executor-source').rglob('*.py')}
    report=dict(case_id=task['id'],passed=False,source_prefix_only=True,source_prefix_cut_sim_s=prefix['cut'],
        evaluation=dict(assignments=prefix['assignments'],total_goals=len(prefix['assignments']),violations=[]),
        physical_control_sha256=physical_control_fingerprint(hashes,cfg),
        environment_logic_sha256=environment_logic_manifest(hashes,task)['sha256'],
        scene_bundle_sha256=json.loads((source/'source-assets.json').read_text())['sha256'],
        assisted=any(e['event']=='mosaic_review_request' and e.get('assisted') for e in prefix['events']),
        scope='Incomplete-source command candidate only; never source or target task qualification')
    write_json(destination/'report.json',report)
    manifest=dict(source=str(source),world_id=status['world_id'],case_id=task['id'],
        source_executor_manifest_sha256=hashlib.sha256((source/'executor-launch.json').read_bytes()).hexdigest(),
        captured_trace_sha256=hashlib.sha256(raw).hexdigest(),selected_trace_sha256=hashlib.sha256((destination/'trace.jsonl').read_bytes()).hexdigest(),
        cut_sim_s=prefix['cut'],after_sim_s=after_sim_s,source_assignments=prefix['assignments'],
        source_phase_at_capture=status['phase'],full_source_passed=False,full_target_passed=False,
        scope=report['scope'])
    write_json(destination/'prefix-manifest.json',manifest)
    return manifest


def execute_stream(trial,source,equivalence,*,max_goals=None,prefix_goals=24,finish_after_source=False):
    if not equivalence['equivalent_for_command_candidate']:raise ValueError('Streaming requires exact physical input equivalence')
    source=Path(source).resolve();identity=json.loads((source/'runner-status.json').read_text())['world_id']
    original_manifest=hashlib.sha256((source/'executor-launch.json').read_bytes()).hexdigest()
    target_bundle=trial.source_bundle['sha256'];target_count=max_goals or len(trial.task['goals'])
    after=-1.;pairs={};chunk=0;peak=0;first=True
    trial.mosaic_stream_summary=dict(source=str(source),prefixes=[],source_assisted=False,
        scope='New actuator dynamics from completed source prefixes; source may be incomplete; target evaluation remains independent')
    write_json(trial.directory/'physical-equivalence.json',equivalence)
    while len(trial.monitor.result().get('assignments',{}))<target_count:
        trial.check_stop();status=json.loads((source/'runner-status.json').read_text())
        if status['world_id']!=identity or hashlib.sha256((source/'executor-launch.json').read_bytes()).hexdigest()!=original_manifest:
            raise ValueError('Streaming source physical owner or frozen executor changed')
        path=trial.directory/'source-prefixes'/f'prefix-{chunk:04d}'
        manifest=snapshot(source,path,after_sim_s=after,previous_pairs=pairs,
            max_new_goals=min(prefix_goals,target_count-len(pairs)))
        if manifest is None:
            if status['phase'] not in ('running','review'):
                if finish_after_source:
                    report=json.loads((source/'report.json').read_text())
                    if (report.get('failed_robot_actions') or report.get('unresolved_robot_actions') or
                            report['evaluation']['violations']):raise RuntimeError('Closed source native feedback needs owner review')
                    require_known_idle(trial)
                    if trial.held or any(a.grasp_force is not None for a in trial.arms.values()):
                        raise RuntimeError('Source handoff requires physically released arms')
                    trial.mosaic_stream_summary['source_terminal']=dict(phase=status['phase'],error=report.get('error'),
                        source_passed=report.get('passed'),target_progress_at_handoff=len(trial.monitor.result().get('assignments',{})))
                    write_json(trial.directory/'streaming-summary.json',trial.mosaic_stream_summary)
                    trial.event('mosaic_stream_source_exhausted',source_phase=status['phase'],source_error=report.get('error'),
                        scope='Retained source commands consumed; continue new target world from actual progress, never copy source outcome')
                    from .mosaic import solve
                    return solve(trial,resume=not first,motion_profile=trial.mosaic_motion_profile)
                raise RuntimeError('Source ended before a new usable complete prefix: '+status['phase'])
            # Waiting is actual forward simulation. Previously accepted goals
            # remain protected; no held payload or active action is abandoned.
            if trial.held or any(a.job is not None or a.grasp_force is not None for a in trial.arms.values()):
                raise RuntimeError('Source wait requires actual released, known idle arms')
            trial.wait(.2)
            current=trial.monitor.result().get('assignments',{})
            if any(current.get(g)!=name for g,name in getattr(trial,'mosaic_protected_assignments',{}).items()):
                raise RuntimeError('Streaming wait disturbed a completed pairing')
            time.sleep(.2);continue
        plan=build_plan(path,candidate_prefix=True,after_sim_s=None if first else after)
        review_deliberation(plan,[json.loads(line) for line in (path/'trace.jsonl').read_text().splitlines()])
        plan['target_scene_bundle_sha256']=target_bundle
        plan['operation_prefix']=f'mosaic-stream-{chunk:04d}'
        write_json(path/'concurrency-plan.json',plan)
        trial.event('mosaic_stream_prefix_admitted',manifest=str(path/'prefix-manifest.json'),
            source_cut_sim_s=manifest['cut_sim_s'],new_candidate_goals=plan['total_goals'],source_prefix_only=True)
        result=execute_plan_async(trial,plan,initialize=first)
        peak=max(peak,result['concurrent_operation_peak']);first=False;after=manifest['cut_sim_s'];pairs=manifest['source_assignments'];chunk+=1
        trial.mosaic_stream_summary['prefixes'].append(dict(path=str(path),source_cut_sim_s=after,candidate_goals=len(pairs),
            target_actual_goals=len(trial.monitor.result().get('assignments',{})),peak=result['concurrent_operation_peak'],
            review_deliberation_saved_s=plan['review_deliberation_schedule']['saved_source_idle_s']))
        trial.mosaic_stream_summary['source_assisted']|=plan['source_assisted']
        write_json(trial.directory/'streaming-summary.json',trial.mosaic_stream_summary)
    return dict(reference_placed=len(trial.monitor.result().get('assignments',{})),total_goals=len(trial.task['goals']),
        commissioning_only=max_goals is not None,streamed_prefixes=chunk,concurrent_operation_peak=peak,
        strategy='Independent native execution of source prefix dependencies; not a global optimum')


# ---- Forward recovery and review
def require_known_idle(trial):
    if getattr(trial,'physics_failure',None):
        raise RuntimeError('Invalid physical trajectory cannot be repaired as valid evidence')
    if process_blocks(trial) and trial.monitor.violations:
        raise ProcessViolation('Retained process violation prevents canonical continuation')
    historical_unknown=any(result.get('status') == 'uncertain' for action in trial.actions
                           for result in action.get('results', {}).values())
    if unresolved_robots(trial) or (process_blocks(trial) and historical_unknown):
        raise RuntimeError('Unknown or in-flight execution requires original-action review')


class MosaicReview:
    def __init__(self, trial, *, review_wall_s=None, publish=None, on_enter=None):
        self.trial = trial
        self.directory = Path(trial.directory)/'review'
        for name in ('requests', 'results', 'rejected'):
            (self.directory/name).mkdir(parents=True, exist_ok=True)
        self.world_id = hashlib.sha256(str(Path(trial.directory).resolve()).encode()).hexdigest()[:24]
        self.review_wall_s = review_wall_s
        self.epoch = 0
        self.history, self.requests, self.seen_files = [], {}, {}
        self.assisted = False
        self.publish = publish if publish is not None else self.observation
        self.on_enter = on_enter

    def observation(self):
        t = self.trial
        write_json(self.directory/'observation.json', dict(
            world_id=self.world_id, review_id=self.epoch, sim_time_s=t.time,
            updated_at_unix_s=time.time(), held=dict(t.held),
            job=getattr(t, 'mosaic_current_job', None),
            active_jobs=getattr(t,'mosaic_active_jobs',[]),
            evaluation=t.monitor.result(),
            robots={r:a.observe() for r,a in t.arms.items()},
            objects={o['id']:dict(position_m=t.data.body(o['id']).xpos.tolist(),
                rotation=t.data.body(o['id']).xmat.reshape(3,3).tolist()) for o in t.env['objects']},
            last_actions=t.actions[-3:],
            scope='Private privileged engineering observation; never policy input'))

    def _status(self, phase):
        write_json(self.trial.directory/'runner-status.json', dict(
            phase=phase, world_id=self.world_id, review_id=self.epoch,
            simulation_time_s=self.trial.time, updated_at_unix_s=time.time(),
            review_history=self.history, evaluation=self.trial.monitor.result()))

    def _reconcile_released(self, robot):
        t=self.trial;name=t.held.get(robot)
        if name is None:return
        arm=t.arms[robot]
        width=float(arm.observe()['gripper_width_m'])
        if (arm.grasp_force is not None or not np.isfinite(width) or
                (process_blocks(t) and width<t.task['cube_size_m']+.003) or
                not t.monitor.released(t.monitor.geoms[name])):
            raise ValueError('Payload is not physically released '+robot+'/'+name)
        velocity=t.monitor.velocity(t.model.body(name).id)
        if np.linalg.norm(velocity[:3])>.1 or np.linalg.norm(velocity[3:])>.01:
            raise ValueError('Released payload is not stable '+name)
        geoms=set(t.monitor.geoms[name]);supported=False
        for contact in t.data.contact:
            a,b=map(int,contact.geom)
            for own,other in ((a,b),(b,a)):
                if own in geoms and contact.dist<=.0005 and (t.model.geom(other).name or '').startswith(('table_','pocket_')):
                    supported=True
        if not supported:raise ValueError('No actual tabletop support for '+name)
        t.held.pop(robot)
        getattr(t,'mosaic_tilted_grasps',{}).pop(robot,None)
        t.event('mosaic_review_reconciled_release',robot=robot,object=name)

    def submit(self, request, *, assisted=True):
        request=json.loads(json.dumps(request,allow_nan=False))
        ident=request.get('id')
        if not isinstance(ident,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ident) is None:
            raise ValueError('Use a bounded request ID')
        if ident in self.requests:
            old=self.requests[ident]
            if old['request']!=request:raise ValueError('Request ID reused with different input')
            return deepcopy(old)
        if set(request)-{'id','world_id','review_id','operation','batches','robot','object','target_m'}:
            raise ValueError('Unsupported request fields')
        if request.get('world_id')!=self.world_id or request.get('review_id')!=self.epoch:
            raise ValueError('Request belongs to another world or stale review')
        require_known_idle(self.trial)
        op=request.get('operation');t=self.trial
        if op not in ('commands','resume','finish_held','reconcile_released','adopt_hold','stop'):
            raise ValueError('Unsupported recovery operation')
        if op=='commands':
            batches=request.get('batches')
            if not isinstance(batches,list) or not 1<=len(batches)<=16:
                raise ValueError('Use 1..16 finite command batches')
            for batch in batches:
                if not isinstance(batch,dict) or not batch or not set(batch)<=set(t.arms):
                    raise ValueError('Invalid robot batch')
                for operation,parameters in batch.values():
                    if operation not in ('move','gripper') or not isinstance(parameters,dict):
                        raise ValueError('Only ordinary move/gripper commands')
        if op=='resume':
            if t.held or any(getattr(arm,'grasp_force',None) is not None for arm in t.arms.values()):
                raise ValueError('Finish or reconcile held payloads and force-held grippers before rematching')
            reference.protected_remaining_inputs(t,getattr(t,'mosaic_protected_assignments',{}))
        if op in ('finish_held','adopt_hold','reconcile_released') and request.get('robot') not in t.arms:
            raise ValueError('Select an actual robot')
        if op=='finish_held':
            robot=request['robot'];job=getattr(t,'mosaic_current_job',None)
            name=t.held.get(robot)
            if name is None:raise ValueError('No tracked held payload')
            job=next((j for j in getattr(t,'mosaic_active_jobs',[]) if j['object']==name),job)
            if 'target_m' in request:
                target=np.asarray(request['target_m'],dtype=float)
                if target.shape!=(3,) or not np.isfinite(target).all():raise ValueError('Finite 3D staging target required')
            else:
                if not job or job['object']!=name or robot not in job['path']:
                    raise ValueError('No matching current job; supply a reviewed staging target')
                index=job['path'].index(robot)
                target=(np.asarray(next(g['position_m'] for g in t.task['goals'] if g['goal_id']==job['goal_id']))
                    if index==len(job['path'])-1 else t.mosaic_edges[frozenset(job['path'][index:index+2])])
        record=dict(request=request,status='running',feedback=[])
        self.requests[ident]=record
        write_json(self.directory/'results'/f'{ident}.json',record)
        self.assisted|=assisted
        t.event('mosaic_review_request',request=request,assisted=assisted)
        try:
            if op=='stop':raise ReferenceStopped('Explicit owner stop during review')
            if op=='commands':
                for index,batch in enumerate(batches):
                    feedback=t.execute(f'mosaic-recovery-{ident}-{index}',batch,allow_failure=True)
                    record['feedback'].append(deepcopy(feedback))
                    require_known_idle(t)
                    if any(v['status']!='completed' for v in feedback.values()):
                        record['status']='failed';break
            elif op=='finish_held':
                reference.place_cube(t,robot,target)
                reference.helpers.park(t,robot)
                t.wait(.7)
            elif op=='reconcile_released':self._reconcile_released(request['robot'])
            elif op=='adopt_hold':
                robot=request['robot'];name=request.get('object')
                if name not in {o['id'] for o in t.env['objects']} or name in t.monitor.result().get('assignments',{}).values():
                    raise ValueError('Cannot adopt an absent or completed object')
                if t.held.get(robot) not in (None,name):raise ValueError('Robot already owns another payload')
                if t.arms[robot].grasp_force is None or not t.finger_contacts(robot,name):
                    raise ValueError('No actual force-held bilateral support')
                for _ in range(10):
                    t.wait(.02)
                    if not t.finger_contacts(robot,name):raise ValueError('Support lost during observation')
                t.held[robot]=name;t.event('mosaic_review_adopted_hold',robot=robot,object=name)
            record['status']='completed' if record['status']=='running' else record['status']
        except (ProcessViolation,ReferenceStopped):
            record['status']='interrupted';raise
        except (RuntimeError,ValueError) as error:
            record.update(status='failed',error=f'{type(error).__name__}: {error}')
            require_known_idle(t)
        finally:
            record['finished_sim_s']=t.time
            write_json(self.directory/'results'/f'{ident}.json',record)
        return deepcopy(record)

    def await_resolution(self, error):
        require_known_idle(self.trial)
        self.epoch+=1
        boundary=dict(review_id=self.epoch,error=f'{type(error).__name__}: {error}',
            start_sim_s=self.trial.time,protected_assignments=dict(getattr(self.trial,'mosaic_protected_assignments',{})))
        self.history.append(boundary)
        self.trial.event('mosaic_review_opened',**boundary)
        self._status('review');self.publish()
        if self.on_enter is not None:self.on_enter(self)
        start=time.monotonic();last_publish=start
        while True:
            self.trial.check_stop();require_known_idle(self.trial)
            for path in sorted((self.directory/'requests').glob('*.json')):
                payload=path.read_bytes()
                digest=hashlib.sha256(payload).hexdigest()
                if self.seen_files.get(str(path))==digest:continue
                try:
                    request=json.loads(payload)
                    # Future decisions are not consumed before their boundary.
                    if request.get('review_id',0)>self.epoch:continue
                    self.seen_files[str(path)]=digest
                    result=self.submit(request)
                except (ValueError,TypeError,KeyError,json.JSONDecodeError) as rejected:
                    write_json(self.directory/'rejected'/f'{digest}.json',dict(error=str(rejected)))
                    continue
                if (result['status']=='completed' and request['operation']=='resume' and
                        request['review_id']==self.epoch):
                    boundary.update(resolved_sim_s=self.trial.time,request_id=request['id'])
                    self.trial.event('mosaic_review_resumed',**boundary)
                    self._status('running');return
            now=time.monotonic()
            if self.review_wall_s is not None and now-start>self.review_wall_s:
                raise ReferenceStopped('Explicit review deadline exhausted')
            self.trial.wait(.02)
            if now-last_publish>=2:
                self.publish();self._status('review');last_publish=now
            # Review holds advance real physics at approximately wall rate.
            time.sleep(max(0.,.02-(time.monotonic()-now)))


def run_reference(trial, review, *, solver=reference.solve, max_goals=None, motion_profile=None, max_reviews=None, goal_ids=None):
    resume=False
    while True:
        try:
            remaining=None if max_goals is None else max_goals-len(trial.monitor.result().get('assignments',{}))
            if remaining is not None and remaining<=0:
                return dict(reference_placed=len(trial.monitor.result().get('assignments',{})),
                    total_goals=len(trial.task['goals']),commissioning_only=max_goals<len(trial.task['goals']),resumed=resume)
            extra={}
            if goal_ids is not None:
                completed=trial.monitor.result().get('assignments',{})
                extra['goal_ids']=[goal for goal in goal_ids if goal not in completed]
            return solver(trial,max_goals=remaining,motion_profile=motion_profile,resume=resume,**extra)
        except (ProcessViolation,ReferenceStopped):raise
        except Exception as error:
            # Logic/input failures at a known idle boundary preserve the live
            # owner for review too. Unknown/active actions and violations still
            # fail require_known_idle and must never admit repair commands.
            require_known_idle(trial)
            if max_reviews is not None and len(review.history)>=max_reviews:
                raise ReferenceStopped('Explicit review count budget exhausted')
            review.await_resolution(error)
            resume=True
