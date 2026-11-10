"""Private process and goal evaluation. Nothing here is a policy observation."""
from collections import deque
import json,math
from pathlib import Path
import mujoco,numpy as np

DIGITS={0:'abcdef',1:'bc',2:'abged',3:'abgcd',4:'fgbc',5:'afgcd',6:'afgedc',7:'abc',8:'abcdefg',9:'abfgcd'}
# Process-log formats. 'full': a snapshot with object poses every 0.1 s (Oracle
# tooling reads this). 'events-1s': an event whenever a non-continuous result
# field changes, checked at every 20 ms sample, plus a full snapshot every 1 s
# and at the end. Detection itself is identical in both. 'events-10s' (the policy
# default) and 'events-60s' write the same events with snapshots every 10 s or 60 s
# and each Dial trial with its event; 'events-10s' keeps object poses in every
# snapshot, 'events-60s' leaves recorded poses to the motion recording.
PROCESS_LOG_FORMATS={'full':.10,'events-1s':1.0,'events-10s':10.0,'events-60s':60.0}
# Formats that write each new Dial trial (input symbols and score) with its event.
TRIAL_LOG_FORMATS=frozenset({'events-10s','events-60s'})
# Fields that change with time alone; 'events-1s' keeps them in snapshots only.
CONTINUOUS_FIELDS=frozenset({'sim_time_s','samples','private_angles_deg','private_angle_speeds_rad_s','private_clearance_m',
                             'timber_inside_fraction'})

def event_fields(value):
    """The result without clocks, accumulated seconds (*_s) and raw dial measurements."""
    if isinstance(value,dict):
        return {k:event_fields(v) for k,v in value.items() if k not in CONTINUOUS_FIELDS and not k.endswith('_s')}
    # Per-goal and per-dial results are lists of records with the same continuous fields.
    if isinstance(value,(list,tuple)):return [event_fields(v) for v in value]
    return value

def geom_extent(model,data,g):
    r=data.geom_xmat[g].reshape(3,3);size=model.geom_size[g];typ=model.geom_type[g]
    if typ==mujoco.mjtGeom.mjGEOM_BOX:return abs(r)@size
    if typ==mujoco.mjtGeom.mjGEOM_SPHERE:return np.full(3,size[0])
    if typ==mujoco.mjtGeom.mjGEOM_CYLINDER:return abs(r[:,2])*size[1]+size[0]*np.sqrt(np.maximum(0,1-r[:,2]**2))
    if typ==mujoco.mjtGeom.mjGEOM_CAPSULE:return abs(r[:,2])*size[1]+size[0]
    aabb=model.geom_aabb[g];return abs(r)@aabb[3:]

class SupportQualification:
    """Initial dwell and requalification after a sustained support loss.

    A sub-grace contact gap makes the instantaneous input ineligible, but does
    not create a fresh 250 ms unsupported interval after contact returns.
    """
    def __init__(self,dwell=.25,gap=.05):self.dwell=dwell;self.gap=gap;self.since=None;self.missing=None;self.qualified=False;self.last=None
    def update(self,t,present):
        if self.last is not None and t-self.last>.030001:self.since=None;self.missing=None;self.qualified=False
        self.last=t
        if present:
            self.missing=None
            if self.since is None:self.since=t
            if t-self.since>=self.dwell-1e-9:self.qualified=True
        else:
            if self.missing is None:self.missing=t
            self.since=None
            if t-self.missing>self.gap+1e-9:self.qualified=False
        return bool(present and self.qualified)

