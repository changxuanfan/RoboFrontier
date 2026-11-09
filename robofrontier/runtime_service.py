"""Policy/admin tool protocol with an injected execution owner.

No GUI or model calls are made here. Tests inject FakeWorld; pipeline injects
MuJoCo and keeps all physics/rendering on its GUI thread.
"""
import fcntl
import json
import math
from pathlib import Path
import queue
import secrets
import sqlite3
import threading
import time

from .runtime_store import RuntimeStore
from . import run_layout
from .run_setup import verify_inputs, write_json
from .delegation import Delegations
from .scene_task import camera_names
from .stop_diagnostics import stop_diagnostics
from .task_config import action_limits, execution_timing


class RuntimeService:
    def __init__(self, directory, world_factory, capture, video_factory=None):
        self.store = None
        self.world_lock = None
        self.owns_world = False
        self.world = None
        try:
            self._initialize(directory, world_factory, capture, video_factory)
        except BaseException:
            self.close()
            raise

    def _initialize(self, directory, world_factory, capture, video_factory):
        self.directory = Path(directory).resolve()
        if not (self.directory/'private/inputs/manifest.json').is_file():
            raise ValueError('Prepare a new run first with scripts/create_pipeline_run.py')
        manifest = json.loads((self.directory/'private/inputs/manifest.json').read_text())
        if manifest.get('schema_version') != 3:
            raise ValueError('Historical run: use its frozen tools; no automatic migration')
        lock = run_layout.path(self.directory, 'world_lock')
        lock.parent.mkdir(parents=True, exist_ok=True)
        self.world_lock = lock.open('a+')
        try:
            fcntl.flock(self.world_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.world_lock.close()
            raise ValueError('Another process owns this physical world')
        self.store = RuntimeStore(self.directory/'private/state/runtime.sqlite')
        self.owns_world = False
        self.world = None
        self.video = None
        self.finished_video = self.store.get('video')
        self.last_integrity_check = time.monotonic()
        self.config = self.store.get('config')
        self.task = json.loads((self.directory/'private/inputs/task.json').read_text())
        self.policy_budget = None
        if self.task.get('execution_readiness') == 'prepared_policy_trial':
            from .policy_probe import BudgetGuard, protocol, run_clock
            self.policy_budget = BudgetGuard(protocol(self.task['run_protocol']['total_wall_limit_s'],
                                                      run_clock(self.task['run_protocol'])))
        self.roles = tuple(self.store.agents())
        self.policy_roles = tuple(a for a in self.roles if self.store.agent(a)['kind'] != 'manager')
        self.tokens = {}
        for actor in self.roles:
            conn = json.loads((self.directory/'private/state/connections'/f'{actor}.json').read_text())
            if conn.get('run_id') != self.directory.name or conn.get('schema_version') != 3:
                self.close()
                raise ValueError('Connection belongs to another run/protocol')
            self.tokens[actor] = conn['token']
        self.capture = capture
        self.video_factory = video_factory
        self.lock = threading.RLock()
        self.queue = queue.Queue()
        self.requests = {}
        self.waiters = {}
        self.action_batches = {}
        self.recovery_checks = {}
        self.motion_check = None
        self.shutdown = False
        lifecycle = self.store.get('lifecycle')
        # A run that continues after an unexpected exit was prepared for it explicitly
        # (run_segments.prepare_retry); every other restart is refused.
        resuming = lifecycle == 'resuming' and not self.store.get('execution_owner_attached')
        if (lifecycle != 'prepared' and not resuming) or self.store.get('execution_owner_attached'):
            # Reading a run must never silently recreate its physical world.
            if lifecycle not in ('ended', 'interrupted'):
                self.recover_execution()
                self.store.put('dispatch_paused', True)
                self.store.put('lifecycle', 'interrupted')
                self.store.put('physics_state', 'stopped')
                self.store.event('RUN_INTERRUPTED', 'Meta', {'reason':'Previous execution owner ended'})
            self.close()
            raise ValueError('Physical restart is unsupported; inspect this run and prepare a new run')
        if verify_inputs(self.directory):
            self.close()
            raise ValueError('Prepared inputs changed; prepare a new run')
        self.store.put('execution_owner_attached', True)
        self.owns_world = True
        self.world = world_factory(self.directory, self.task)
        from .egress_pause import WorldPause
        self.egress_pause = WorldPause(self)
        self.store.event('EXECUTION_OWNER_ATTACHED', 'Meta', {'segment': self.store.get('segment', 0)})
        if resuming:
            # The trial's recorders start now; the run itself resumes on the host's `resume`.
            begin = getattr(self.world, 'start_trial', None)
            if begin is not None: begin()

    def recover_execution(self):
        """Settle unfinished execution as unknown; a failure here must not hide the interruption."""
        try:
            self.store.recover_execution()
        except Exception as error:
            # The recovery transaction rolled back; the run is still recorded as interrupted
            # and its unsettled calls stay as they were for engineering review.
            self.store.event('EXECUTION_RECOVERY_FAILED', 'Meta', {'reason': type(error).__name__+': '+str(error)})

    @property
    def started(self):
        return self.store.get('lifecycle') != 'prepared'

    @property
    def ended(self):
        return self.store.get('lifecycle') in ('ended', 'interrupted', 'recovery_required')

    def close(self):
        try:
            if self.store:
                try:
                    if self.owns_world:
                        if getattr(self,'egress_pause',None) is not None:self.egress_pause.close()
                        if getattr(self,'policy_budget',None) is not None:self.policy_budget.flush(self.store)
                        if getattr(self,'motion_check',None) is not None:
                            job,_ = self.motion_check
                            self.respond(job, {'motion_check':{'assessment':'unknown','reason':'Execution owner closed during screening','advisory_only':True}})
                            job['done'].set()
                            self.motion_check = None
                        self.stop_video()
                        if self.store.get('lifecycle') != 'ended':
                            self.recover_execution()
                            self.store.put('dispatch_paused', True)
                            self.store.put('lifecycle', 'interrupted')
                            self.store.put('physics_state', 'stopped')
                            self.store.event('RUN_INTERRUPTED', 'Meta', {'reason':'Execution owner closed; no physical replay'})
                            try:
                                from .run_segments import output_dir
                                folder = output_dir(self.directory, self.store.get('segment', 0))
                                folder.mkdir(parents=True, exist_ok=True)
                                write_json(folder/'interruption-evaluation.json',
                                    {'task_success':False,'scope':'Postmortem geometry only; interrupted trial is not a success',
                                     'sim_time_s':float(self.world.time),'evaluation':self.world.evaluate()})
                                self.save_evaluation_evidence('interruption-evaluation-window.json', folder)
                            except Exception as error:
                                self.store.event('INTERRUPTION_EVALUATION_UNAVAILABLE','Meta',{'reason':str(error)})
                        self.check_integrity()
                        self.export_records()
                finally:
                    self.store.close()
                    self.store = None
        finally:
            close_world=getattr(self.world,'close',None)
            if callable(close_world):close_world()
            if self.world_lock and not self.world_lock.closed:
                fcntl.flock(self.world_lock, fcntl.LOCK_UN)
                self.world_lock.close()

    # Robot motion requests; none may start once the run has ended.
    PHYSICAL_OPS = ('move', 'gripper', 'action_batch')
    ENDED_REQUEST = 'The run has ended; no new robot action is accepted'

    def accept(self, actor, op, data, call_id, ack_delivery=None):
        with self.lock:
            if not isinstance(data,dict):raise ValueError('Tool data must be an object')
            if ack_delivery:
                self.store.acknowledge(actor, ack_delivery)
            old = self.store.begin_call(call_id, actor, op, data)
            if call_id in self.requests:
                return self.requests[call_id]
            job = {'id': call_id, 'actor': actor, 'op': op, 'data': data, 'done': threading.Event(), 'result': None}
            self.requests[call_id] = job
            if old['status'] in ('completed', 'failed'):
                job['result'] = json.loads(old['result']) if old['result'] else \
                    {'call_id': call_id, 'execution_status': 'failed', 'error': 'Call ended without a recorded result; do not replay'}
                job['done'].set()
            elif old['status'] == 'uncertain':
                job['result'] = {'call_id': call_id, 'execution_status': 'uncertain', 'error': 'Query original execution; do not replay'}
                job['done'].set()
            elif old['status'] == 'running':
                job['result'] = {'call_id': call_id, 'execution_status': 'running', 'note': 'Execution owner must supply the original result'}
                job['done'].set()
            elif op in self.PHYSICAL_OPS and self.ended:
                # A request arriving as the run closes gets a definite failure at once; left
                # accepted, it could never settle and would block the run's seal.
                self.respond(job, {'error': self.ENDED_REQUEST})
                job['done'].set()
            else:
                self.queue.put(job)
            return job

    def respond(self, job, result):
        with self.store.transaction():
            answer = {'call_id': job['id'], **result}
            if self.ended:
                answer['run_ended'] = True
            if self.store.get('dispatch_paused',False) or self.store.get('physics_state')=='paused_by_user':
                answer['run_paused'] = True
            if self.store.agent(job['actor'])['kind'] != 'manager' and 'messages' not in answer:
                answer.update(self.store.delivery(job['actor']))
            self.store.finish_call(job['id'], answer)
            self.store.event('TOOL_RETURN', job['actor'], {'call_id': job['id'], 'op': job['op'],
                             'result': answer if job['op'] != 'state' else {'snapshot': True}})
            job['result'] = answer
        # The outer operation releases the client after its transaction commits.

    def check_startable(self):
        """The task's START gates. World.start_trial repeats them as it opens the recorders."""
        readiness = self.task.get('execution_readiness')
        if readiness == 'environment_preview_only':
            raise ValueError('This v2 scene is an environment preview. Mechanism-specific evaluation and recording commissioning are required before starting a policy trial.')
        if readiness == 'prepared_policy_trial':
            from .task_families import validate_frozen_policy
            validate_frozen_policy(self.task, self.directory)

    def fault_injected(self):
        """The run's one engineering fault already fired, in this or an earlier segment.

        A continued segment builds a new world whose fault state starts afresh; the run
        store is what remembers that the fault was applied."""
        if not getattr(self, '_fault_injected', False):
            self._fault_injected = self.store.db.execute(
                "SELECT 1 FROM events WHERE kind='ENGINEERING_FAULT_INJECTED' LIMIT 1").fetchone() is not None
        return self._fault_injected

    def stopping_diagnostics(self, action):
        arm=getattr(self.world,'arms',{}).get(action['arm'])
        if hasattr(self.world,'stop_diagnostics') or arm is not None and hasattr(arm,'data'):
            return stop_diagnostics(self.world,action['arm'],action['action_id'],action)
        return action.get('stop_diagnostics')

    def isolated_diagnostics(self, action):
        arm=getattr(self.world,'arms',{}).get(action['arm'])
        if arm is None:
            return {'controller_state':'unavailable',
                    'note':'The executor cannot report this robot; the original result remains unknown.'}
        current=getattr(arm,'job',None)
        state='original_active' if current==action['action_id'] else 'no_active_action' if current is None else 'different_action_active'
        result={'controller_state':state,'stopping':bool(getattr(arm,'stopping',False)),
                'note':'This is the current controller state, not proof of the original action outcome.'}
        if hasattr(arm,'observe'):result['robot']=arm.observe()
        return result

    def snapshot(self):
        agents = self.store.agents()
        return {'schema_version': 3, 'lifecycle': self.store.get('lifecycle'), 'started': self.started,
                'segment': self.store.get('segment', 0), 'segments': self.store.get('segments') or [],
                'downtime_s': self.store.get('downtime_s', 0.),
                # Active running time, kept only by runs whose protocol counts it (policy_probe.BudgetGuard).
                **({'active_s': self.store.get('active_s')} if self.store.get('active_s') is not None else {}),
                'ended': self.ended, 'sim_time_s': float(self.world.time) if self.world else None, 'agents': agents,
                'unread': {a: self.store.pending(a)['messages'] for a in self.policy_roles},
                'messages': [self.store._message(r) for r in self.store.db.execute('SELECT * FROM messages ORDER BY seq')],
                'jobs': self.store.actions(), 'events': self.store.events(100),
                'recording': bool(self.video), 'video': self.finished_video,
                'dispatcher_health':self.store.get('dispatcher_health',{}),
                'dispatcher_paused': self.store.get('dispatch_paused', False),
                'delegations':Delegations(self.store).active() if self.config['topology']=='adaptive' else []}

    def register_delegates(self, batch):
        """Scoped connections are runtime state, not edits to frozen inputs."""
        parent_path=self.directory/'private/state/connections'/f"{batch['parent']}.json"
        url=json.loads(parent_path.read_text())['url']
        for child in batch['children']:
            actor=child['actor'];path=self.directory/'private/state/connections'/f'{actor}.json'
            if not path.exists():
                write_json(path,{'schema_version':3,'run_id':self.directory.name,'url':url,
                                 'actor':actor,'token':secrets.token_urlsafe(24)})
            self.tokens[actor]=json.loads(path.read_text())['token']
        self.roles=tuple(self.store.agents())
        self.policy_roles=tuple(a for a in self.roles if self.store.agent(a)['kind']!='manager')

    def selected_cameras(self, cameras, allow_empty=False):
        allowed = set(camera_names(self.task))
        if (not isinstance(cameras,list) or (not cameras and not allow_empty)
            or any(not isinstance(name,str) for name in cameras)
            or len(set(cameras)) != len(cameras) or not set(cameras) <= allowed):
            raise ValueError('Select distinct allowed camera names')
        return cameras

    def handle(self, job):
        actor, op, data = job['actor'], job['op'], job['data']
        kind = self.store.agent(actor)['kind']
        manager = kind == 'manager'
        try:
            if op in ('bind','start','resume','state','shutdown') and not manager:
                raise ValueError('Meta administrative operation')
            if manager and op not in ('bind','start','resume','state','shutdown','observe'):
                raise ValueError('Meta observes/administers; business decisions and robot actions belong to policy roles')
            # Queued before the run ended but reached after it: still never started.
            if op in self.PHYSICAL_OPS and self.ended:
                raise ValueError(self.ENDED_REQUEST)
            if op == 'ready':
                facts=self.world.robot_facts(self.config)
                self.store.update_agent(actor, ready=True)
                self.respond(job, {'ready': True, 'run_started': self.started,
                    'robot_facts':facts,
                    'controlled_robots':([r for r,o in Delegations(self.store).owners().items() if o==actor]
                        if self.config['topology']=='adaptive' else list(self.task['arms']) if kind=='controller' else [actor] if kind=='worker' else []),
                    'limits': {k: self.config[k] for k in ('min_check_interval_s','max_check_interval_s','allowed_tcp_speed_m_s','default_tcp_speed_m_s','motion_check')},
                    'execution_timing':execution_timing(self.config),
                    'cameras': camera_names(self.task), 'action_limits':action_limits(self.config),
                    'action_batch':{'supported':True,'authority':'Each owner submits only its own members; optional sync_group collects signed parts',
                        'sync_group':{'fields':['id','robots','timeout_s'],'timeout_max_s':self.config['max_check_interval_s'],
                                      'before_start':'Pending own-robot reservation; roster/timeout immutable; revalidate all when complete'},
                        'start':'Same control cycle; not synchronized arrival or a coupled controller',
                        'failure':'Stop remaining group arm motions; retain established force grasps; inspect individual outcomes'}})
            elif op == 'robot_model':
                if set(data)-{'robot'}:raise ValueError('robot_model accepts an optional robot ID')
                selected=data.get('robot')
                if selected is not None and selected not in self.task['arms']:raise ValueError('Unknown robot ID')
                model=self.world.robot_model(self.config)
                path=self.directory/'public/robot-models'/(model['model_id']+'.json')
                if not path.exists():write_json(path,model)
                header={k:v for k,v in model.items() if k!='robots'}
                robots=({selected:model['robots'][selected]} if selected else
                        {name:{'body_count':len(value['bodies']),'collision_geom_count':len(value['collision_geoms'])}
                         for name,value in model['robots'].items()})
                self.respond(job, {'robot_model':{**header,'robots':robots,'detail':'robot' if selected else 'summary',
                                                 'result_ref':str(path)}})
            elif op == 'check_motion':
                if self.ended or self.store.get('physics_state')=='paused_by_user':
                    raise ValueError('Motion screening unavailable while paused/ended')
                if self.motion_check is not None:
                    raise ValueError('One read-only motion check is already computing; retry later with a new call ID')
                self.motion_check = (job,self.world.check_motion(data,self.config))
            elif op == 'bind':
                target = data['actor']
                if self.store.agent(target)['kind'] == 'manager':
                    raise ValueError('Policy binding only')
                if self.started:
                    raise ValueError('Binding is frozen after START')
                self.store.update_agent(target, thread_id=data['thread_id'])
                self.respond(job, {'bound': True})
            elif op == 'start':
                if self.store.get('lifecycle') != 'prepared':
                    raise ValueError('Run already started or ended')
                changed = verify_inputs(self.directory)
                if changed:
                    raise ValueError('Prepared inputs changed: '+str(changed))
                policy = [v for v in self.store.agents().values() if v['kind'] != 'manager']
                now = time.time()
                protocol = self.config.get('startup_protocol', 'ready_barrier_v1')
                if protocol == 'direct_controller_v2':
                    if len(policy) != 1 or policy[0]['kind'] != 'controller' or not policy[0]['thread_id']:
                        raise ValueError('Direct START requires one bound Controller')
                elif protocol == 'direct_team_v3':
                    threads = [v['thread_id'] for v in policy]
                    if not threads or not all(threads) or len(set(threads)) != len(threads):
                        raise ValueError('Direct team START requires every initial role bound to a distinct session')
                elif not all(v['ready'] and v['thread_id'] and v['session_status']=='idle' and v['session_observed_at'] is not None and 0 <= now-v['session_observed_at'] <= self.config['session_observation_ttl_s'] for v in policy):
                    raise ValueError('Import fresh actual idle session observations before START')
                # The trial's START gates run before START is committed, so a refused START
                # leaves the run prepared: no START event, start time or video.
                self.check_startable()
                if self.video_factory:
                    self.video = self.video_factory()
                self.store.start()
                begin=getattr(self.world,'start_trial',None)
                if begin is not None:begin()
                self.store.put('start_sim_time',float(self.world.time))
                self.last_integrity_check = time.monotonic()
                self.respond(job, {'started': True})
            elif op == 'resume':
                # Continue the same trial in the segment prepared after an unexpected exit.
                if self.store.get('lifecycle') != 'resuming':
                    raise ValueError('No segment is waiting to resume')
                changed = verify_inputs(self.directory)
                if changed:
                    raise ValueError('Prepared inputs changed: '+str(changed))
                from .run_segments import begin_segment, export, resume_message
                with self.store.transaction():
                    record = begin_segment(self.store)
                    self.store.put('lifecycle', 'running')
                    self.store.put('physics_state', 'running')
                    self.store.put('dispatch_paused', False)
                if self.video_factory:
                    self.video = self.video_factory()
                self.last_integrity_check = time.monotonic()
                export(self.directory, self.store)
                # Roles still at work: not returned delegates, and only roles with a session.
                working = [a for a in self.policy_roles if self.store.agent(a)['thread_id'] and
                           (self.store.agent(a)['kind'] != 'delegate' or self.store.agent(a).get('delegation_state') == 'active')]
                messages = {a: resume_message(self.directory, a, record) for a in working}
                self.respond(job, {'resumed': True, 'segment': record['index'], 'messages': messages})
            elif op == 'send':
                with self.store.transaction():
                    m = self.store.send(actor, data['to'], data['text'], job['id'], data.get('reply_to'))
                    self.respond(job, {'message_id': m['message_id'], 'delivery': 'durable inbox, not business acceptance'})
                if self.ended:
                    self.export_records()
            elif op == 'inbox':
                self.respond(job, self.store.delivery(actor))
            elif op == 'wait_events':
                if self.store.get('lifecycle') == 'prepared':
                    raise ValueError('Before START save waiting state and end the READY turn')
                if any(w['job']['actor'] == actor for w in self.waiters.values()):
                    raise ValueError('An event wait is already pending for this role; retry its original ID')
                timeout = float(data.get('timeout_s', 30))
                if not math.isfinite(timeout) or not 0 <= timeout <= self.config['max_check_interval_s']:
                    raise ValueError('Wait deadline outside run limits')
                action_ids = data.get('call_ids', [])
                if not isinstance(action_ids, list) or any(not isinstance(v, str) for v in action_ids):
                    raise ValueError('call_ids must be a list of your action IDs')
                expanded=[]
                for action_id in action_ids:
                    original=self.store.call(action_id,actor)
                    if original['op']=='action_batch':
                        from .action_batch import member_ids
                        expanded.extend(member_ids(self.store,action_id))
                    else:expanded.append(action_id)
                action_ids=list(dict.fromkeys(expanded))
                for action_id in action_ids:
                    self.store.call(action_id, actor)
                    if action_id not in self.store.actions(actor):
                        raise ValueError('Wait only for your physical action IDs')
                self.waiters[job['id']] = {'job': job, 'deadline': time.monotonic()+timeout,
                                           'call_ids': action_ids}
            elif op == 'history':
                self.respond(job, {'messages': self.store.history(actor)})
            elif op == 'work':
                if set(data)-{'delegate_id'}:raise ValueError('work accepts an optional delegate_id')
                selected=data.get('delegate_id')
                parent=self.config['topology']=='adaptive' and actor=='Controller'
                if selected is not None and not parent:raise ValueError('Only Controller inspects its own delegates')
                self.respond(job, {'work': self.store.agent(actor),
                                   'execution':self.store.latest_execution(actor),
                                   'active_executions':{i:a for i,a in self.store.actions(actor).items() if a['status'] in ('pending','running','uncertain')},
                                   'sampled_at':time.time(),
                                   **({'delegations':Delegations(self.store).active(),
                                       'delegate_status':Delegations(self.store).status(actor,selected),
                                       'robot_owners':Delegations(self.store).owners()}
                                      if parent else {})})
            elif op == 'delegate':
                batch=Delegations(self.store).create(actor,job['id'],data['scopes'])
                self.register_delegates(batch)
                # Keep parent at its native tool boundary until forks are bound
                # and initial input is delivered. Robot physics keeps advancing.
            elif op == 'return_task':
                event=Delegations(self.store).return_task(actor,data['outcome'],data['result'])
                self.respond(job,{'returned':True,'delegation':event})
            elif op == 'team':
                if kind != 'team-controller':
                    raise ValueError('Hierarchical Controller team view only')
                with self.store.transaction():
                    workers={a:{'work':{'note':v['note'], 'saved_at':v.get('work_saved_at'), 'revision':v['work_revision']},
                                'execution':self.store.latest_execution(a),
                                'session':{'status':v['session_status'], 'observed_at':v['session_observed_at']}}
                             for a,v in self.store.agents().items() if v['kind']=='worker'}
                    self.respond(job, {'workers':workers, 'sampled_at':time.time(),
                                       'note':'Saved notes can lag newer messages and execution. Execution does not prove task completion, acceptance or clearance.'})
            elif op in ('checkpoint', 'yield'):
                state = data.get('state', 'working' if op=='checkpoint' else 'waiting')
                if op == 'yield' and state == 'working':
                    raise ValueError('Yield as waiting, available or continue')
                if (op=='yield' and state in ('waiting','available') and self.store.get('lifecycle')=='running'
                    and not self.store.get('dispatch_paused',False) and self.store.get('physics_state')=='running'
                    and data.get('after_s') is None):
                    raise ValueError('Choose after_s for a finite self-selected review while the team run is active')
                with self.store.transaction():
                    value = self.store.checkpoint_work(actor, state, data['note'], data.get('after_s'))
                    self.respond(job, {'saved': True, 'work': value})
            elif op == 'observe':
                cameras = data.get('cameras', ['global'] if kind!='worker' else [actor+'_front',actor+'_side'])
                self.respond(job, {'observation': self.capture(self.selected_cameras(cameras))})
            elif op == 'stop':
                if set(data)-{'robot','call_id'}:raise ValueError('stop accepts robot and the active call_id')
                original=self.store.call(data['call_id'],actor)
                if original['op']=='action_batch':
                    if 'robot' in data:raise ValueError('Stop a batch without robot; or stop an individual member ID')
                    from .action_batch import stop
                    batch=self.action_batches.get(data['call_id'])
                    if batch:stop(self,batch)
                    self.respond(job,{'stop_requested':bool(batch),'original_call_id':data['call_id'],
                                      'note':'Stops running group arm motions, not gripper force holds; inspect original batch results'})
                    job['done'].set();return
                robot=self.store.action_robot(actor,data.get('robot'))
                original=self.store.call(data['call_id'],actor)
                action=self.store.actions(actor).get(data['call_id'])
                if not action or action['arm']!=robot:raise ValueError('Stop requires an own action on the selected robot')
                if action['status']=='uncertain':
                    if not action.get('isolated'):raise ValueError('Uncertain execution requires engineering review')
                    diagnostic=self.isolated_diagnostics(action)
                    if diagnostic['controller_state']!='original_active':
                        self.respond(job,{'stop_requested':False,'original_call_id':data['call_id'],
                            'execution':action,'execution_diagnostics':diagnostic,
                            'note':'The original action is not confirmed active; inspect the robot. The original outcome remains unknown.'})
                        job['done'].set();return
                    self.world.request_stop(robot,data['call_id'])
                    self.store.event('STOP_REQUESTED',actor,{'robot':robot,'call_id':data['call_id']})
                    self.respond(job,{'stop_requested':True,'original_call_id':data['call_id'],
                        'execution':action,'execution_diagnostics':diagnostic,
                        'note':'Stop requested for the original action; inspect and query that action until the owner confirms its result.'})
                    job['done'].set();return
                if action['status']=='pending' and action.get('sync_group_id'):
                    from .action_batch import cancel_collecting
                    cancel_collecting(self.store,'withdrawn_by_participant',float(self.world.time),action['sync_group_id'])
                    self.respond(job,{'stop_requested':True,'original_call_id':data['call_id'],'note':'Unstarted sync group cancelled'})
                    job['done'].set();return
                if action['status']=='running':
                    self.world.request_stop(robot,data['call_id'])
                    self.store.event('STOP_REQUESTED',actor,{'robot':robot,'call_id':data['call_id']})
                self.respond(job,{'stop_requested':action['status']=='running','original_call_id':data['call_id'],
                                  'execution':action,'note':'A stop request is not a terminal result; query the original action'})
            elif op=='action_batch':
                from .action_batch import submit
                submit(self,job)
            elif op in ('move', 'gripper'):
                robot = self.store.action_robot(actor, data.get('robot'))
                if not isinstance(data.get('wait', True), bool):
                    raise ValueError('wait must be boolean')
                self.selected_cameras(data.get('cameras',[robot+'_front',robot+'_side']),allow_empty=True)
                parameters = {k:v for k,v in data.items() if k not in ('wait','robot','cameras')}
                prepared = self.world.validate_action(robot, op, parameters, self.config)
                with self.store.transaction():
                    action = self.store.start_action(job['id'], actor, op, data, float(self.world.time),prepared.get('timing'))
                try:
                    self.world.start_action(robot, job['id'], prepared)
                    inject = getattr(self.world, 'inject_fault', None)
                    injected = inject(robot, job['id'], op) if callable(inject) and not self.fault_injected() else None
                    if injected:
                        self.store.event('ENGINEERING_FAULT_INJECTED', 'Meta', injected)
                        self._fault_injected = True
                except Exception as error:
                    self.store.uncertain_action(job['id'],'Executor acknowledgement failed: '+str(error),isolate=True)
                    self.respond(job,{'execution_status':'uncertain',
                        'error':'Execution acknowledgement unavailable; inspect the affected robot and original call. Other robots may continue.'})
                else:
                    self.store.event('ACTION_ACCEPTED_BY_EXECUTOR',actor,action)
                    if not data.get('wait', True):
                        self.respond(job, {'execution_status':'running', 'execution':action,
                                           'note':'Submitted, not completed; query job or wait_events with this call_id'})
            elif op == 'recover_action':
                if set(data)!={'call_id'}:raise ValueError('recover_action requires only the original call_id')
                original=self.store.call(data['call_id'],actor)
                action=self.store.actions(actor).get(data['call_id'])
                if (not action or action['status'] not in ('running','uncertain') or not action.get('local_recovery')
                        or action['status']=='running' and action.get('phase')!='stopping'):
                    raise ValueError('No locally recoverable action for this role')
                robot=self.store.action_robot(actor,action['arm'])
                if self.store.get('lifecycle')!='running' or self.store.get('physics_state')!='running' or self.store.get('dispatch_paused',False):
                    raise ValueError('Recovery requires the original live and running world')
                recovered=self.world.recover_action(robot,data['call_id'])
                if recovered is None:
                    diagnostics=self.stopping_diagnostics(action)
                    self.respond(job,{'recovered':False,'execution':action,'stop_diagnostics':diagnostics,
                        'note':'Stop is still settling; inspect the measurements and retry recovery later. Do not replay the action.'})
                else:
                    action=self.store.reconcile_stopped_action(data['call_id'],actor,recovered,float(self.world.time))
                    if data['call_id'] in self.requests:
                        self.requests[data['call_id']]['result']=self.store.call(data['call_id'],actor)['result']
                    self.respond(job,{'recovered':True,'execution':action,
                        'note':'The original action failed and is now confirmed stopped. Decide any new action independently.'})
            elif op == 'job':
                call = self.store.call(data['call_id'], None if manager else actor)
                if call['op']=='action_batch':
                    from .action_batch import get_batch_status
                    value=get_batch_status(self.store,data['call_id'])
                    self.respond(job,{**value,'call_status':call['status'],
                                      'execution':{'call_id':data['call_id'],'status':value['execution_status']},'original_result':call['result']})
                    job['done'].set();return
                action = self.store.actions().get(data['call_id'])
                diagnostics=None
                if action and action.get('phase')=='stopping':
                    # Only a live stop has a controller to ask. A terminal action keeps its phase
                    # (an integrity abort, a recovery or a new segment ended it); the world that
                    # owned the stop may be gone, so its recorded diagnostics are the answer.
                    diagnostics=action.get('stop_diagnostics')
                    if action.get('status')=='running':
                        try:diagnostics=self.stopping_diagnostics(action)
                        except ValueError:pass
                self.respond(job, {'execution': action or {'call_id':data['call_id'],'status':call['status']},
                                   'original_result':call['result'], **({'stop_diagnostics':diagnostics} if diagnostics is not None else {}),
                                   **({'execution_diagnostics':self.isolated_diagnostics(action)} if action and action.get('isolated') else {})})
            elif op == 'state':
                self.respond(job, self.snapshot())
            elif op == 'finish':
                authorized = kind=={'hierarchical':'team-controller','peer':'worker','centralized':'controller','adaptive':'controller'}[self.config['topology']]
                if not authorized:
                    raise ValueError('Task-team finish proposal required')
                if any(v['status'] in ('pending','running','uncertain') for v in self.store.actions().values()):
                    raise ValueError('Execution still running or uncertain')
                if self.config['topology']=='adaptive' and Delegations(self.store).active():
                    raise ValueError('Resolve and return outstanding delegations before team finish')
                if self.store.get('lifecycle') != 'running':
                    raise ValueError('Run is not running')
                if self.check_integrity():
                    raise ValueError('Engineering inputs changed; run invalidated')
                end_trial=getattr(self.world,'end_trial',None)
                if callable(end_trial):end_trial()
                self.store.put('lifecycle', 'ended')
                self.store.put('physics_state', 'finished')
                self.store.event('TEAM_FINISH_PROPOSED', actor, {'note':data.get('note',''), 'sim_time_s':float(self.world.time)})
                self.stop_video()
                write_json(self.directory/'private/outputs/evaluation.json', self.world.evaluate())
                self.save_evaluation_evidence('evaluation-window.json')
                self.respond(job, {'ended': True, 'note':'Private evaluation is not policy feedback'})
                self.export_records()
            elif op == 'shutdown':
                from .action_batch import cancel_collecting
                # One transaction: a refused shutdown leaves every forming sync group intact.
                with self.store.transaction():
                    cancel_collecting(self.store,'shutdown_before_group_start',float(self.world.time))
                    if any(v['status'] in ('pending','running') for v in self.store.actions().values()):
                        raise ValueError('Resolve execution before shutdown')
                self.respond(job, {'shutdown': True})
                self.shutdown = True
            else:
                raise ValueError('Unknown tool operation')
        except (ValueError, KeyError, TypeError, sqlite3.InterfaceError, sqlite3.ProgrammingError) as error:
            # A policy value the store cannot bind is a malformed request, never a reason to end
            # the owner loop (and with it the shared world). Other database errors still propagate.
            # A failed IK request also reports what the solver found (robot_control.IKNoSolution).
            detail = getattr(error, 'detail', None)
            self.respond(job, {'error': str(error), **({'ik_detail': detail} if detail is not None else {})})
        if job['result'] is not None:
            job['done'].set()

    def step_physics(self):
        """Advance the original world only while its route is admitted."""
        if self.egress_pause.sync() or self.store.get('egress_review_hold',False):return False
        self.world.step()
        return True

    def pump(self):
        if self.egress_pause.sync() or self.store.get('egress_review_hold',False):
            # Keep engineering observation/shutdown reachable. Every policy
            # request retains its original call ID and waits, without reissue.
            held=[]
            while True:
                try:job=self.queue.get_nowait()
                except queue.Empty:break
                if self.store.agent(job['actor'])['kind']=='manager' and job['op'] in ('state','observe','shutdown'):
                    self.handle(job)
                else:held.append(job)
            for job in held:self.queue.put(job)
            return
        if self.policy_budget is not None:
            self.policy_budget.tick(self)
        while True:
            try:
                job = self.queue.get_nowait()
            except queue.Empty:
                break
            self.handle(job)
        for result in self.world.poll_actions(self.config['action_timeout_sim_s']):
            job = self.requests[result['call_id']]
            with self.store.transaction():
                if result['status'] in ('stopping','uncertain'):
                    action=self.store.actions().get(job['id'],{})
                    arm=getattr(self.world,'arms',{}).get(action.get('arm'))
                    locally_stopping=(result.get('reason') in ('Stop is still settling','Stop did not settle; engineering review required')
                                      and arm is not None and arm.job==job['id'] and arm.stopping and arm.uncertainty_reported)
                    if locally_stopping:
                        diagnostics=result.get('stop_diagnostics') or self.stopping_diagnostics(action)
                        action=self.store.isolate_stopping_action(job['id'],'Stop is still settling',diagnostics)
                        self.respond(job,{'execution_status':'running','execution':action,
                                          'stop_diagnostics':diagnostics,
                                          'note':'Action is still stopping; inspect and recover it. Other robots may continue.'})
                    else:
                        action=self.store.uncertain_action(job['id'],result['reason'],isolate=True)
                        self.respond(job,{'execution_status':'uncertain','execution':action,
                                          'execution_feedback':{k:v for k,v in result.items() if k not in ('call_id','status','reason')},
                                          'error':result['reason']})
                    job['done'].set()
                    continue
                action = self.store.finish_action(job['id'], result['status'], float(self.world.time), result.get('reason'))
                if not job['data'].get('wait', True):
                    self.store.signal(job['actor'], {'event':'action_finished', 'call_id':job['id'],
                                                     'status':action['status']})
                cameras = job['data'].get('cameras',[action['arm']+'_front',action['arm']+'_side'])
                self.respond(job, {'execution': action, 'execution_feedback':{k:v for k,v in result.items() if k not in ('call_id','status','reason')}, 'observation': self.capture(cameras)})
            job['done'].set()
        self.poll_local_recovery()
        self.poll_delegations()
        from .action_batch import poll
        poll(self)
        self.poll_waiters()
        self.poll_motion_check()
        if self.policy_budget is not None:
            self.policy_budget.tick(self)
            if self.ended:
                self.shutdown = True

    def poll_local_recovery(self):
        """Recheck a live stop and periodically remind the owner about unknowns."""
        if self.ended or self.store.get('physics_state') != 'running':
            return
        now = float(self.world.time)
        actions = self.store.unresolved_actions()
        active = {ident for ident, action in actions.items()
                  if action.get('local_recovery') or action.get('status') == 'uncertain' and action.get('isolated')}
        self.recovery_checks = {ident: due for ident, due in self.recovery_checks.items() if ident in active}
        for ident in active:
            action = actions[ident]
            interval = 5.0 if action.get('local_recovery') else 30.0
            due = self.recovery_checks.setdefault(ident, now + interval)
            if now < due:
                continue
            self.recovery_checks[ident] = now + interval
            call = self.store.call(ident)
            actor = call['actor']
            if action.get('local_recovery'):
                try:
                    recovered = self.world.recover_action(action['arm'], ident)
                except (ValueError, KeyError) as error:
                    self.store.uncertain_action(ident, 'Stop recheck lost the original controller state: '+str(error), isolate=True)
                    self.recovery_checks.pop(ident, None)
                    continue
                if recovered is None:
                    notice = {'event':'arm_recovery_check', 'robot':action['arm'], 'call_id':ident,
                              'stop_diagnostics':self.stopping_diagnostics(action),
                              'note':'Still stopping; inspect the evidence and continue independent work.'}
                else:
                    action = self.store.reconcile_stopped_action(ident, actor, recovered, now)
                    if ident in self.requests:
                        self.requests[ident]['result'] = self.store.call(ident, actor)['result']
                    notice = {'event':'arm_recovery_confirmed', 'robot':action['arm'], 'call_id':ident,
                              'execution':action, 'note':'The original action failed and its stop is confirmed.'}
                    self.recovery_checks.pop(ident, None)
            else:
                notice = {'event':'arm_execution_check', 'robot':action['arm'], 'call_id':ident,
                          'execution_diagnostics':self.isolated_diagnostics(action),
                          'note':'Outcome remains unknown; inspect the original action. Never replay it.'}
            self.store.signal(actor, notice)
            if self.config.get('topology') == 'adaptive' and actor != 'Controller':
                self.store.signal('Controller', notice)

    def poll_motion_check(self):
        if self.motion_check is None:
            return
        job, samples = self.motion_check
        try:
            if self.ended or self.store.get('physics_state')=='paused_by_user':
                result = {'assessment':'unknown','reason':'Run paused/ended during screening','advisory_only':True}
            else:
                result = next(samples)
            if result is None:
                return
            if 'source_state_id' in result:
                result['live_state_changed'] = result['source_state_id'] != self.world.motion_state_id()
            result['returned_sim_time_s'] = float(self.world.time)
            self.respond(job, {'motion_check':result})
        except Exception as error:
            self.respond(job, {'motion_check':{'assessment':'unknown','reason':str(error),'advisory_only':True}})
        self.motion_check = None
        job['done'].set()

    def poll_delegations(self):
        if self.config['topology']!='adaptive':return
        d=Delegations(self.store)
        for job in list(self.requests.values()):
            if job['op']!='delegate' or job['result'] is not None:continue
            b=d.batch(job['id'])
            if b['status']=='finished':
                self.respond(job,{'delegation':b,'robot_owners':d.owners()});job['done'].set()
                continue
            paused=self.store.get('dispatch_paused',False) or self.store.get('physics_state')=='paused_by_user'
            if time.time()>=b.get('setup_deadline',float('inf')) and b['status']!='needs_review':
                b=d.uncertain(b['id'],'Native setup deadline expired; inspect existing forks, never refork automatically',b['claimed_by'])
            elif (paused or self.ended) and b['status']!='needs_review':
                b=d.uncertain(b['id'],'Run paused/ended during native setup',b['claimed_by'])
            if b['status']=='needs_review':
                self.respond(job,{'error':b.get('reason','Run paused/ended during native delegation'),
                                  'delegation':b})
                job['done'].set()
            elif b['status']=='active' and all(c['start_status'] in ('sent','observed') for c in b['children']):
                self.respond(job,{'delegation':b,'robot_owners':d.owners()})
                job['done'].set()

    def poll_waiters(self):
        """GUI tick checks durable predicates; no sleeping or long DB transaction.

        Both mailbox writes and registration run on this owner thread. A message
        before registration or between ticks remains pending until receipted.
        """
        for call_id, waiter in list(self.waiters.items()):
            job = waiter['job']
            pending = self.store.pending(job['actor'])
            own_actions = self.store.actions_for_calls(job['actor'], waiter['call_ids'])
            executions = {i:own_actions[i] for i in waiter['call_ids']}
            terminal = any(v['status'] in ('completed','failed','uncertain') for v in executions.values())
            ended = self.ended
            paused = self.store.get('lifecycle')=='paused' or self.store.get('dispatch_paused',False) or self.store.get('physics_state')=='paused_by_user'
            timed_out = time.monotonic() >= waiter['deadline']
            if pending['messages'] or pending['signals'] or terminal or ended or paused or timed_out:
                self.respond(job, {'wait_status':'ended' if ended else 'paused' if paused else 'events' if pending['messages'] or pending['signals'] or terminal else 'timeout',
                                   'executions':executions, 'run_ended':ended})
                job['done'].set()
                del self.waiters[call_id]

    def stop_video(self):
        if self.video:
            self.finished_video = self.video.close()
            self.store.put('video', self.finished_video)
            self.video = None

    def save_evaluation_evidence(self, filename, folder=None):
        method=getattr(self.world,'evaluation_evidence',None)
        if callable(method):
            evidence=method()
            if evidence is not None:write_json((folder or self.directory/'private/outputs')/filename,evidence)

    def check_integrity(self):
        changed = verify_inputs(self.directory)
        self.last_integrity_check = time.monotonic()
        if changed:
            self.store.put('integrity_valid', False)
            self.store.put('dispatch_paused', True)
            if self.store.get('lifecycle') == 'running':
                self.store.put('lifecycle', 'recovery_required')
                self.store.put('physics_state', 'recovery_required')
                for result in self.world.abort_actions('Engineering inputs changed'):
                    job = self.requests[result['call_id']]
                    action = self.store.finish_action(job['id'], 'failed', float(self.world.time), result['reason'])
                    self.respond(job, {'execution': action, 'error':'Engineering integrity failure'})
                    job['done'].set()
                self.stop_video()
            self.store.event('INTEGRITY_ABORT', 'Meta', {'changed': changed})
        return changed

    def periodic(self):
        holds = getattr(self.world, 'held_grasps', None)
        if callable(holds) and self.store.get('lifecycle') == 'running':
            self.store.put('arm_holds', holds())
        if self.store.get('lifecycle') == 'running' and time.monotonic() >= self.last_integrity_check + self.config['integrity_check_interval_s']:
            if self.check_integrity():
                self.export_records()

    def export_records(self):
        """Derived records, exported on finish/close or an explicit request."""
        write_json(self.directory/'private/outputs/runtime.json', self.snapshot())
        self.store.export_events(self.directory/'private/outputs/events.jsonl')
