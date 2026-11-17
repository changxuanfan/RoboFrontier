"""The Oracle's recoveries: owner-reviewed, forward-only repairs of one live world.

Single-robot forward recovery (all families): Forward-only Oracle recovery at an explicitly idle ownership handover. The owner reviews independent single-robot sequences; this module never plans tasks. RuntimeService owns a separate prepared-world lifecycle, so this adapter reuses PandaArm and Trial's execution/recording primitives without another DB.

Transport handback: Engineering handback for a live Transport world, without arbitrary code exec. The research owner may submit ordinary bounded robot commands or request a fresh goal plan from measured state. Inputs and their provenance are archived. No state rewind, score reset, unknown-action adoption or implicit success.

Relay live repair: Keep one known physical world alive for typed, owner-reviewed Oracle repair. This engineering interface exposes privileged observations. It is not a GPT policy tool, physical restart checkpoint, or arbitrary Python execution hook.

Dial live repair: Oracle-only live repair channel. Never reads passwords or assigns state. A recoverable reference failure retains the world and blind solver. Research can inspect timestamped geometry/images and submit ordinary bounded actions. All interventions and failed plans remain in the episode record. This is not an autonomous policy harness and grants no new observations to GPT task roles.

Merged on 2026-11-11 from recovery, transport_recovery, relay_live_recovery and dial_live_repair.
"""
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import re
import threading
import time
import uuid

import numpy as np

from ..runtime.setup import write_json
from .transport_full_oracle import execute_job,goal_coverage,candidate_graph,path_between
from .transport_runtime import PreparationComplete
from .transport_oracle import _robot_payload_contacts
from .transport_grasp_safety import requires_contact_recovery
from ..physics.robot_control import quat_matrix
from . import relay_oracle as ref
from .protocol import process_blocks
from .trial import ReferenceStopped


# ---- Single-robot forward recovery (all families)
class RecoverablePlanError(RuntimeError):
    """Owner-declared planning fault, never an automatic physics exception."""