class Monitor:
    def __init__(self,world,secret=None,log_path=None,log_format='full',append=False):
        # Before anything opens (and would truncate) the process log.
        if log_format not in PROCESS_LOG_FORMATS:raise ValueError('Unknown process log format')
        self.w=world;self.m=world.model;self.d=world.data;self.task=world.task;self.family=self.task['family'];self.robots=list(world.arms);self.robot_index={r:i for i,r in enumerate(self.robots)}
        self.geom_owner=np.full(self.m.ngeom,-1,dtype=int);self.finger=np.full(self.m.ngeom,-1,dtype=int)
        roots={self.m.body(r+'_link0').id:i for i,r in enumerate(self.robots)}
        for g in range(self.m.ngeom):
            body=int(self.m.geom_bodyid[g]);name=self.m.body(body).name or ''
            while body and body not in roots:body=int(self.m.body_parentid[body])
            if body in roots:
                owner=roots[body];self.geom_owner[g]=owner
                if name in (self.robots[owner]+'_left_finger',self.robots[owner]+'_right_finger'):self.finger[g]=owner*2+(name.endswith('right_finger'))
        physical=(self.m.geom_contype!=0)|(self.m.geom_conaffinity!=0)
        self.finger_geoms={code:np.flatnonzero((self.finger==code)&physical).tolist() for code in range(len(self.robots)*2)}
        self.objects=self.task['objects'];self.names=[o['id'] for o in self.objects];self.bodies=[self.m.body(n).id for n in self.names]
        self.geoms={n:self.descendant_geoms(self.m.body(n).id) for n in self.names}
        self.geom_object=np.full(self.m.ngeom,-1,int)
        for i,n in enumerate(self.names):self.geom_object[self.geoms[n]]=i
        self.contact_pairs=[];self.self_contact_pairs=[];self.first_collisions={};self.violations=[];self.next_sample=-1;self.next_log=-1;self.last_time=None;self.max_sample_gap=0.;self.samples=0;self.max_active=0;self.overlap_s=0.;self.holding_s=0.;self.previous_sample=None
        from .contact_episodes import ContactEpisodes
        self.contact_episodes = ContactEpisodes()
        self.motion_overlap_s=0.;self.any_motion_s=0.;self.robot_motion_s=0.;self.max_moving=0
        # A continued segment appends to the same process log (docs/running/run-segments.md).
        self.log=Path(log_path).open('a' if append else 'w') if log_path else None;self.active=True
        self.log_format=log_format;self.snapshot_interval=PROCESS_LOG_FORMATS[log_format];self.last_event=None;self.logged_trials=0;self.final_logged=False
        if self.log and log_format!='full':
            # Self-describing header; 'full' logs keep their original line-per-snapshot form.
            self.log.write(json.dumps(dict(schema='robofrontier.suite-process.v2',format=log_format,snapshot_interval_s=self.snapshot_interval,
                sample_interval_s=.02,continuous_fields=sorted(CONTINUOUS_FIELDS)+['*_s']))+'\n');self.log.flush()
        self.result_cache={};self.goal_since=None;self.since=np.full((len(self.task['goals']),len(self.names)),np.nan)
        if self.family=='dial':
            self.dials=self.task['dials'];n=len(self.dials);self.blue={};self.red={};self.module_geoms=[];self.blue_qualification=[SupportQualification() for _ in range(n)];self.dial_ready=[False]*n;self.previous_red=set();self.unsupported_since={}
            for i,a in enumerate(self.dials):
                name=a['id']
                if self.task['level']>1:
                    self.blue[self.m.geom(name+'_module_stem').id]=i
                    for g in self.descendant_geoms(self.m.body(name+'_module').id):
                        if (self.m.geom(g).name or '').startswith(name+'_handle_shoulder'):self.blue[g]=i
                rotor=self.m.body(name+'_rotor').id;self.red.update({g:i for g in self.descendant_geoms(rotor)})
                self.module_geoms.append(self.descendant_geoms(self.m.body(name+'_module').id))
            self.qids=[self.m.jnt_qposadr[self.m.joint(x['id']+'_hinge').id] for x in self.dials];self.dofs=[self.m.jnt_dofadr[self.m.joint(x['id']+'_hinge').id] for x in self.dials]
            if secret is None:raise ValueError('Private dial code must be explicitly supplied to evaluator')
            from .dial import from_task
            self.game=from_task(self.task,secret)
            self.minimum_clearance=np.full(n,math.inf);self.blue_gaps=np.zeros(n);self.blue_max_gaps=np.zeros(n);self.last_dial_angles=None
            self.carried_trials=0
            if append:self.continue_dial_record()
        if self.family=='relay':
            self.relay=Relay(self)
            if append:self.relay.continue_record()
    def continue_dial_record(self):
        """A continued segment's evaluator takes over the Dial record at its restore frame.

        Trials, BEST and success are episode history, carried in the bound restore record
        (docs/running/run-segments.md). A configuration already counted and held at that
        frame stays the same trial while it is held on; leaving and re-entering counts again.
        Blue support ready at that frame stays qualified, and red knobs held there are not new
        contacts, so the restart neither re-counts a held input nor records a violation.
        """
        from ..runtime.segments import current_restore
        # Red contacts present at the first sample are carried, not new (sample_dial).
        self.previous_red=None
        found=current_restore(self.w.directory) if getattr(self.w,'directory',None) is not None else None
        record=found[0].get('evaluator') if found else None
        if not record:return
        t=float(self.d.time);ready=record.get('support_ready')
        if ready is None and record.get('input_ready'):ready=[True]*len(getattr(self,'blue_qualification',[]))
        for q,held in zip(getattr(self,'blue_qualification',[]),ready or []):
            if held:q.since=t-q.dwell;q.qualified=True;q.last=t
        game=self.game;game.queries=self.carried_trials=int(record['valid_trials']);game.won=bool(record['solved'])
        if getattr(game,'mode',None)=='best_so_far' and record.get('best') is not None:game.best=game.display=int(record['best'])
        if record.get('input_ready'):
            angles=self.d.qpos[self.qids]
            marks=tuple(round((math.degrees(float(x))%360)/game.step_deg)%(game.symbol_count+1) for x in angles)
            game.candidate=marks;game.since=float(self.d.time);game.submitted=True
    def descendant_geoms(self,root):
        out=[]
        for g in range(self.m.ngeom):
            if not (self.m.geom_contype[g] or self.m.geom_conaffinity[g]):continue
            b=int(self.m.geom_bodyid[g])
            while b and b!=root:b=int(self.m.body_parentid[b])
            if b==root:out.append(g)
        return out
    def violation(self,kind,**details):
        if not any(v['kind']==kind and v.get('key')==details.get('key') for v in self.violations):self.violations.append(dict(kind=kind,sim_time_s=float(self.d.time),**details))
    def terminal_scoring(self):
        return self.task.get('run_protocol', {}).get('evaluation_semantics') == 'terminal_outcome_v2'
    def contacts(self):
        if not self.d.ncon:return np.empty((0,2),int),np.empty(0)
        return np.asarray(self.d.contact.geom),np.asarray(self.d.contact.dist)
    def scene_contacts(self):
        """Every current contact, including those a sleeping world no longer lists.

        MuJoCo drops contacts between sleeping bodies from `data.contact`, though they
        still touch. Scoring that asks what supports an object recomputes them here, from
        a separate MjData that never sleeps. Physics is untouched: no force is read or
        written, and a world without sleep returns its own list unchanged."""
        if not self.m.opt.enableflags&int(mujoco.mjtEnableBit.mjENBL_SLEEP):return self.d.contact
        scratch=getattr(self,'_contact_data',None)
        if scratch is None:scratch=self._contact_data=mujoco.MjData(self.m);self._contact_time=None
        if self._contact_time!=float(self.d.time):
            scratch.qpos[:]=self.d.qpos;scratch.time=float(self.d.time)
            mujoco.mj_kinematics(self.m,scratch);mujoco.mj_collision(self.m,scratch);self._contact_time=float(self.d.time)
        return scratch.contact
    def bilateral(self,target_geoms,positive_force=False):
        """Opposed-jaw proximity with actual contact on at least one side.

        For load support, a real force-bearing contact is required per gripper;
        it need not be distributed positively over both individual pads.
        """
        target=set(target_geoms);found={};loaded=set()
        for i,c in enumerate(self.d.contact):
            if c.dist>.0002:continue
            for finger,part in ((int(c.geom1),int(c.geom2)),(int(c.geom2),int(c.geom1))):
                code=int(self.finger[finger])
                if code<0 or part not in target:continue
                if positive_force:
                    force=np.zeros(6);mujoco.mj_contactForce(self.m,self.d,i,force)
                    if force[0]>=.02:loaded.add(self.robots[code//2])
                found.setdefault(self.robots[code//2],set()).add(code%2)
        if found:
            # With zero physics margin, the contact list contains no positive
            # gaps at all. Implement the declared 0.2 mm geometric tolerance by
            # querying distance, without adding contacts or forces to physics.
            for robot,parts in found.items():
                if len(parts)==2:continue
                missing=1-next(iter(parts));code=self.robot_index[robot]*2+missing
                for finger in self.finger_geoms[code]:
                    for part in target:
                        compatible=(self.m.geom_contype[finger]&self.m.geom_conaffinity[part]) or (self.m.geom_contype[part]&self.m.geom_conaffinity[finger])
                        if compatible and mujoco.mj_geomDistance(self.m,self.d,finger,part,.00021,None)<.0002:
                            parts.add(missing);break
                    if missing in parts:break
        return {r for r,parts in found.items() if len(parts)==2 and (not positive_force or r in loaded)}
    def released(self,target_geoms):
        pairs,dist=self.contacts()
        if not len(pairs):return True
        target=np.zeros(self.m.ngeom,bool);target[list(target_geoms)]=True
        return not np.any((dist<=.0002)&((target[pairs[:,0]]&(self.geom_owner[pairs[:,1]]>=0))|(target[pairs[:,1]]&(self.geom_owner[pairs[:,0]]>=0))))
    def bottom(self,gs):return min(float((self.d.geom_xpos[g]+self.d.geom_xmat[g].reshape(3,3)@self.m.geom_aabb[g,:3])[2]-geom_extent(self.m,self.d,g)[2]) for g in gs)
    def velocity(self,body):
        v=np.zeros(6);mujoco.mj_objectVelocity(self.m,self.d,mujoco.mjtObj.mjOBJ_BODY,body,v,0);return v
    def physical_step(self):
        if not self.active:return
        pairs,dist=self.contacts()
        episode_contacts=set()
        if len(pairs):
            owners=self.geom_owner[pairs];bad=(owners[:,0]>=0)&(owners[:,1]>=0)&(owners[:,0]!=owners[:,1])&(dist<-.0002)
            for a,b in pairs[bad]:
                names=tuple(sorted((self.m.body(self.m.geom_bodyid[a]).name,self.m.body(self.m.geom_bodyid[b]).name)));key=' / '.join(names)
                episode_contacts.add(('inter_robot_contact',key))
                if key not in self.first_collisions:self.first_collisions[key]=float(self.d.time);self.violation('inter_robot_contact',key=key)
            same=(owners[:,0]>=0)&(owners[:,0]==owners[:,1])&(dist<-.001)
            for a,b in pairs[same]:
                bodies=[self.m.body(self.m.geom_bodyid[g]).name or '' for g in (a,b)]
                if not all('finger' in x for x in bodies):
                    key=' / '.join(sorted(bodies))
                    episode_contacts.add(('self_robot_contact',key))
                    if key not in self.self_contact_pairs:self.self_contact_pairs.append(key);self.violation('self_robot_contact',key=key)
        t=float(self.d.time)
        self.contact_episodes.sample(t,episode_contacts)
        if t+1e-9<self.next_sample:return
        self.next_sample=t+.02;self.samples+=1
        if self.last_time is not None:self.max_sample_gap=max(self.max_sample_gap,t-self.last_time)
        dt=0 if self.last_time is None else t-self.last_time;self.last_time=t
        active=sum(arm.job is not None for arm in self.w.arms.values());self.max_active=max(self.max_active,active)
        if active>=2:self.overlap_s+=dt
        sample=np.asarray([self.d.qpos[arm.qids].copy() for arm in self.w.arms.values()])
        if self.previous_sample is not None and dt>0:
            # Position change over the complete sampling window suppresses
            # solver sub-step velocity chatter. Holding is counted separately.
            moving=int(np.sum(np.max(abs(sample-self.previous_sample),axis=1)/dt>.02))
            self.max_moving=max(self.max_moving,moving);self.robot_motion_s+=moving*dt
            if moving:self.any_motion_s+=dt
            if moving>=2:self.motion_overlap_s+=dt
        self.previous_sample=sample
        if self.family=='dial':self.sample_dial(dt)
        elif self.family=='relay':self.relay.sample()
        else:self.sample_goals()
        if self.log:self.log_sample(t)
    def log_sample(self,t,final=False):
        result=self.result()
        if self.log_format=='full':
            if not final and t<self.next_log:return
            self.next_log=t+self.snapshot_interval;record=dict(sim_time_s=t,result=result,objects=self.object_poses())
        else:
            events=json.dumps(event_fields(result),sort_keys=True,allow_nan=False)
            if final or t>=self.next_log:
                self.next_log=t+self.snapshot_interval;record=dict(type='snapshot',sim_time_s=t,result=result)
                if final or self.log_format!='events-60s' or not self.motion_recorded():record['objects']=self.object_poses()
            elif events!=self.last_event:record=dict(type='event',sim_time_s=t,result=result)
            else:return
            self.last_event=events
            if self.log_format in TRIAL_LOG_FORMATS and getattr(getattr(self,'game',None),'trials',None):
                fresh=self.game.trials[self.logged_trials:]
                if fresh:record['trials']=fresh;self.logged_trials=len(self.game.trials)
        self.log.write(json.dumps(record,allow_nan=False)+'\n');self.log.flush()
    def motion_recorded(self):
        """This scene records motion, so its poses need not be logged twice (motion_query)."""
        asset=self.task.get('scene_asset')
        return bool(asset) and (Path(self.w.directory)/Path(asset).parent/'workstation.json').exists()
    def object_poses(self):
        return {n:dict(position_m=self.d.body(n).xpos.tolist(),quaternion_wxyz=self.d.body(n).xquat.tolist()) for n in self.names}
    def sample_goals(self):
        n=len(self.names);goals=self.task['goals'];eligible=np.zeros((len(goals),n),bool)
        positions=np.array([self.d.body(n).xpos for n in self.names]);vel=[self.velocity(b) for b in self.bodies]
        released=np.ones(n,bool);pairs,dist=self.contacts()
        for left,right in ((0,1),(1,0)):
            ids=self.geom_object[pairs[:,left]];mask=(ids>=0)&(self.geom_owner[pairs[:,right]]>=0)&(dist<=.0002);released[ids[mask]]=False
        stable=[np.linalg.norm(v[3:])<.01 and np.linalg.norm(v[:3])<.1 and released[j] for j,v in enumerate(vel)]
        eligible=placement_candidates(self,positions,stable)
        t=float(self.d.time);self.since=np.where(eligible,np.where(np.isnan(self.since),t,self.since),np.nan)
        qualified=eligible&((t-self.since)>=self.task['completion']['stable_duration_sim_s']-1e-8);matched={}
        def assign(i,seen):
            for j in np.flatnonzero(qualified[i]):
                if j in seen:continue
                seen.add(j)
                if j not in matched or assign(matched[j],seen):matched[j]=i;return True
            return False
        for i in range(len(goals)):assign(i,set())
        complete=len(matched)==len(goals)
        self.result_cache=dict(all_goals_met=complete,task_success=complete and not self.violations,matched_goals=len(matched),total_goals=len(goals),assignments={goals[i]['goal_id']:self.names[j] for j,i in matched.items()})
        if Monitor.terminal_scoring(self):
            self.result_cache.update(task_success=complete, terminal_goal_met=complete,
                                     strict_task_success=complete and not self.violations,
                                     scoring_version='terminal_outcome_v2')
    def sample_dial(self,dt):
        n=len(self.dials);supporters=[];ready=[];clear=[];red=set();pairs,dist=self.contacts()
        for i,a in enumerate(self.dials):
            if self.task['level']==1:support=set();ok=True;c=math.inf
            else:
                support=self.bilateral([g for g,index in self.blue.items() if index==i]);c=self.bottom(self.module_geoms[i])-self.task.get('table_height_m',.4)
                own=np.zeros(self.m.ngeom,bool);own[self.module_geoms[i]]=True
                external=bool(np.any((dist<=.0002)&((own[pairs[:,0]]&~own[pairs[:,1]]&(self.geom_owner[pairs[:,1]]<0))|(own[pairs[:,1]]&~own[pairs[:,0]]&(self.geom_owner[pairs[:,0]]<0))))) if len(pairs) else False
                ok=c>=.02 and bool(support) and not external
                if ok:self.holding_s+=dt
                ok=self.blue_qualification[i].update(float(self.d.time),ok)
                self.minimum_clearance[i]=min(self.minimum_clearance[i],c) if ok else self.minimum_clearance[i]
            supporters.append(support);ready.append(ok);clear.append(None if not math.isfinite(c) else c)
        for pair,distance in zip(pairs,dist):
            if distance>.0002:continue
            for robot,part in ((int(pair[0]),int(pair[1])),(int(pair[1]),int(pair[0]))):
                if self.geom_owner[robot]>=0 and part in self.red:red.add((self.red[part],self.robots[self.geom_owner[robot]]))
        if self.previous_red is None:self.previous_red=red
        if not self.game.won and self.task['level']>1:
            for i,robot in red-self.previous_red:
                if not ready[i] or not (supporters[i]-{robot}):self.violation('premature_red_contact',key=self.dials[i]['id']+'/'+robot)
            for i,robot in red:
                arm=self.w.arms[robot];moving=arm.job is not None and arm.job_op=='move' and np.max(abs(self.d.qvel[arm.dofs]))>.03
                key=(i,robot)
                if not ready[i] and moving:
                    if key not in self.unsupported_since:self.unsupported_since[key]=self.d.time
                    if self.d.time-self.unsupported_since[key]>.05:self.violation('driven_red_without_support',key=self.dials[i]['id']+'/'+robot)
                else:self.unsupported_since.pop(key,None)
        self.dial_ready=ready;self.previous_red=red;eligible=all(ready);red_ready=None
        spec=self.task.get('mechanism',{}).get('feedback')
        if spec and spec.get('require_red_grasp'):
            red_ready=[]
            for i,a in enumerate(self.dials):
                geoms=[self.m.geom(a['id']+'_hand_grip').id] if self.task['level']==3 else [g for g,index in self.red.items() if index==i]
                rotating={r for r in self.bilateral(geoms) if self.w.arms[r].grasp_force is not None}
                if self.task['level']>1:rotating={r for r in rotating if supporters[i]-{r}}
                red_ready.append(bool(rotating))
            eligible=eligible and all(red_ready)
        score=self.game.update(float(self.d.time),self.d.qpos[self.qids],self.d.qvel[self.dofs],eligible)
        if spec:
            from .dial import paint_display
            paint_display(self.m,self.game,spec.get('display_digits',2))
        else:
            show='--' if score is None else f'{score:02d}'
            for digit,char in enumerate(show):
                for k,segment in enumerate('abcdefg'):
                    gid=self.m.geom(f'score_{digit}_{k}').id;self.m.geom_rgba[gid]=[.68,.13,.07,1 if segment in (DIGITS[int(char)] if char!='-' else 'g') else 0]
        self.result_cache=dict(all_goals_met=self.game.won,task_success=self.game.won and not self.violations,solved=self.game.won,valid_trials=self.game.queries,display=score,private_angles_deg=np.degrees(self.d.qpos[self.qids]).tolist(),private_clearance_m=clear,private_support_ready=ready,private_angle_speeds_rad_s=self.d.qvel[self.dofs].tolist(),private_feedback_dwell_s=None if self.game.since is None else float(self.d.time)-self.game.since)
        if Monitor.terminal_scoring(self):
            self.result_cache.update(task_success=self.game.won, terminal_goal_met=self.game.won,
                                     strict_task_success=self.game.won and not self.violations,
                                     scoring_version='terminal_outcome_v2')
        if spec:self.result_cache.update(feedback_mode=self.game.mode,input_ready=self.game.ready,private_red_hold_ready=red_ready)
        else:self.result_cache.update(input_ready=self.game.ready)
        if self.carried_trials:self.result_cache['carried_valid_trials']=self.carried_trials
    def result(self):
        result = dict(self.result_cache,process_compliant=not self.violations,violations=list(self.violations),sim_time_s=float(self.d.time),samples=self.samples,max_sample_gap_s=self.max_sample_gap,inter_robot_contacts=len(self.first_collisions),self_contacts=list(self.self_contact_pairs),peak_concurrent_actions=self.max_active,execution_overlap_sim_s=self.overlap_s,motion_overlap_sim_s=self.motion_overlap_s,any_motion_sim_s=self.any_motion_s,robot_motion_s=self.robot_motion_s,peak_moving_robots=self.max_moving,motion_definition='max joint displacement / 20 ms window > 0.02 rad/s; distinct from active jobs and useful holding',useful_blue_support_robot_s=self.holding_s)
        if self.terminal_scoring(): result['robot_contact_episodes'] = self.contact_episodes.report()
        return result
    def close(self):
        if self.log:
            if self.log_format!='full' and not self.final_logged:
                # Interrupted runs: best-effort final state; closing must not fail on it.
                try:self.log_sample(float(self.d.time),final=True)
                except Exception:pass
            self.log.close()
    def finish(self):
        self.active=False
        if self.log and self.log_format!='full' and not self.final_logged:
            self.log_sample(float(self.d.time),final=True);self.final_logged=True

def mosaic_candidates(mon,positions,stable):
    """Same private predicates, evaluated once per object or in array batches.

    Geometry/contact thresholds, requirement equality and inclusive boundaries
    match the scalar reference. No physics state or task metadata is cached or
    changed; mutable test metadata is observed on every call.
    """
    task=mon.task;m,d=mon.m,mon.d;goals=task['goals'];n=len(mon.names)
    out=np.zeros((len(goals),n),bool)
    if not len(goals) or not n or not np.any(stable):return out
    out[:]=True
    keys=set().union(*(g['requires'] for g in goals))
    for key in keys:
        expected=np.fromiter((g['requires'].get(key) for g in goals),dtype=object,count=len(goals))
        actual=np.fromiter((o.get(key) for o in mon.objects),dtype=object,count=n)
        required=np.fromiter((key in g['requires'] for g in goals),dtype=bool,count=len(goals))
        out&=(~required[:,None])|(expected[:,None]==actual[None,:])
    rotations=d.xmat[np.asarray(mon.bodies,dtype=int)].reshape(n,3,3)
    aligned=np.min(np.max(abs(rotations),axis=1),axis=1)
    out&=(np.asarray(stable,dtype=bool)&~(aligned<math.cos(math.radians(8))))[None,:]
    targets=np.asarray([g['position_m'] for g in goals]);delta=np.asarray(positions)[None,:,:]-targets[:,None,:]
    if task['level']!=1:
        tolerance=task.get('completion',{}).get('xy_center_tolerance_m_inclusive',.005)
        if isinstance(tolerance,bool) or not isinstance(tolerance,(int,float)) or not math.isfinite(tolerance) or not 0 < tolerance <= .05:
            raise ValueError('Invalid Mosaic center tolerance')
        out&=~(np.linalg.norm(delta[:,:,:2],axis=2)>tolerance)
        out&=~(abs(delta[:,:,2])>.003)
        return out
    half=task['cube_size_m']/2*np.sum(abs(rotations),axis=2)
    out&=~np.any(abs(delta[:,:,:2])+half[None,:,:2]>task['grid']['pocket_opening_m']/2+.0003,axis=2)
    out&=~(abs(np.asarray(positions)[:,2]-half[:,2]-task['grid']['floor_z_m'])>.0008)[None,:]
    candidates=np.flatnonzero(out.any(axis=0))
    if not len(candidates):return out
    floor=m.geom('pocket_bottom').id;pairs,dist=mon.contacts()
    touches=set(pairs[(pairs[:,0]==floor)&(dist<=.0002),1].tolist())
    touches.update(pairs[(pairs[:,1]==floor)&(dist<=.0002),0].tolist())
    seated=np.zeros(n,bool)
    for j in candidates:
        root=m.geom(mon.objects[int(j)]['id']+'_geom').id
        seated[j]=root in touches or not(mujoco.mj_geomDistance(m,d,root,floor,.00021,None)>.0002)
    return out&seated[None,:]


def placement_candidates(mon,positions,stable):
    if mon.task['family']=='mosaic':return mosaic_candidates(mon,positions,stable)
    task=mon.task;m,d=mon.m,mon.d;goals=task['goals'];out=np.zeros((len(goals),len(mon.names)),bool)
    side=task['cube_size_m'];tol=.0003
    for i,g in enumerate(goals):
        target=np.asarray(g['position_m'])
        if task['family']=='transport':
            board=d.body(g['board']);br=board.xmat.reshape(3,3);bv=mon.velocity(board.id)
            if np.linalg.norm(bv[3:])>.01 or np.linalg.norm(bv[:3])>.1:continue
        for j,o in enumerate(mon.objects):
            if not stable[j] or any(o.get(k)!=v for k,v in g['requires'].items()):continue
            body=d.body(o['id']);r=body.xmat.reshape(3,3)
            p=br.T@(positions[j]-board.xpos);rr=br.T@r;local=np.asarray(g['local_position_m'])
            if abs(p[2]-local[2])>.0015 or rr[2,2]<math.cos(math.radians(5)):continue
            if task['level']==1:
                root=m.geom(o['id']+'_geom').id;gr=d.geom_xmat[root].reshape(3,3);typ=o['shape']
                extent=(side/2*np.sum(abs(br.T@gr),axis=1) if typ=='cube' else side/2*(abs((br.T@gr)[:,2])+np.sqrt(np.maximum(0,1-(br.T@gr)[:,2]**2))))
                if np.any(abs(p[:2]-local[:2])+extent[:2]>(side+.010)/2+tol):continue
            else:
                mechanism=task['mechanism'];spacing=mechanism['blade_spacing_m'];opening=np.asarray(mechanism['slot_opening_m'])/2;depth=mechanism['slot_depth_m'];valid=True
                for blade in (0,1):
                    gid=m.geom(o['id']+f'_blade{blade}').id;center=br.T@(d.geom_xpos[gid]-board.xpos);rot=br.T@d.geom_xmat[gid].reshape(3,3);extent=abs(rot)@m.geom_size[gid]
                    expected=np.array([(-1 if blade==0 else 1)*spacing/2,local[1]])
                    # 180-degree placement swaps the two identical blades.
                    nearest=min((np.array([-spacing/2,local[1]]),np.array([spacing/2,local[1]])),key=lambda q:np.linalg.norm(center[:2]-q))
                    if np.any(abs(center[:2]-nearest)+extent[:2]>opening+tol) or center[2]+extent[2]>.0005 or center[2]-extent[2]<-depth-tol:valid=False;break
                if not valid:continue
            out[i,j]=True
    return out


class Relay:
    HANDOVER_PROTOCOL='qualified-members-v3'
    GROUNDED_REGRASP_PROTOCOL='grounded-regrasp-v1'

    @staticmethod
    def is_handover(item):
        """A recorded custody change that counts as a qualified airborne handover.

        A new arm must have joined, and the change must have happened off the table.
        Rows written before the airborne flag existed ('qualified-members-v2') read as airborne.
        """
        return bool(item.get('airborne',True) and set(item['receivers'])-set(item['senders']))
    def __init__(self,monitor):
        self.mon=monitor;self.table=monitor.task['table_height_m'];self.route=monitor.task['route'];self.states={}
        for item in monitor.task['mechanism']['payload_assemblies']:
            ident=item['id'];all_geoms=monitor.descendant_geoms(monitor.m.body(ident).id)
            for name in (item.get('weight_body'),item.get('tray_body')):
                if name:all_geoms+=monitor.descendant_geoms(monitor.m.body(name).id)
            # Articulated L3 has graspable timber on both sides of the hinge.
            # Suspension rings and the weight are never valid beam grasps.
            beam_ids={monitor.m.body(n).id for n in item.get('beam_bodies',[ident])}
            rod=[g for g in all_geoms if monitor.m.geom_bodyid[g] in beam_ids
                 and ('_beam' in (monitor.m.geom(g).name or ''))]
            self.states[ident]=dict(assembly=item,all_geoms=all_geoms,rod_geoms=rod,airborne=False,custody=set(),candidate=set(),candidate_since={},overlap_since=None,qualified=set(),gap_since=None,dropped=False,drops=0,transitions=[],valid_from=0.,goal_since=None,landed=False,spill=False,goal_release_ready=False,goal_release_active=False)
        self.payload_components={};self.geom_component={}
        for ident,state in self.states.items():
            names=[ident]+[state['assembly'][key] for key in ('weight_body','tray_body') if state['assembly'].get(key)]
            self.payload_components[ident]=set()
            for name in names:
                geoms=monitor.descendant_geoms(monitor.m.body(name).id)
                if not geoms:continue
                self.payload_components[ident].add(name)
                for gid in geoms:self.geom_component[gid]=name
    def environment_contact(self,geoms):
        mon=self.mon;own=set(geoms)
        return any(c.dist<=0 and any(int(a) in own and (mon.m.geom(int(b)).name or '').startswith(('table_','floor','pocket_')) for a,b in ((c.geom1,c.geom2),(c.geom2,c.geom1))) for c in mon.scene_contacts())
    def inside(self,state):
        mon=self.mon;region=self.route[-1];yaw=region['nominal_yaw_rad'];c,s=math.cos(yaw),math.sin(yaw);r=np.array([[c,-s,0],[s,c,0],[0,0,1.]])
        center=np.asarray(region['center_m']);half=np.asarray(region.get('half_size_m',[.24,.65]))
        for gid in state['all_geoms']:
            rotation=mon.d.geom_xmat[gid].reshape(3,3);aabb=mon.m.geom_aabb[gid];p=mon.d.geom_xpos[gid]+rotation@aabb[:3];extent=abs(r.T@rotation)@aabb[3:];delta=r.T@(p-center)
            if np.any(abs(delta[:2])+extent[:2]>half+mon.task.get('completion',{}).get('boundary_tolerance_m',.002)):return False
        return True
    def supported_payloads(self,goal_only=True,require_all=True,inside_ids=None):
        """Actual cargo contacts/structural components connected to tabletop.

        Robot contacts never ground a component. Independent free weights
        require their own contact path; grouping an assembly does not weld it.
        """
        eligible=set(self.states)
        if goal_only:
            eligible&=set(inside_ids) if inside_ids is not None else {name for name,state in self.states.items() if self.inside(state)}
        components={part for name in eligible for part in self.payload_components[name]}
        edges={part:set() for part in components};ground=set();mon=self.mon
        for contact in mon.scene_contacts():
            if contact.dist>0:continue
            a,b=map(int,contact.geom);left=self.geom_component.get(a);right=self.geom_component.get(b)
            if left in components and right in components and left!=right:
                edges[left].add(right);edges[right].add(left)
            for part,other in ((left,b),(right,a)):
                if part in components and (mon.m.geom(other).name or '').startswith('table_') and contact.pos[2]>=self.table-.01:ground.add(part)
        pending=list(ground)
        while pending:
            part=pending.pop()
            for neighbor in edges[part]-ground:ground.add(neighbor);pending.append(neighbor)
        return {name for name in eligible if (self.payload_components[name]<=ground if require_all else bool(self.payload_components[name]&ground))}
    def continue_record(self):
        """A continued segment keeps each timber's handovers and drops, which are episode history.

        A timber held at the restore frame is re-established as airborne by the ordinary
        lift check, with the custody and drop state it had at that frame
        (docs/running/run-segments.md).
        """
        from ..runtime.segments import current_restore
        directory=getattr(self.mon.w,'directory',None)
        found=current_restore(directory) if directory is not None else None
        record=found[0].get('evaluator',{}).get('relay_payloads') if found else None
        for ident,item in (record or {}).items():
            if ident not in self.states:continue
            self.states[ident].update(transitions=list(item['handovers']),drops=int(item['drops']),
                                      valid_from=item.get('handovers_valid_from_s',0.))
            if len(item.get('custody') or [])>=2:
                self.states[ident].update(carried_custody=set(item['custody']),carried_dropped=bool(item.get('dropped')))
    def sample(self):
        mon=self.mon;t=float(mon.d.time);completed=0;terminal_completed=0;reports={}
        inside_flags={name:self.inside(state) for name,state in self.states.items()}
        stacking=bool(mon.task['completion'].get('support_via_goal_payload'))
        global_ground=self.supported_payloads(False,False) if stacking else set()
        from .relay import is_current, RULE_REVISION
        current_contract=is_current(mon.task)
        fraction_contract=mon.task.get('completion', {}).get('rule_revision') == RULE_REVISION
        goal_ground=self.supported_payloads(True,not current_contract,{name for name,inside in inside_flags.items() if inside}) if stacking else set()
        for ident,state in self.states.items():
            a=state['assembly'];support=mon.bilateral(state['rod_geoms'],positive_force=True);all_g=state['all_geoms'];external=self.environment_contact(all_g) or ident in global_ground;on_table=ident in goal_ground if stacking else external;inside=inside_flags[ident]
            clear=mon.bottom(all_g)>self.table+.002 and ident not in global_ground
            if not state['airborne'] and mon.bottom(state['rod_geoms'])>self.table+.025:
                if len(support)<2:mon.violation('unsupported_initial_lift',key=ident)
                elif clear:
                    # A continued segment re-establishes the carried team (continue_record):
                    # a timber dropped at the restore frame stays dropped for its holders,
                    # and a handover under way there still needs its receiver qualified.
                    carried=state.get('carried_custody') or set()
                    if state.get('carried_dropped'):state.update(airborne=True,custody=set(carried),dropped=True)
                    elif len(carried&support)>=2:state.update(airborne=True,custody=carried&support)
                    else:state.update(airborne=True,custody=set(support))
            if state['airborne']:
                completion=mon.task['completion'];original_support=len(support&state['custody'])>=2
                near_release=bool(completion.get('allow_near_goal_release'))
                if near_release:
                    if not inside:
                        state['goal_release_ready']=state['goal_release_active']=False
                    elif original_support:
                        # Permission comes from the measured prior two-hand
                        # low pose, never from a commanded target or RPC flag.
                        geoms=all_g if current_contract else state['rod_geoms']
                        limit=completion['max_release_gap_m'] if current_contract else completion['max_timber_release_gap_m']
                        state['goal_release_ready']=mon.bottom(geoms)<=self.table+limit
                        state['goal_release_active']=False
                    elif state['goal_release_ready']:
                        state['goal_release_active']=True;state['goal_release_ready']=False
                allowed_release=near_release and inside and state['goal_release_active']
                if len(support)<2 and not state['landed']:
                    if state['gap_since'] is None:state['gap_since']=t
                else:state['gap_since']=None
                # A handover happens in the air: the timber is clear of the table, held
                # neither by it nor through other cargo (task_families.RELAY_HANDOVER_DEFINITION).
                off_table=clear and not external
                if not state['dropped']:
                    fresh=support-state['custody']
                    # Qualify each arriving hand while the established team
                    # still supplies at least two supports off the table. A
                    # contact loss or a touch of the table invalidates that
                    # receiver's earlier overlap evidence.
                    state['qualified'].intersection_update(fresh)
                    state['candidate_since']={a:s for a,s in state['candidate_since'].items() if a in fresh}
                    if not off_table:state['qualified']=set();state['candidate_since']={}
                    elif len(support&state['custody'])>=2:
                        for robot in fresh:
                            since=state['candidate_since'].setdefault(robot,t)
                            if t-since>=.20-1e-9:state['qualified'].add(robot)
                    state['candidate']=set(fresh)
                    state['overlap_since']=min(state['candidate_since'].values(),default=None)
                    if not state['custody']<=support and len(support)>=2:
                        old=set(state['custody'])
                        change=dict(sim_time_s=t,senders=sorted(old),receivers=sorted(support),
                            retained=sorted(old&support),released=sorted(old-support),joined=sorted(fresh))
                        if not fresh or (off_table and fresh<=state['qualified']):
                            # A pure release is recorded wherever it happens; it is never a handover.
                            state['transitions'].append(dict(change,protocol=self.HANDOVER_PROTOCOL,airborne=off_table))
                            state['custody']=set(support);state['qualified']=set();state['candidate']=set();state['candidate_since']={};state['overlap_since']=None
                        elif not off_table and inside:
                            # A regrasp of a timber resting in GOAL changes who holds it,
                            # but it is never a handover.
                            state['transitions'].append(dict(change,protocol=self.GROUNDED_REGRASP_PROTOCOL,airborne=False))
                            state['custody']=set(support);state['qualified']=set();state['candidate']=set();state['candidate_since']={};state['overlap_since']=None
                        else:mon.violation('unverified_handover',key=ident)
                if on_table and inside and (original_support or (allowed_release and mon.released(all_g))):state['landed']=True
                goal_contact=bool(completion.get('allow_goal_partial_support')) and inside and (original_support or allowed_release)
                bad_contact=external and not((state['landed'] and inside) or goal_contact)
                gap=state['gap_since'] is not None and t-state['gap_since']>.20 and not allowed_release
                if (bad_contact or gap) and not state['dropped']:state['dropped']=True;state['drops']+=1
                if state['dropped']:
                    if support-state['custody']:
                        # A receiver that picks a dropped timber up voids its handovers
                        # (RELAY_RECOVERY_RULE): none counts, earlier or later, until the team
                        # that held it at the drop lifts it again and hands it over.
                        mon.violation('receiver_recovered_drop',key=ident);state['valid_from']=None
                    if len(support&state['custody'])>=2 and clear:
                        # Receiver evidence from before the drop does not carry over the drop.
                        state.update(dropped=False,gap_since=None,qualified=set(),candidate=set(),candidate_since={},overlap_since=None)
                        if state['valid_from'] is None:state['valid_from']=t
            if a.get('tray_body'):
                tray=mon.d.body(a['tray_body']);weight=mon.d.body(a['weight_body']);delta=tray.xmat.reshape(3,3).T@(weight.xpos-tray.xpos);spec=mon.task['mechanism']['tray']
                if np.linalg.norm(delta[:2])>(spec['outer_diameter_m']-spec['weight_diameter_m'])/2+.002 or delta[2]<spec['weight_height_m']/2-.005 or delta[2]>.075:
                    state['spill']=True;mon.violation('tray_weight_spilled',key=ident)
            moving_names=list(dict.fromkeys(a.get('beam_bodies',[ident])+[name for name in (a.get('weight_body'),a.get('tray_body')) if name]))
            velocities=[mon.velocity(mon.m.body(name).id) for name in moving_names]
            stable=current_contract or all(np.linalg.norm(v[3:])<.01 and np.linalg.norm(v[:3])<.1 for v in velocities)
            counted=[tr for tr in state['transitions'] if self.is_handover(tr) and state['valid_from'] is not None and tr.get('sim_time_s',0.)>=state['valid_from']-1e-9]
            handover_ok=not mon.task['completion'].get('required_airborne_handover',False) or bool(counted)
            done=state['landed'] and inside and on_table and mon.released(all_g) and stable and not state['dropped'] and not state['spill'] and handover_ok
            state['goal_since']=(t if state['goal_since'] is None else state['goal_since']) if done else None
            qualified=state['goal_since'] is not None and t-state['goal_since']>=mon.task['completion']['stable_duration_sim_s']
            if fraction_contract:
                from .relay_goal_fraction import timber_fraction
                # Visual mesh duplicates collision segments for curved timbers.
                # Only physical timber geoms contribute, never the pendant.
                segments=[g for g in state['rod_geoms']
                          if (mon.m.geom(g).name or '').endswith('_beam')
                          or '_beam_part' in (mon.m.geom(g).name or '')
                          or '_beam_segment' in (mon.m.geom(g).name or '')]
                fraction=float(timber_fraction(mon.m,mon.d,segments,self.route[-1],
                                               mon.task['completion']['timber_goal_tolerance_m']))
                terminal=bool(fraction >= mon.task['completion']['timber_inside_fraction_min'] and mon.released(all_g))
            else:
                terminal=inside and on_table and mon.released(all_g)
            handover_met=bool(counted)
            handover_required=mon.task.get('run_protocol',{}).get('relay_completion_rule') is not None
            terminal=bool(terminal and (handover_met or not handover_required))
            terminal_completed+=int(terminal)
            completed+=int(qualified);reports[ident]=dict(completed=qualified,terminal_goal_met=terminal,airborne=state['airborne'],drops=state['drops'],dropped=state['dropped'],custody=sorted(state['custody']),support=sorted(support),goal_table_support=on_table,handovers=state['transitions'],handovers_valid_from_s=state['valid_from'],spill=state['spill'])
            if handover_required:reports[ident].update(airborne_handover_met=handover_met,handover_protocol=self.HANDOVER_PROTOCOL)
            if fraction_contract:
                reports[ident].update(timber_inside_fraction=fraction,
                    timber_inside_fraction_min=mon.task['completion']['timber_inside_fraction_min'])
        complete=completed==len(self.states)
        mon.result_cache=dict(all_goals_met=complete,task_success=complete and not mon.violations,completed_payloads=completed,total_payloads=len(self.states),payloads=reports,drops=sum(s['drops'] for s in self.states.values()))
        if mon.task.get('run_protocol', {}).get('evaluation_semantics') == 'terminal_outcome_v2':
            terminal_complete=terminal_completed==len(self.states)
            mon.result_cache.update(all_goals_met=terminal_complete,task_success=terminal_complete,
                terminal_goal_met=terminal_complete,terminal_completed_payloads=terminal_completed,
                completed_payloads=terminal_completed,legacy_completed_payloads=completed,
                legacy_process_goals_met=complete,strict_task_success=complete and not mon.violations,
                scoring_version='terminal_outcome_v2')