class OracleRecovery:
    def __init__(self, trial, *, owner, world_id, observe):
        if getattr(trial, '_oracle_recovery_attachment', None) is not None:
            raise ValueError('This world already has a recovery execution owner')
        if any(arm.job is not None or getattr(arm,'uncertainty_reported',False) for arm in trial.arms.values()):
            raise ValueError('Attach only at an idle, exclusive execution handover')
        from .protocol import process_blocks,unresolved_robots
        if not process_blocks(trial) and unresolved_robots(trial):
            raise ValueError('Original action feedback must be resolved before recovery handover')
        self.trial, self.owner, self.world_id, self.observe = trial, owner, world_id, observe
        self.requests, self.running, self.reserved, self.unknown = {}, {}, {}, {}
        self.recoveries, self.paused = {}, False
        self.dt = float(trial.model.opt.timestep)
        self.directory = Path(trial.directory)/'recovery'
        for folder in ('requests', 'results', 'sources', 'rejected'):
            (self.directory/folder).mkdir(parents=True, exist_ok=True)
        self.files, self.sources, self.assisted = {}, {}, False
        self.last_observation = -math.inf
        self.thread, self.closed = threading.get_ident(), False
        self.attached, self.submitted_actions = True, 0
        self.original_execute = trial.execute
        trial._oracle_recovery_attachment = self
        write_json(self.directory/'world.json', dict(owner=owner, world_id=world_id,
            scope='Trusted owner identity, not an OS security sandbox'))
        trial.execute = self._blocked_legacy_execute

    def _thread(self, execution=True):
        if threading.get_ident() != self.thread or self.closed:
            raise ValueError('Use the single live physics owner thread')
        if execution and not self.attached:
            raise ValueError('Execution was handed back; this adapter cannot step or submit')
        if execution and getattr(self.trial,'physics_failure',None):
            raise ValueError('Invalid physical trajectory cannot be repaired as valid evidence')

    def _blocked_legacy_execute(self, *args, **kwargs):
        raise ValueError('Recovery owns execution; drain and explicitly handoff before Trial.execute')

    @staticmethod
    def _evidence(value):
        try:
            value = json.loads(json.dumps(value, allow_nan=False))
        except (TypeError, ValueError) as error:
            raise ValueError('Owner observation must be finite JSON, never Trial/Monitor') from error
        if not isinstance(value, dict) or set(value)-{'task', 'robots', 'objects', 'actions', 'images'}:
            raise ValueError('Only owner-selected observation fields are allowed')
        def inspect(node):
            if isinstance(node, dict):
                for key, child in node.items():
                    if key.lower() in ('game', 'secret', 'decoder', 'unobserved_feedback') or key.lower().startswith('private'):
                        raise ValueError('Hidden game/feedback fields are not repair observations')
                    inspect(child)
            elif isinstance(node, list):
                for child in node:
                    inspect(child)
        inspect(value)
        return value

    def _source(self, request):
        source = request.get('repair_source')
        if source is None:
            return
        path = Path(source['path'])
        path = (self.directory/path).resolve() if not path.is_absolute() else path.resolve()
        if not path.is_relative_to(self.directory.resolve()) or path.suffix != '.py':
            raise ValueError('Repair source must be an owner-directory Python file')
        payload = path.read_bytes(); digest = hashlib.sha256(payload).hexdigest()
        if source['sha256'] != digest:
            raise ValueError('Repair source SHA mismatch')
        target = self.directory/'sources'/(digest+'.py')
        if target.exists() and target.read_bytes() != payload:
            raise ValueError('Archived repair source changed')
        if not target.exists():
            target.write_bytes(payload)
        # Owner evaluates this module externally. The physics thread never execs it.
        self.sources[digest] = dict(sha256=digest, archived_path=str(target), execution='external_owner')

    def _publish(self, ident):
        write_json(self.directory/'results'/(ident+'.json'), self.status(ident))

    def submit(self, request):
        self._thread()
        request = json.loads(json.dumps(request, allow_nan=False))
        if set(request)-{'owner', 'world_id', 'id', 'robot', 'sequence', 'review',
                        'recovery_id', 'assisted', 'repair_source'}:
            raise ValueError('Unsupported recovery request field')
        if request['owner'] != self.owner or request['world_id'] != self.world_id:
            raise ValueError('Request does not belong to this world owner')
        ident, robot, steps = request['id'], request['robot'], request['sequence']
        if not isinstance(ident, str) or re.fullmatch(r'[A-Za-z0-9_-]{1,96}', ident) is None:
            raise ValueError('Use a bounded plain request ID')
        if ident in self.requests:
            if self.requests[ident]['request'] != request:
                raise ValueError('Request ID reused with different input')
            return self.status(ident)
        from .protocol import process_blocks,unresolved_robots
        if not process_blocks(self.trial) and robot in unresolved_robots(self.trial):
            raise ValueError('Original action feedback is unresolved; never replay')
        if self.paused or robot in self.reserved or robot in self.unknown:
            raise ValueError('Robot paused, reserved, or outcome uncertain')
        if robot not in self.trial.arms or self.trial.arms[robot].job is not None:
            raise ValueError('Unknown or externally busy robot')
        recovery = self.recoveries.get(request.get('recovery_id'))
        affected = [r for r in self.recoveries.values()
                    if robot in r['robots'] and r['status'] != 'feedback_ready']
        if ('recovery_id' in request and (recovery is None or robot not in recovery['robots'])):
            raise ValueError('Recovery does not match this robot')
        if affected and recovery not in affected:
            raise ValueError('Affected robot requires the matching owner recovery input')
        if not request.get('review') or not isinstance(steps, list) or not 1 <= len(steps) <= 64:
            raise ValueError('Owner review and a finite sequence are required')
        if any(set(s) != {'op', 'parameters'} or s['op'] not in ('move', 'gripper')
               or not isinstance(s['parameters'], dict) for s in steps):
            raise ValueError('Only ordinary finite robot commands are supported')
        if not isinstance(request.get('assisted', False), bool):
            raise ValueError('Assistance is an explicit owner attestation')
        self._source(request)
        self.assisted |= request.get('assisted', False)
        rec = dict(request=deepcopy(request), status='queued', next_step=0, feedback=[])
        rec['input_sha256'] = hashlib.sha256(json.dumps(request, sort_keys=True).encode()).hexdigest()
        self.requests[ident] = rec; self.reserved[robot] = ident
        if recovery is not None:
            recovery['status'] = 'repair_running'
        self._publish(ident)
        self.trial.event('oracle_recovery_input', request_id=ident, input_sha256=rec['input_sha256'],
                         assisted=request.get('assisted', False), repair_source=request.get('repair_source'))
        self._start(ident)
        return self.status(ident)

    def _start(self, ident):
        rec = self.requests[ident]; req = rec['request']; robot = req['robot']
        if self.paused:
            self._finish(ident, 'failed', 'Paused before next command'); return
        step = req['sequence'][rec['next_step']]; t = self.trial
        try:
            prepared = t.arms[robot].validate(step['op'], step['parameters'], t.cfg,
                t.task['workspace_world_m']['lower'], t.task['workspace_world_m']['upper'])
        except (ValueError, KeyError, TypeError) as error:
            self._finish(ident, 'failed', 'Admission rejected: '+str(error)); return
        call_id = f'recovery-{ident}-{rec["next_step"]}'
        self.running[robot] = dict(id=ident, call_id=call_id, start=t.time, step=step)
        rec.update(status='running', active_call_id=call_id)
        self._publish(ident)
        t.event('action_start', label=call_id, commands={robot:(step['op'], step['parameters'])})
        self.submitted_actions += 1
        try:
            t.arms[robot].start(call_id, prepared, t.time)
        except Exception as error:
            self.unknown[robot] = call_id
            self._finish(ident, 'uncertain', 'Executor acknowledgement failed: '+str(error))

    def _finish(self, ident, status, reason=None):
        rec = self.requests[ident]; robot = rec['request']['robot']
        rec.update(status=status, reason=reason, finished_sim_s=self.trial.time)
        if status != 'uncertain':
            rec['active_call_id'] = None
        self.reserved.pop(robot, None)
        recovery = self.recoveries.get(rec['request'].get('recovery_id'))
        if recovery is not None:
            recovery['status'] = 'needs_engineering_review' if status == 'uncertain' else 'feedback_ready'
        self._publish(ident)

    def recover(self, error, robots, *, evidence=None):
        self._thread()
        if not isinstance(error, RecoverablePlanError):
            raise ValueError('Only an explicitly marked planning fault is recoverable here')
        if not robots or any(r not in self.trial.arms or self.trial.arms[r].job is not None
                             or r in self.reserved or r in self.unknown for r in robots):
            raise ValueError('Recovery requires known idle affected robots')
        ident = f'plan-{len(self.recoveries)+1}'
        rec = dict(id=ident, robots=list(robots), status='awaiting_owner',
                   error=str(error), evidence=self._evidence(evidence or {}), sim_time_s=self.trial.time)
        self.recoveries[ident] = rec
        self.trial.event('oracle_recovery_requested', recovery=rec)
        self.service()
        return deepcopy(rec)

    def service(self):
        self._thread()
        for path in sorted((self.directory/'requests').glob('*.json')):
            payload = path.read_bytes(); digest = hashlib.sha256(payload).hexdigest()
            if self.files.get(str(path)) == digest:
                continue
            self.files[str(path)] = digest
            try:
                self.submit(json.loads(payload))
            except (ValueError, KeyError, TypeError, OSError) as error:
                write_json(self.directory/'rejected'/(digest+'.json'), dict(error=str(error), input_sha256=digest))
                self.trial.event('oracle_recovery_input_rejected', input_sha256=digest, reason=str(error))
        if self.trial.time-self.last_observation >= .5:
            try:
                write_json(self.directory/'observation.json', self.observation())
            except (ValueError, TypeError) as error:
                # Bad observation selection cannot expose secrets or stop other work.
                write_json(self.directory/'observation-error.json', dict(error=str(error)))
                self.trial.event('oracle_recovery_observation_rejected', reason=str(error))
            self.last_observation = self.trial.time

    def advance(self, seconds):
        self._thread()
        if not math.isfinite(seconds) or seconds < 0:
            raise ValueError('Finite forward duration required')
        if float(self.trial.model.opt.timestep) != self.dt:
            raise ValueError('Physics timestep changed')
        for _ in range(round(seconds/self.dt)):
            if self.trial.tick % self.trial.stride == 0:
                self.service()
            for robot, arm in self.trial.arms.items():
                expected = self.running.get(robot, {}).get('call_id', self.unknown.get(robot))
                if arm.job is not None and arm.job != expected:
                    raise ValueError('Foreign in-flight action; adapter must not steal its poll')
            self.trial.step()
            if self.trial.tick % self.trial.stride:
                continue
            for robot, active in list(self.running.items()):
                result = self.trial.arms[robot].poll(self.trial.time, 15)
                if result is None:
                    continue
                ident = active['id']; rec = self.requests[ident]
                rec['feedback'].append(deepcopy(result)); self.running.pop(robot)
                if result['status'] == 'uncertain':
                    self.unknown[robot] = active['call_id']
                    self._finish(ident, 'uncertain', result.get('reason')); continue
                self.trial.actions.append(dict(label=active['call_id'],
                    commands={robot:(active['step']['op'], active['step']['parameters'])},
                    results={robot:result}, start_sim_s=active['start'], end_sim_s=self.trial.time))
                self.trial.event('action_end', label=active['call_id'], results={robot:result})
                if rec['status'] == 'uncertain':
                    rec.update(terminal_feedback=deepcopy(result), active_call_id=None)
                    self._publish(ident); continue
                rec['next_step'] += 1
                if result['status'] != 'completed':
                    self._finish(ident, 'failed', result.get('reason'))
                elif rec['next_step'] == len(rec['request']['sequence']):
                    self._finish(ident, 'completed')
                else:
                    self._start(ident)
                self._publish(ident)

    def status(self, ident):
        self._thread(False)
        return deepcopy(self.requests[ident])

    def observation(self):
        self._thread(False)
        return dict(world_id=self.world_id, sim_time_s=self.trial.time,
                    requests=deepcopy(self.requests), recoveries=deepcopy(self.recoveries),
                    evidence=self._evidence(self.observe()))

    def handoff(self, owner):
        """Return the live world to legacy code only after a known drained boundary."""
        self._thread()
        if (owner != self.owner or self.running or self.reserved or self.unknown
            or any(a.job is not None for a in self.trial.arms.values())
            or any(r['status'] != 'feedback_ready' for r in self.recoveries.values())):
            raise ValueError('Resolve all executions/recovery feedback before legacy handoff')
        self.trial.execute = self.original_execute
        self.attached = False
        self.trial.event('oracle_recovery_legacy_handoff', owner=owner)

    def reattach(self, owner):
        """Allow a later repair boundary without creating a second owner."""
        self._thread(False)
        if (owner != self.owner or self.attached or self.running or self.reserved or self.unknown
            or any(a.job is not None for a in self.trial.arms.values())
            or self.trial.execute != self.original_execute):
            raise ValueError('Reattach only from a known idle legacy handover')
        self.attached=True;self.paused=False
        self.trial.execute=self._blocked_legacy_execute
        self.trial.event('oracle_recovery_reattached', owner=owner)

    def acknowledge(self, owner, ident, review, assisted=False):
        """Owner closes a reviewed boundary only after all feedback is known."""
        self._thread()
        if (owner != self.owner or ident not in self.recoveries or not review
            or self.running or self.reserved or self.unknown
            or any(a.job is not None for a in self.trial.arms.values())):
            raise ValueError('Known idle reviewed recovery required')
        if not isinstance(assisted,bool):raise ValueError('Assistance must be explicit')
        self.assisted |= assisted
        self.recoveries[ident].update(status='feedback_ready',review=str(review))
        self.trial.event('oracle_recovery_reviewed', recovery_id=ident,review=str(review))

    def pause(self, owner):
        self._thread()
        if owner != self.owner:
            raise ValueError('Only the world owner may pause')
        self.paused = True
        for robot in self.running:
            self.trial.arms[robot].request_stop(self.trial.time, 'Paused by Oracle owner')

    def resume(self, owner):
        self._thread()
        if owner != self.owner or self.running or self.reserved or self.unknown:
            raise ValueError('Resume only after known terminal feedback')
        self.paused=False
        self.trial.event('oracle_recovery_resumed', owner=owner)

    def fence(self, owner, ident, reason):
        """Preserve an uncertain acknowledgement; terminal feedback cannot auto-clear it."""
        self._thread()
        if owner != self.owner or self.requests[ident]['status'] != 'running':
            raise ValueError('Only the owner may fence its active execution')
        robot = self.requests[ident]['request']['robot']
        self.unknown[robot] = self.running[robot]['call_id']
        self._finish(ident, 'uncertain', reason)
        self.trial.event('oracle_recovery_execution_fenced', request_id=ident, reason=reason)

    def review_terminal(self, owner, ident, review, *, assisted=False):
        """Resolve one acknowledgement using this owner's original poll result.

        Never resume the remaining sequence or turn a failed motor call into
        success. Legacy/strict fences keep their original behavior.
        """
        self._thread()
        from .protocol import process_blocks
        if process_blocks(self.trial) or owner!=self.owner or not review or not isinstance(assisted,bool):
            raise ValueError('Task-reference owner review is required')
        rec=self.requests[ident];robot=rec['request']['robot']
        result=rec.get('terminal_feedback',{})
        arm=self.trial.arms[robot]
        if (rec['status']!='uncertain' or robot in self.running or arm.job is not None
                or getattr(arm,'uncertainty_reported',False)
                or not result.get('call_id') or self.unknown.get(robot)!=result['call_id']
                or result.get('status') not in ('completed','failed')):
            raise ValueError('Original terminal motor feedback is required; never infer from idle state')
        self.assisted |= assisted
        resolution=dict(original_status='uncertain',terminal_feedback=deepcopy(result),
                        review=str(review),assisted=assisted,sim_time_s=self.trial.time,
                        remaining_sequence_replayed=False)
        rec.update(status='resolved',execution_resolution=resolution)
        self.unknown.pop(robot)
        recovery=self.recoveries.get(rec['request'].get('recovery_id'))
        if recovery is not None:recovery['status']='feedback_ready'
        self.trial.event('oracle_execution_resolved',robot=robot,request_id=ident,
                         result=deepcopy(result),review=str(review),assisted=assisted)
        self._publish(ident)
        return self.status(ident)

    def close(self, report):
        if self.closed:
            return
        self._thread(False)
        report['unresolved_robot_actions'] = sorted(set(self.unknown) |
            {r for r, a in self.trial.arms.items() if a.job is not None})
        from .protocol import process_blocks
        if report['unresolved_robot_actions'] or (process_blocks(self.trial) and self.trial.monitor.violations):
            report['passed'] = False
        metadata = dict(llm_used=self.assisted, assisted=self.assisted,
            oracle_mode='privileged_assisted' if self.assisted else 'pure_program',
            recovery=dict(world_id=self.world_id, owner=self.owner, sources=list(self.sources.values()),
                inputs=[dict(id=i, input_sha256=r['input_sha256']) for i,r in self.requests.items()],
                requests=deepcopy(self.requests), boundaries=deepcopy(self.recoveries),
                retained_process_violations=deepcopy(self.trial.monitor.violations),
                submitted_robot_actions=self.submitted_actions, legacy_handoff_supported=True,
                restart_supported=False, source_modules_hot_executed=False))
        report.update(metadata)  # trial_end must already carry the correct classification.
        self.trial.close(report)
        report.update(metadata)  # Preserve adapter classification after core close.
        write_json(self.trial.directory/'report.json', report)
        self.trial.execute = self.original_execute
        self.closed = True


# ---- Transport handback
class EngineeringRecovery:
    def __init__(self,directory,on_idle=None,inventory_check=None,on_review=None):
        self.path=Path(directory)/'recovery'
        for name in ('inbox','accepted','rejected','reviews'): (self.path/name).mkdir(parents=True,exist_ok=True)
        self.seen=set();self.external_inputs=[];self.next_poll=0.;self.counter=0
        self.waiting=False;self.failed_progress={};self.automatic_progress={}
        self.on_idle=on_idle;self.inventory_check=inventory_check
        self.on_review=on_review

    def on_terminal(self,t,runtime,ident,job,kind):
        fault=kind=='failed' and requires_contact_recovery(job.get('error'))
        review=kind=='prepared' and job.get('pause_after_prepare',False)
        if fault:job['manual_recovery_required']=True
        if not (fault or review) or self.on_review is None:return
        # The failed/prepared scope has known terminal actions. Independent
        # actions may remain live; preserve those controllers rather than
        # adopting, cancelling or replaying them during engineering review.
        if any(t.arms[r].job is not None or t.arms[r].uncertainty_reported for r in job['robots']):return
        notice=dict(job=ident,kind=kind,reason=str(job.get('error')) if fault else 'Explicit prepared-state review',
            preserved_action_ids={r:a.job for r,a in t.arms.items() if a.job is not None})
        state=self.observation(t,runtime);state['engineering_review']=notice
        write_json(self.path/'frontier.json',state)
        write_json(self.path/'reviews'/(ident+'-'+kind+'.json'),state)
        self.on_review(t,runtime,notice)

    def observation(self,t,runtime):
        def support(name):
            if not hasattr(t.monitor,'geoms') or name not in t.monitor.geoms:return None
            velocity=None
            if hasattr(t.data,'joint'):
                velocity=np.asarray(t.data.joint(name+'_free').qvel[:3]).tolist()
            target=t.monitor.geoms[name]
            return dict(geometric_bilateral=sorted(t.monitor.bilateral(target)),
                positive_force_bilateral=sorted(t.monitor.bilateral(target,positive_force=True)),
                linear_velocity_m_s=velocity)
        failed={ident:dict(goal=job.get('goal'),object=job.get('object'),error=str(job.get('error')),
            error_type=type(job.get('error')).__name__,manual_recovery_required=job.get('manual_recovery_required',False),
            measured_support=support(job.get('object')),
            prepared_reservations=job.get('prepared_reservations',[]),
            robots=sorted(job['robots']),retained=[r for r,owner in runtime.leases.items() if owner==ident])
            for ident,job in runtime.jobs.items() if job['status'] in ('failed','prepared') and not job.get('recovered_by')}
        return dict(schema='transport.engineering-frontier.v1',scene_sha256=t.task['scene_sha256'],
            sim_time_s=t.time,wall_s=time.monotonic()-t.started,failed_jobs=failed,
            accepted_goals=t.monitor.result().get('assignments',{}),retained_resources=runtime.leases,
            robots={r:a.observe() for r,a in t.arms.items()},
            objects={o['id']:dict(position_m=t.data.body(o['id']).xpos.tolist(),rotation=t.data.body(o['id']).xmat.tolist()) for o in t.env['objects']},
            held=dict(t.held),active_robots=sorted(runtime.running),updated_at_unix_s=time.time(),
            socket_release_phases=getattr(t,'socket_release_phases',{}),
            inventory_warnings=getattr(t,'oracle_inventory_warnings',[]),
            state_qpos=t.data.qpos.tolist(),state_qvel=t.data.qvel.tolist(),
            capabilities=['coherent_qpos_qvel','retain_robots_on_prepare','pause_after_prepare','known_action_fault_review','measured_payload_support','immutable_review_snapshots'],
            source='Privileged engineering observation; never a GPT benchmark policy input')

    def _retry(self,t,runtime,ident,request):
        old=runtime.jobs[ident]
        if old.get('recovered_by'):raise ValueError('This failure already has a recovery owner')
        goal=old['goal'];name=old['object']
        retained={r for r,owner in runtime.leases.items() if owner==ident}
        requested=request.get('robots')
        if requested is None:
            robots=retained|{r for r in old['robots'] if r not in runtime.leases}
            p=t.data.body(goal['board']).xpos
            nearby=sorted((r for r in t.arms if r not in runtime.leases),
                key=lambda r:np.linalg.norm(np.asarray(t.stations[r]['base_position_m'])[:2]-p[:2]))[:2]
            robots.update(nearby)
        else:robots=retained|set(requested)
        if robots-set(t.arms):raise ValueError('Unknown recovery robot')
        if not robots:raise ValueError('No available recovery robot')
        if requested is None and goal['goal_id'] not in t.monitor.result().get('assignments',{}):
            starts=[r for r in robots if t.arms[r].grasp_force is not None and t.finger_contacts(r,name)]
            if not starts:
                point=t.data.body(name).xpos
                starts=[r for r in robots if np.linalg.norm(np.asarray(t.stations[r]['base_position_m'])[:2]-point[:2])<=.90]
            destinations=set(goal_coverage(t,goal))&robots
            graph={r:[s for s in ns if s in robots] for r,ns in candidate_graph(t).items() if r in robots}
            if not any(path_between(graph,start,end) for start in starts for end in destinations):
                raise ValueError('No currently available recovery route; preserve the original failed scope')
        original=dict(id=goal['goal_id'],goal=goal,object=name,path=list(robots),attempts=1)
        steps=request.get('steps',[])
        resume=request.get('resume_goal',True)
        if not isinstance(resume,bool):raise ValueError('resume_goal must be boolean')
        keep=request.get('retain_robots',[]);pause=request.get('pause_after_prepare',False)
        if not isinstance(keep,list) or any(not isinstance(r,str) for r in keep) or set(keep)-robots:
            raise ValueError('Prepared reservations must be robots in this recovery scope')
        if not isinstance(pause,bool) or (resume and (keep or pause)):
            raise ValueError('Reservations and prepared review require resume_goal:false')
        if pause and self.on_review is None:raise ValueError('Prepared review pause is unavailable in this executor')
        if not isinstance(steps,list) or len(steps)>64:raise ValueError('At most 64 ordinary recovery steps')
        for step in steps:
            if 'wait_s' in step:
                if set(step)!={'wait_s'} or not 0<=float(step['wait_s'])<=30:raise ValueError('Invalid bounded wait')
            elif set(step)!={'robot','operation','parameters'} or step['robot'] not in robots or step['operation'] not in ('move','gripper') or not isinstance(step['parameters'],dict):
                raise ValueError('Only leased ordinary robot commands are accepted')
        def recover():
            for step in steps:
                if 'wait_s' in step:t.wait(float(step['wait_s']))
                else:t.execute('engineering-repair',{step['robot']:(step['operation'],step['parameters'])})
            if not resume:
                for actor,held in list(t.held.items()):
                    if actor in robots and t.arms[actor].grasp_force is None and not _robot_payload_contacts(t,actor,held):
                        t.held.pop(actor)
                        getattr(t,'socket_released_payload',{}).pop(actor,None)
                        getattr(t,'socket_release_phases',{}).pop(actor,None)
                        t.event('transport_measured_carrier_cleared',robot=actor,object=held)
                raise PreparationComplete(retain_robots=keep,pause_after_prepare=pause)
            return execute_job(t,runtime,original,resume=True)
        self.counter+=1;new_id=goal['goal_id']+'-recovery-'+str(self.counter)
        if not runtime.recover(ident,new_id,robots,recover):raise ValueError('Requested recovery resources are still busy')
        if new_id in runtime.jobs:
            runtime.jobs[new_id]['manual_recovery_required']=bool(not resume and old.get('manual_recovery_required'))
        return new_id

    def poll(self,t,runtime,jobs,pending,force=False):
        if not force and time.monotonic()<self.next_poll:return False
        if self.inventory_check is not None:
            lost=self.inventory_check(t)
            if lost:
                from .protocol import process_blocks
                from .transport_inventory import UnreachableTransportInventory
                if process_blocks(t):
                    if t.motion is not None:t.motion.capture(t.data,force=True)
                    t.event('transport_inventory_unreachable',objects=lost)
                    raise UnreachableTransportInventory('Required stock left the admitted robot workspace: '+str(lost))
                signature=tuple(sorted(item['object'] for item in lost))
                if getattr(t,'oracle_inventory_warning_ids',None)!=signature:
                    t.event('transport_inventory_review_required',objects=lost,
                            scope='Finite stock reach heuristic; not a proof of task impossibility')
                t.oracle_inventory_warning_ids=signature
                t.oracle_inventory_warnings=lost
            else:
                t.oracle_inventory_warnings=[];t.oracle_inventory_warning_ids=()
        self.next_poll=time.monotonic()+1.;state=self.observation(t,runtime)
        write_json(self.path/'frontier.json',state);changed=False
        # Explicit owner repairs acquire resources before heuristic retries.
        for file in sorted((self.path/'inbox').glob('*.json')):
            if file.name in self.seen:continue
            try:
                payload=file.read_bytes();request=json.loads(payload)
                if not isinstance(request,dict):raise ValueError('Engineering input must be an object')
                if set(request)-{'id','job','scene_sha256','robots','steps','reason','author','resume_goal','retain_robots','pause_after_prepare'}:raise ValueError('Unsupported engineering input')
                # Provenance must be complete before any admission side effect.
                missing={'id','job','scene_sha256'}-set(request)
                if missing:raise ValueError('Missing engineering input fields: '+str(sorted(missing)))
                if not isinstance(request['id'],str) or not request['id'] or not isinstance(request['job'],str):raise ValueError('Engineering input id and job must be strings')
                if request['id'] in {item['id'] for item in self.external_inputs}:raise ValueError('Duplicate engineering input id')
                if request['scene_sha256']!=t.task['scene_sha256']:raise ValueError('Wrong physical scene')
                ident=request['job']
                if ident not in runtime.jobs or runtime.jobs[ident]['status'] not in ('failed','prepared'):raise ValueError('No matching failed or prepared job')
                new_id=self._retry(t,runtime,ident,request)
                record=dict(id=request['id'],source_file=file.name,sha256=hashlib.sha256(payload).hexdigest(),
                    input=request,admitted_sim_s=t.time,recovery_job=new_id)
                self.external_inputs.append(record);write_json(self.path/'accepted'/file.name,record)
                t.event('transport_engineering_input',**record);self.seen.add(file.name);changed=True
            except (ValueError,KeyError,TypeError) as error:
                write_json(self.path/'rejected'/file.name,dict(error=str(error),sim_time_s=t.time));self.seen.add(file.name)
        # New accepted progress justifies another geometric plan, but a known
        # contact/support fault needs measured owner recovery first.
        for ident,failed in list(state['failed_jobs'].items()):
            if getattr(runtime,'jobs',{}).get(ident,{}).get('manual_recovery_required'):continue
            count=len(state['accepted_goals']);baseline=self.failed_progress.setdefault(ident,count)
            goal=failed['goal']['goal_id']
            if count>self.automatic_progress.get(goal,-1) and (count>baseline or goal in state['accepted_goals']):
                try:self._retry(t,runtime,ident,{});self.automatic_progress[goal]=count;changed=True
                except ValueError:pass
        return changed

    def __call__(self,t,runtime,jobs,pending):
        self.waiting=True
        t.event('transport_engineering_handback',frontier=str(self.path/'frontier.json'),
            scope='Live world retained; independent jobs already continue through the same runtime')
        t.snapshot('recovery-frontier')
        self.poll(t,runtime,jobs,pending,force=True)
        next_wall=time.monotonic()
        while not runtime.active:
            if self.on_idle is not None:self.on_idle(t,runtime)
            t.check_stop()
            if self.poll(t,runtime,jobs,pending,force=self.on_idle is not None):break
            if self.on_idle is not None:continue
            # Keep gravity, contact and holding alive at approximately real
            # time during owner diagnosis. This waiting counts in the trial.
            runtime.step();next_wall+=float(t.model.opt.timestep)
            delay=next_wall-time.monotonic()
            if delay>0:time.sleep(min(delay,.02))
        self.waiting=False
        return runtime.active


# ---- Relay live repair
def continuation_options(value):
    fields={'future_region','future_yaw','future_fraction','future_height','future_waypoints','landing_point','require_topdown'}
    if not isinstance(value,dict) or set(value)-fields:raise ValueError('Unsupported receiving continuation field')
    if value and 'future_region' not in value:raise ValueError('Receiving continuation needs its reference region')
    def point(v):
        p=np.asarray(v,dtype=float)
        if p.shape!=(3,) or not np.isfinite(p).all():raise ValueError('Finite continuation XYZ required')
    for key in ['future_region','landing_point']:
        if key in value:point(value[key])
    for key in ['future_yaw','future_fraction','future_height']:
        if key in value and not math.isfinite(float(value[key])):raise ValueError('Finite continuation scalar required')
    if 'future_fraction' in value and not 0<=value['future_fraction']<=1:raise ValueError('Continuation fraction outside0..1')
    waypoints=value.get('future_waypoints',[])
    if not isinstance(waypoints,list) or len(waypoints)>4:raise ValueError('At most four finite continuation waypoints')
    for step in waypoints:
        if not isinstance(step,(list,tuple)) or len(step)!=2:raise ValueError('Continuation waypoint is XYZ,yaw')
        point(step[0])
        if not math.isfinite(float(step[1])):raise ValueError('Finite waypoint yaw required')
    if 'require_topdown' in value and not isinstance(value['require_topdown'],bool):raise ValueError('Topdown preference must be boolean')
    return dict(value)


class RelayLiveRecovery:
    def __init__(self,trial,report):
        self.trial=trial;self.report=report;self.directory=trial.directory/'recovery'
        for name in ('requests','results','accepted','rejected'):(self.directory/name).mkdir(parents=True,exist_ok=True)
        self.world_id=uuid.uuid4().hex;self.handled={};self.assisted=False
        write_json(self.directory/'world.json',dict(world_id=self.world_id,pid=__import__('os').getpid(),
            scope='Same live privileged Oracle world; finite typed repair; no reset/pose writes',
            operations=['carry','place','release','place_release','handover','grasp','open','move_empty','stop','wait','resume']))

    def publish(self,error=None):
        t=self.trial;result=t.monitor.result()
        payloads={}
        for item in t.task['mechanism']['payload_assemblies']:
            ident=item['id'];body=t.data.body(ident)
            payloads[ident]=dict(position_m=body.xpos.tolist(),rotation=body.xmat.reshape(3,3).tolist(),
                actual_support=sorted(t.monitor.bilateral(t.monitor.relay.states[ident]['rod_geoms'],positive_force=True)),
                state=result['payloads'][ident])
        from .relay_observation_state import native_kinematic_state
        write_json(self.directory/'observation.json',dict(world_id=self.world_id,sim_time_s=t.time,
            native_kinematic_state=native_kinematic_state(t),
            wall_elapsed_s=time.monotonic()-t.started,error=error,held=dict(t.held),
            active_jobs={a:r.job for a,r in t.arms.items() if r.job is not None},
            robots={a:r.observe() for a,r in t.arms.items()},payloads=payloads,goal=t.task['route'][-1],
            evaluation=result,visibility='Privileged engineering Oracle only'))
        try:t.snapshot('recovery-live',('global','global_rear'))
        except Exception as image_error:write_json(self.directory/'image-error.json',dict(error=repr(image_error)))

    def process(self,request):
        ident=request.get('id');digest=hashlib.sha256(json.dumps(request,sort_keys=True,allow_nan=False).encode()).hexdigest()
        if not isinstance(ident,str) or re.fullmatch(r'[A-Za-z0-9_-]{1,80}',ident) is None:raise ValueError('Invalid repair ID')
        if ident in self.handled:
            old=self.handled[ident]
            if old['request_sha256']!=digest:raise ValueError('Repair ID reused with different input')
            return old
        if request.get('world_id')!=self.world_id:raise ValueError('Request belongs to another world')
        if set(request)-{'id','world_id','op','payload','robots','target_m','yaw_rad','retain_attitude','offset_m','seconds','review','assisted','retained_side','continuation','joint_rad','target_quaternion_wxyz'}:raise ValueError('Unsupported repair field')
        if not request.get('review') or request.get('assisted') is not True:raise ValueError('External model repair requires review and assisted attestation')
        t=self.trial
        op=request.get('op')
        if any(a.job is not None or getattr(a,'uncertainty_reported',False) for a in t.arms.values()) and op!='stop':raise ValueError('Original execution unresolved; request controlled stop, never replay')
        if process_blocks(t) and t.monitor.violations:raise ValueError('Irreversible process history retained; repair cannot erase it')
        if getattr(t,'physics_failure',None):raise ValueError('Invalid physical trajectory cannot be repaired as valid evidence')
        if op not in {'carry','place','release','place_release','handover','grasp','open','move_empty','stop','wait','resume'}:raise ValueError('No state/reset/physics editing operation')
        if 'joint_rad' in request and op!='move_empty':raise ValueError('Joint target applies only to observed empty-robot movement')
        if 'target_quaternion_wxyz' in request and op!='carry':raise ValueError('Payload orientation applies only to coupled carry')
        payload=request.get('payload');team=request.get('robots',[])
        if op not in {'wait','resume','stop'}:
            if payload not in t.monitor.relay.states:raise ValueError('Unknown payload')
            if (len(team)!=1 if op=='move_empty' else len(team)<2) or len(set(team))!=len(team) or any(a not in t.arms for a in team):raise ValueError('Use one observed empty robot or an actual support team')
            support=t.monitor.bilateral(t.monitor.relay.states[payload]['rod_geoms'],positive_force=True)
            if op not in {'grasp','open','move_empty'} and not set(team)<=support:raise ValueError('Declared holders lack actual bilateral support')
        continuation=continuation_options(request.get('continuation',{}))
        if continuation and op!='handover':raise ValueError('Receiving continuation applies only to handover')
        side=request.get('retained_side')
        if side is not None and (op!='handover' or type(side) is not int or side not in (0,1) or len(team)!=2):raise ValueError('Retain one side of an existing two-holder handover')
        self.assisted=True;self.report['execution_mode']='privileged_assisted';self.report['llm_used']=True
        write_json(self.directory/'accepted'/(ident+'.json'),request)
        t.event('relay_repair_admitted',request=request,request_sha256=digest,world_id=self.world_id)
        result=dict(id=ident,request_sha256=digest,status='running',world_id=self.world_id,start_sim_s=t.time)
        try:
            if op=='move_empty':
                ref.move_empty_robot(t,payload,team[0],request['joint_rad'])
            elif op=='carry':
                point=np.asarray(request['target_m'],dtype=float)
                if point.shape!=(3,) or not np.isfinite(point).all():raise ValueError('Finite XYZ required')
                rotation=t.data.body(payload).xmat.reshape(3,3).copy()
                if 'target_quaternion_wxyz' in request:
                    if request.get('retain_attitude') is True or 'yaw_rad' in request:raise ValueError('Choose one carried orientation: quaternion, retained attitude or yaw')
                    quaternion=np.asarray(request['target_quaternion_wxyz'],dtype=float)
                    if quaternion.shape!=(4,) or not np.isfinite(quaternion).all() or abs(np.linalg.norm(quaternion)-1.)>1e-6:raise ValueError('Finite unit wxyz quaternion required')
                    target_rotation=quat_matrix(quaternion)
                else:target_rotation=rotation if request.get('retain_attitude',True) else None
                yaw=float(request.get('yaw_rad',math.atan2(rotation[1,0],rotation[0,0])))
                if not math.isfinite(yaw):raise ValueError('Finite yaw required')
                ref.carry(t,payload,team,point,yaw,target_rotation=target_rotation)
            elif op in {'place','place_release'}:
                ref.place(t,payload,team);t.wait(.3)
                if op=='place_release':ref.release(t,payload,team,terminal=True);t.wait(1.2)
            elif op=='release':
                if not ref.final_support(t,payload,team):raise ValueError('Establish real in-goal beam support before releasing')
                ref.release(t,payload,team,terminal=True);t.wait(1.2)
            elif op=='handover':
                offset=request.get('offset_m',.32);body=t.data.body(payload)
                retained={} if side is None else {side:team[side]}
                receivers=ref.choose_team(t,payload,body.xpos.copy(),body.xmat.reshape(3,3).copy(),offset,exclude=team,search_budget_s=60.,retained=retained,**continuation)
                ref.grasp(t,payload,receivers,offset);t.wait(.3);ref.release(t,payload,[robot for robot in team if robot not in receivers])
                result['receivers']=receivers
            elif op=='grasp':
                state=t.monitor.relay.states[payload]
                if process_blocks(t) and state['dropped'] and not set(team)<=state['custody']:raise ValueError('Only original custody may recover a drop')
                body=t.data.body(payload);offset=request.get('offset_m',.44)
                continuing=set(team)&support
                if len(continuing)>1:raise ValueError('Already supported; use an explicit retained handover for regrasp')
                retained={}
                if continuing:
                    if process_blocks(t) and not set(team)<=state['custody']:raise ValueError('Partial support recovery belongs to original custody')
                    robot=next(iter(continuing));arm=t.arms[robot]
                    local=body.xmat.reshape(3,3).T@(t.data.site_xpos[arm.site]-body.xpos)
                    retained={int(local[1]>=0):robot}
                selected=ref.choose_team(t,payload,body.xpos.copy(),body.xmat.reshape(3,3).copy(),offset,
                    exclude=(set(t.arms)-set(team))|continuing,retained=retained,departing=(),search_budget_s=60.)
                ref.grasp(t,payload,selected,offset);result['holders']=selected
            elif op=='open':
                state=t.monitor.relay.states[payload]
                supported=t.monitor.relay.environment_contact(state['all_geoms'])
                from .relay_user_goal_policy import opening_supported
                if not supported:supported=opening_supported(t,payload)
                if not supported:raise ValueError('Opening recovery requires actual table or approved Goal support')
                if any(t.held.get(a) not in (None,payload) for a in team):raise ValueError('Cannot open a hand labelled with different cargo')
                t.execute('recovery-open-supported',{a:('gripper',dict(mode='move',width_m=.08,speed_m_s=.06)) for a in team})
                for a in team:
                    if not ref.arm_payload_contact(t,payload,a):t.held.pop(a,None)
            elif op=='stop':
                original={a:r.job for a,r in t.arms.items() if r.job is not None};feedback={};started=t.time
                for a in original:t.arms[a].request_stop(t.time,'Owner controlled stop for recovery')
                while any(t.arms[a].job is not None for a in original) and t.time-started<15.:
                    t.step()
                    for a in original:
                        value=t.arms[a].poll(t.time,15)
                        if value is not None:feedback[a]=value
                result['original_jobs']=original;result['original_feedback']=feedback
                if any(t.arms[a].job is not None for a in original):raise RuntimeError('Original stop remains unresolved')
            elif op=='wait':
                seconds=float(request.get('seconds',.5))
                if not 0<=seconds<=2:raise ValueError('Finite wait0..2s only')
                t.wait(seconds)
            elif op=='resume':
                if t.held:raise ValueError('Finish the held frontier before restarting remaining tabletop work')
                result['resume_remaining']=True
            result['status']='completed'
        except Exception as error:
            result.update(status='failed',error=type(error).__name__+': '+str(error))
        result.update(end_sim_s=t.time,evaluation=t.monitor.result(),unresolved=[a for a,r in t.arms.items() if r.job is not None])
        self.handled[ident]=result;write_json(self.directory/'results'/(ident+'.json'),result)
        t.event('relay_repair_result',detail=result);self.report.setdefault('repair_results',[]).append(result)
        return result

    def wait_for_repair(self,error=None):
        t=self.trial
        if error is not None:
            self.report.setdefault('recoverable_failures',[]).append(dict(error=repr(error),sim_time_s=t.time))
        t.event('relay_recovery_boundary' if error is not None else 'relay_owner_boundary',error=repr(error) if error is not None else None,world_id=self.world_id)
        self.publish(str(error) if error is not None else None);next_publish=time.monotonic()+2.;anchor_wall=time.monotonic();anchor_sim=t.time
        while True:
            t.check_stop()
            if t.monitor.result().get('task_success') and not any(a.job is not None for a in t.arms.values()):
                t.wait(.5);return 'complete'
            for path in sorted((self.directory/'requests').glob('*.json')):
                try:
                    request=json.loads(path.read_text());result=self.process(request)
                    path.unlink()
                    self.publish(result.get('error'))
                    if result.get('resume_remaining') and result['status']=='completed':return 'resume'
                except Exception as rejection:
                    write_json(self.directory/'rejected'/path.name,dict(error=repr(rejection)));path.unlink()
                anchor_wall=time.monotonic();anchor_sim=t.time
            # Keep force holds/physics/recording alive while the owner thinks.
            desired=anchor_sim+(time.monotonic()-anchor_wall)
            # A large world may integrate slower than real time. Poll between
            # short batches instead of letting accumulated wall debt starve
            # queued repairs. Every ordinary physics step is still recorded.
            for _ in range(25):
                if t.time+.001>=desired:break
                t.step()
            if time.monotonic()>=next_publish:self.publish(str(error) if error is not None else None);next_publish=time.monotonic()+2.
            time.sleep(.01)


# ---- Dial live repair
class LiveRepair:
    def __init__(self,trial,operator):
        self.t=trial;self.m=operator;self.index=0;self.path=trial.directory/'recovery';self.path.mkdir()
        self.interventions=0;self.adapter=None;self.owner="dial-reference-owner"

    def settle(self):
        t=self.t;old=t.abort_on_process_violation;t.abort_on_process_violation=False
        try:
            if self.adapter is not None and self.adapter.attached:
                self.adapter.pause(self.owner)
                for _ in range(800):
                    if not self.adapter.running:break
                    self.adapter.advance(.02)
                if self.adapter.running or self.adapter.unknown:raise RuntimeError('Recovery waits for unresolved executor feedback')
                self.adapter.resume(self.owner);return
            for arm in t.arms.values():
                if arm.job is not None:arm.request_stop(t.time,reason='reference_recovery_boundary')
            for _ in range(round(16/t.model.opt.timestep)):
                busy=[a for a in t.arms.values() if a.job is not None]
                if not busy:return
                t.step()
                for arm in busy:
                    result=arm.poll(t.time,15.)
                    if result:t.event('reference_recovery_terminal_action',robot=arm.name,result=result)
            raise RuntimeError('Recovery cannot replay unknown active actions')
        finally:t.abort_on_process_violation=old and not bool(t.monitor.violations)

    def devices(self):
        t=self.t
        devices={}
        for a in self.m.dials:
            body=t.data.body(a['id']+'_module')
            devices[a['id']]=dict(position_m=body.xpos.tolist(),quaternion_wxyz=body.xquat.tolist(),
                angle_deg=float(t.data.joint(a['id']+'_hinge').qpos[0]*180/3.141592653589793),
                blue_ready=bool(t.monitor.dial_ready[a['index']]),nominal_robots=a['nominal_robots'])
        return devices

    def snapshot(self,error,guess):
        t=self.t;folder=self.path/f'pause-{self.index:03d}';folder.mkdir()
        t.snapshot('recovery-'+str(self.index))
        state=dict(pause=self.index,phase='awaiting_repair',error=str(error),sim_time_s=t.time,requested=guess,
                   best=t.monitor.game.display,robots={r:a.observe() for r,a in t.arms.items()},devices=self.devices(),
                   violations=t.monitor.violations,private_password_included=False,
                   waiting_physics='Paused at current live state; wall budget continues; not evidence of physical holding duration',
                   command_schema='plan.json: {source:research_gpt, batches:[{actor:[move|gripper,params]}], resume:true}')
        write_json(folder/'state.json',state);write_json(self.path/'awaiting.json',dict(pause=self.index,folder=str(folder),error=str(error)))
        t.event('reference_awaiting_live_repair',pause=self.index,error=str(error),folder=str(folder),
                scope='World/solver retained; no qpos restore, no violation removal')
        return folder

    def sync(self):
        t=self.t
        for a in self.m.dials:
            grip=self.m.grips.get(a['id'])
            if grip and t.arms[grip['robot']].grasp_force is None and t.monitor.released(self.m.red_geoms(a)):
                self.m.grips.pop(a['id']);t.event('reference_forget_released_grip',dial=a['id'])
            if t.task['level']>1:
                robot=a['nominal_robots'][1]
                if t.arms[robot].grasp_force is None:t.held.pop(robot,None)
                elif robot in t.monitor.bilateral([g for g,i in t.monitor.blue.items() if i==a['index']]):t.held[robot]=a['id']+'_module'

    def recover(self,error,guess):
        if isinstance(error,ReferenceStopped):raise error
        if str(error).startswith(('Numerical physics failure','Nonfinite physical state','Planning scratch cannot')):raise error
        t=self.t;self.settle();self.index+=1;folder=self.snapshot(error,guess)
        waiting_started=time.monotonic()
        if t.monitor.violations:
            t.continued_after_violation=True;t.continue_after_recorded_violation=True
        if self.adapter is None:
            world=hashlib.sha256(str(t.directory).encode()).hexdigest()[:16]
            self.adapter=OracleRecovery(t,owner=self.owner,world_id=world,observe=lambda:{
                'task':{'id':t.task['id'],'best':t.monitor.game.display},
                'robots':{r:a.observe() for r,a in t.arms.items()},'objects':self.devices()})
        elif not self.adapter.attached:self.adapter.reattach(self.owner)
        recovery=self.adapter.recover(RecoverablePlanError(str(error)),list(t.arms),evidence={
            'task':{'reason':str(error),'requested':guess},'objects':self.devices()})
        while True:
            t.check_stop();plan=folder/'plan.json'
            if not plan.exists():
                t._heartbeat('awaiting_recovery');time.sleep(.25);continue
            self.interventions+=1;t.oracle_repair_interventions=self.interventions
            try:
                payload=plan.read_text();plan.rename(folder/f'plan-{self.interventions:03d}.json');request=json.loads(payload)
                if set(request)-{'source','batches','resume'} or request.get('source')!='research_gpt':raise ValueError('Bad repair envelope')
                t.event('reference_live_repair_plan',pause=self.index,intervention=self.interventions,plan=request,
                        scope='Online research GPT physical recovery through existing OracleRecovery; decoder remains blind')
                statuses=[]
                for i,batch in enumerate(request.get('batches',[])):
                    if not isinstance(batch,dict) or not batch:raise ValueError('Repair batch must map actors to commands')
                    identifiers=[]
                    for actor,command in batch.items():
                        if actor not in t.arms or not isinstance(command,list) or len(command)!=2 or command[0] not in ('move','gripper'):raise ValueError('Only existing robot commands are accepted')
                        ident=f'dial-{self.index}-{self.interventions}-{i}-{actor}';identifiers.append(ident)
                        self.adapter.submit(dict(owner=self.owner,world_id=self.adapter.world_id,id=ident,robot=actor,
                            sequence=[dict(op=command[0],parameters=command[1])],review='Research GPT physical recovery plan',
                            recovery_id=recovery['id'],assisted=True))
                    while self.adapter.running:self.adapter.advance(.02)
                    statuses.extend(self.adapter.status(ident) for ident in identifiers)
                    if any(s['status']!='completed' for s in statuses):raise RuntimeError('A repair action failed; feedback retained, world remains available')
                self.sync();t.snapshot('repair-applied-'+str(self.interventions))
                write_json(folder/f'result-{self.interventions:03d}.json',dict(applied=True,sim_time_s=t.time,
                    robots={r:a.observe() for r,a in t.arms.items()},devices=self.devices(),violations=t.monitor.violations,requests=statuses))
                if request.get('resume'):
                    self.adapter.acknowledge(self.owner,recovery['id'],'Owner resumes the reference from observed current state',assisted=True)
                    self.adapter.handoff(self.owner)
                    t.event('reference_live_repair_resumed',pause=self.index,repair_wall_s=time.monotonic()-waiting_started,
                        waiting_physics='Explicit engineering pause; no integration during owner reasoning')
                    write_json(self.path/'awaiting.json',dict(pause=self.index,phase='resuming',sim_time_s=t.time));return
            except ReferenceStopped:raise
            except Exception as failure:
                self.settle();write_json(folder/f'result-{self.interventions:03d}.json',dict(applied=False,error=str(failure),sim_time_s=t.time))
                t.event('reference_live_repair_failed',pause=self.index,error=str(failure))
