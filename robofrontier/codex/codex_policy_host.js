// One independent CLI host per task. Reuses the existing deterministic Meta.
const fs = require('node:fs');
const path = require('node:path');
const {execFile,execFileSync,exec:execShell,spawn} = require('node:child_process');
const {promisify} = require('node:util');
const execFileAsync = promisify(execFile), execAsync = promisify(execShell);
const {CodexRpc,STARTUP_ACK_MS,capacityFailure,networkFailure,requireNoMcpServers} = require('./codex_rpc');
const {GatewayRpc} = require('./gateway_rpc');
const fileTools = require('./tool_broker');
const {runMetaDispatcher} = require('../../scripts/meta_dispatcher');
const sleep = ms => new Promise(resolve=>setTimeout(resolve,ms));
const read = file=>JSON.parse(fs.readFileSync(file,'utf8'));
// Frozen at preparation by robofrontier/policy_bootstrap.py; absent from runs prepared earlier.
const frozenText=(run,name)=>{const file=path.join(run,'private/inputs/bootstrap',name);
  return fs.existsSync(file)?fs.readFileSync(file,'utf8'):null;};
// Capacity recovery, the same policy as robofrontier/claude/recovery.py: at most 3
// consecutive resumes of a session, 10/20/40 s apart plus a 0-5 s jitter fixed by the
// session ID (so many runs do not retry together); a completed turn resets the count.
const MAX_CAPACITY_RETRIES=3;
// As in robofrontier/claude/supervisor.py (finish_turn_grace_s): after a normal finish the
// world is already frozen, so existing turns may write their final reply before closing.
const FINISH_TURN_GRACE_MS=30000;
const capacityDelayMs=(attempt,id)=>10000*2**attempt+[...String(id)].reduce((n,c)=>n+c.charCodeAt(0),0)%5000;
const LEGACY_SYSTEM_PROMPT='You are a RoboFrontier policy agent running in Codex. Follow the frozen public task, current role, tool protocol and evidence boundaries. Use your assigned robot tools. Preserve original call IDs across uncertain results. Do not manage the model host, modify the benchmark, or read private evaluation data.';
function toolFailure(callId, stdout) {
  let detail;
  try { if (typeof stdout==='string' && stdout.length<=16384) detail=JSON.parse(stdout); } catch {}
  const conflict=detail?.tool_error_schema===1 && detail.call_id===callId &&
    detail.error_code==='CALL_ID_CONFLICT' && detail.request_status==='rejected' &&
    detail.original_call_status==='unknown';
  // Rebuild an allowlisted response; never pass through raw stderr, command
  // lines, server strings or another request's details.
  return {tool_error_schema:1,call_id:callId,
    error_code:conflict?'CALL_ID_CONFLICT':'TRANSPORT_UNCERTAIN',
    error:conflict?'This call ID is already associated with a different request.':
      'The tool result could not be confirmed; execution must not be inferred.',
    request_status:conflict?'rejected':'unknown',original_call_status:'unknown',
    note:conflict?
      'The conflicting request was rejected; the original request status is unknown. Inspect pending. To query your action, send a new job request with the original action ID in data.call_id and omit the outer call_id. Reconcile before any new physical action; never replay uncertain motion.':
      'The original request status is unknown. Inspect pending. To query your action, send a new job request with the original action ID in data.call_id and omit the outer call_id. Retry an uncertain request only with its original outer call_id and identical operation and data; never replay motion under a new ID.'};
}
// The delegate a new native fork belongs to: the next unbound child of the one batch
// being created (the dispatcher forks a batch's children in order and binds each before
// the next). A batch left for review keeps unbound children and must never be matched.
function pendingForkActor(snapshot) {
  const creating=(snapshot.delegations??[]).filter(d=>d.status==='creating');
  if (creating.length>1) throw new Error('More than one delegation batch is being created');
  const child=creating.flatMap(d=>d.children).find(c=>!c.thread_id);
  if (!child) throw new Error('No pending runtime delegation for fork');
  return child.actor;
}
function observationMime(data) {
  if (data.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) return 'image/png';
  if (data.length>=3 && data[0]===255 && data[1]===216 && data[2]===255) return 'image/jpeg';
  throw new Error('Observation is not PNG or JPEG');
}
const robotTool = {type:'function',name:'robot',description:
  'Call your assigned RoboFrontier role API. For a new request omit outer call_id; its generated request ID is returned as call_id. For job, data.call_id is the original action ID, not the new request ID. Selected views return RGB images.',
  inputSchema:{type:'object',properties:{op:{type:'string'},data:{type:'object'},
    call_id:{type:'string',description:'Optional request ID. Omit for a new request. To retry an uncertain request, use its original ID and identical op and data.'},views:{type:'array',items:{type:'string'}}},required:['op','data']}};

class PolicyHost {
  constructor(run, cwd, python) {
    this.run=path.resolve(run); this.cwd=cwd; this.python=python;
    this.launch=read(path.join(this.run,'private/inputs/codex.json'));
    this.wallLimit=read(path.join(this.run,'private/inputs/task.json')).run_protocol.total_wall_limit_s;
    this.actors=new Map(); this.turns=new Map(); this.failures=new Map(); this.retries=new Set();
    this.stopped=false;
    this.turnStarted=new Map();
    this.networkFailures=new Map();
  }
  // Host file locations come from robofrontier/run_layout.py, the one source for both engines.
  hostPath(key) {
    if (!this.layout) this.layout=JSON.parse(execFileSync(this.python,['-m','robofrontier.run_layout',this.run,'--engine','codex'],
      {cwd:this.cwd??path.resolve(__dirname,'../..'),encoding:'utf8'})).paths;
    if (!(key in this.layout)) throw new Error('Unknown run layout key: '+key);
    return path.join(this.run,this.layout[key]);
  }
  event(value) {
    const file=this.hostPath('host_log');fs.mkdirSync(path.dirname(file),{recursive:true});
    fs.appendFileSync(file,JSON.stringify({at:Date.now()/1000,...value})+'\n');
  }
  async admin(op,data={}) {
    const {stdout}=await execFileAsync(this.python,['-m','robofrontier.runtime_cli',
      '--run-dir',this.run,op,'--data',JSON.stringify(data)],{cwd:this.cwd,maxBuffer:8*1024*1024});
    return JSON.parse(stdout);
  }
  async toolRequest(method,p) {
    if (method!=='item/tool/call') throw new Error('Unsupported host tool');
    const actor=this.actors.get(p.threadId); if (!actor) throw new Error('Unbound policy role');
    const a=typeof p.arguments==='string'?JSON.parse(p.arguments):p.arguments;
    if (fileTools.enabled(this.launch) && ['policy_exec','policy_image'].includes(p.tool)) {
      const started=Date.now();
      const result=await fileTools.call(this.run,this.python,p.tool,a);
      this.event({event:'file_tool_completed',actor,thread_id:p.threadId,tool:p.tool,
        success:result.success,duration_s:(Date.now()-started)/1000});
      return result;
    }
    if (p.tool!=='robot') throw new Error('Unsupported host tool');
    const toolStarted=Date.now();
    this.event({event:'robot_tool_started',actor,thread_id:p.threadId,op:a.op,call_id:p.callId});
    if (['move','gripper','action_batch'].includes(a.op) && a.data?.cameras===undefined)
      a.data={...(a.data||{}),cameras:a.views||[]};
    // Native call IDs are scoped by actor and stable across transport retries.
    const callId=a.call_id || (actor+'-'+p.callId).replace(/[^A-Za-z0-9_-]/g,'_').slice(0,128);
    const args=['-m','robofrontier.pipeline_client','--quiet','--connection',
      path.join(this.run,'private/state/connections',actor+'.json'),'--call-id',callId,a.op,
      '--data',JSON.stringify(a.data||{})];
    try {
      const {stdout}=await execFileAsync(this.python,args,{cwd:this.cwd,maxBuffer:8*1024*1024});
      const result=JSON.parse(stdout),contentItems=[{type:'inputText',text:JSON.stringify(result)}];
      const observation=result.observation || result.original_result?.observation;
      for (const view of a.views||[]) {
        const file=observation?.images?.[view];
        if (!file) {contentItems.push({type:'inputText',text:'Selected view unavailable: '+view});continue;}
        try {
          const real=fs.realpathSync(file),publicRoot=fs.realpathSync(path.join(this.run,'public'))+path.sep;
          if (!real.startsWith(publicRoot)) throw new Error('Observation outside this run public directory');
          const bytes=fs.readFileSync(real),mime=observationMime(bytes);
          contentItems.push({type:'inputImage',imageUrl:'data:'+mime+';base64,'+bytes.toString('base64')});
        } catch (error) {
          // The physical action already ran: retain the original result and call_id.
          contentItems.push({type:'inputText',text:'Selected view could not be loaded: '+view});
        }
      }
      this.event({event:'robot_tool_completed',actor,thread_id:p.threadId,op:a.op,call_id:p.callId,duration_s:(Date.now()-toolStarted)/1000});
      return {success:true,contentItems};
    } catch(error) {
      const failure=toolFailure(callId,error.stdout);
      this.event({event:'robot_tool_failed',actor,thread_id:p.threadId,op:a.op,call_id:p.callId,
        durable_call_id:callId,error_code:failure.error_code,request_status:failure.request_status,
        duration_s:(Date.now()-toolStarted)/1000});
      return {success:false,contentItems:[{type:'inputText',text:JSON.stringify(failure)}]};
    }
  }
  async startServer() {
    const log=fs.openSync(this.hostPath('server_log'),'a');
    this.rpcLost=false;
    const callbacks={stderr:log,onRequest:(m,p)=>this.toolRequest(m,p),
      onExit:(code,signal)=>{this.rpcLost=true;this.event({event:'model_host_exited',exit_code:code,signal});},onEvent:m=>{
      const p=m.params||{};
      const turnId=p.turnId || p.turn?.id, turnKey=p.threadId+':'+turnId;
      if (m.method==='turn/started') this.turnStarted.set(turnKey,Date.now());
      const began=this.turnStarted.get(turnKey);
      if (m.method==='turn/completed') {
        this.turns.set(p.threadId,p.turn);
        if(p.turn.status==='failed'&&networkFailure(p.turn.error))this.networkFailures.set(turnKey,Date.now()/1000);
        if (p.turn.status==='completed') this.capacityAttempts?.delete(p.threadId);
        if (p.turn.status==='failed' && capacityFailure(p.turn.error)) {
          const key=p.threadId+':'+p.turn.id;
          if (!this.failures.has(key)) this.failures.set(key,Date.now());
          this.event({event:'capacity_wait',thread_id:p.threadId,turn_id:p.turn.id,retry_after_s:10});
        }
      }
      if (['turn/started','turn/completed','thread/status/changed','thread/tokenUsage/updated','error'].includes(m.method))
        this.event({event:m.method,thread_id:p.threadId,actor:this.actors.get(p.threadId),turn_id:turnId,status:p.turn?.status,
          duration_s:m.method==='turn/completed' && began!==undefined?(Date.now()-began)/1000:undefined,
          token_usage:p.tokenUsage,error:p.error});
      if (m.method==='turn/completed') this.turnStarted.delete(turnKey);
    }};
    this.jobScoped=this.launch.profile?.runner_backend==='slurm-managed-v1';
    if(this.jobScoped){
      if(!process.env.ROBOFRONTIER_CODEX_GATEWAY||!process.env.ROBOFRONTIER_CODEX_TASK)
        throw new Error('Missing admitted job gateway channel');
      this.rpc=new GatewayRpc(process.env.ROBOFRONTIER_CODEX_GATEWAY,process.env.ROBOFRONTIER_CODEX_TASK,callbacks);
    }else this.rpc=new CodexRpc(this.launch.args,callbacks);
    fs.closeSync(log); await this.rpc.initialize();
    if(fileTools.subscription(this.launch)) await requireNoMcpServers(this.rpc);
    await fileTools.admit(this.rpc,this.launch);
  }
  async observe(threadId) {
    const result=await this.rpc.call('thread/read',{threadId});
    const latest=await this.rpc.call('thread/turns/list',{threadId,limit:1,sortDirection:'desc',itemsView:'notLoaded'});
    const turn=latest.data?.[0] || this.turns.get(threadId);
    let type=result.thread.status.type;
    if (type==='idle' && turn?.status==='failed') type='systemError';
    return {thread:{...result.thread,status:{type}},latestTurn:turn};
  }
  async send(threadId,prompt) {
    const state=await this.observe(threadId);
    if (state.thread.status.type==='active') throw new Error('Refusing to steer an active policy turn');
    const result=await this.rpc.call('turn/start',{threadId,model:this.launch.model,effort:this.launch.effort,
      input:[{type:'text',text:prompt}],turnTrigger:'robofrontier'});
    this.turns.set(threadId,result.turn); return {threadId};
  }
  stopRequested() { return this.stopped || fs.existsSync(this.hostPath('stop')); }
  // The world process is gone: stop dispatching so the run is sealed and can continue
  // in its next segment (docs/running/run-segments.md) instead of failing every robot call.
  ownerExited() {
    const gone=Boolean(this.owner && (this.owner.exitCode!==null || this.owner.signalCode!==null));
    if (gone && !this.ownerExitLogged) {this.ownerExitLogged=true;
      this.event({event:'owner_exited',exit_code:this.owner.exitCode,signal:this.owner.signalCode});}
    return gone;
  }
  async retryCapacity() {
    if (this.stopped) return;
    const snapshot=await this.admin('snapshot');
    if (snapshot.paused || ['ended','interrupted','recovery_required'].includes(snapshot.lifecycle)) return;
    for (const [id,actor] of this.actors) {
      const state=await this.observe(id),t=state.latestTurn;
      const role=snapshot.agents?.[actor];
      if(role?.kind==='delegate'&&role.delegation_state!=='active')continue;
      if(state.thread.status.type==='systemError'&&t?.status==='failed'&&snapshot.egress_recovery
          && !capacityFailure(t.error) && (!networkFailure(t.error)||this.networkFailures?.get(id+':'+t.id)===undefined||!frozenText(this.run,'network-resume.md'))){
        await this.admin('network-recovery-uncertain',{actor,thread_id:id});return;
      }
      if(state.thread.status.type==='systemError'&&t?.status==='failed'&&networkFailure(t.error)){
        const key=id+':'+t.id,observed=this.networkFailures?.get(key);
        const notice=frozenText(this.run,'network-resume.md');
        if(!snapshot.egress_recovery||observed===undefined||!notice||this.retries.has(key))continue;
        const claim=await this.admin('network-recovery',{actor,thread_id:id,failed_turn_id:t.id,error_observed_at:observed});
        if(claim.review_required){await this.admin('network-recovery-uncertain',{actor,thread_id:id});return;}
        if(!claim.allowed)continue;
        this.retries.add(key);
        try{
          await this.send(id,notice);
          this.event({event:'network_continuation',actor,thread_id:id,failed_turn_id:t.id});
        }catch{
          await this.admin('network-recovery-uncertain',{actor,thread_id:id});
          this.event({event:'network_continuation_uncertain',actor,thread_id:id});
          return;
        }
        continue;
      }
      if (state.thread.status.type!=='systemError' || t?.status!=='failed' || !capacityFailure(t.error)) continue;
      const key=id+':'+t.id;
      if (this.retries.has(key)) continue;
      this.capacityAttempts??=new Map();
      const attempt=this.capacityAttempts.get(id)||0;
      if (attempt>=MAX_CAPACITY_RETRIES) {
        // Exhausted: pause the run for review rather than keep resuming.
        await this.admin('pause',{reason:'Model capacity recovery attempts exhausted',actor,thread_id:id});
        this.event({event:'capacity_recovery_exhausted',actor,thread_id:id,failed_turn_id:t.id});
        return;
      }
      if (!this.failures.has(key)) {
        this.failures.set(key,Date.now());
        this.event({event:'capacity_wait',actor,thread_id:id,failed_turn_id:t.id,attempt:attempt+1,delay_s:capacityDelayMs(attempt,id)/1000});
      }
      if (Date.now()-this.failures.get(key)<capacityDelayMs(attempt,id)) continue;
      // Isolated robots remain reserved, but their owners can resume to inspect them.
      const code="from robofrontier.runtime_store import RuntimeStore;from robofrontier.scheduling import blocks_model_recovery;import sys,json;s=RuntimeStore(sys.argv[1]);a=sys.argv[2];print(json.dumps(any(blocks_model_recovery(v) for v in s.actions(a).values()) or any(True for r in s.db.execute(\"SELECT 1 FROM calls WHERE actor=? AND status='accepted' AND op IN ('move','gripper','action_batch','delegate')\",(a,)))));s.close()";
      const {stdout}=await execFileAsync(this.python,['-c',code,path.join(this.run,'private/state/runtime.sqlite'),actor],{cwd:this.cwd});
      if (JSON.parse(stdout)) continue;
      this.retries.add(key); // An unknown turn/start acknowledgement is never repeated.
      this.capacityAttempts.set(id,attempt+1);
      const phase=snapshot.lifecycle==='running' ? 'The experiment has started: obtain any needed capability information and continue without waiting for another START.' : 'The legacy startup barrier has not opened; continue the existing startup instructions.';
      await this.send(id,'The previous model turn failed because of a capacity or rate limit. Continue this task and its saved work. First inspect pending/job using original action IDs and read your inbox. Preserve submitted actions, the current world and the original deadline. '+phase);
      this.event({event:'capacity_retry',thread_id:id,failed_turn_id:t.id,attempt:attempt+1});
    }
  }
  bootstrap(actor, startupProtocol='direct_controller_v2') {
    const frozen=frozenText(this.run,actor+'.md');
    if (frozen!==null) return frozen;
    return `Run a fresh, independent RoboFrontier experiment. Run directory: ${this.run}. Current role: ${actor}.
Read this run's public/inputs/common.md, policy-rules.md, task.json, roles/${actor}.md, skill/SKILL.md, skill/references/tools.md and skill/references/communication.md; read skill/references/adaptive.md only in adaptive mode. Use this task's public inputs, your own work notes and authorized images.
CLI transport: use the bound robot tool. Its op/data match the frozen Skill's role API. Omit outer call_id for a new request; the response returns its ID. To query an existing action, issue a new job request with the original action ID in data.call_id. For an uncertain result, retry only the same outer ID with identical op/data. Select returned cameras with views. The tool binds your own connection and returns complete JSON and actual RGB image content; a path alone is not an observation. After permitted local image analysis or other non-robot work, refresh your inbox with robot inbox.
${startupProtocol==='ready_barrier_v1' ? 'Legacy startup: read the public task and role, call robot ready, save waiting state and end this startup turn. On the post-START continuation, call robot work to restore your work and continue within your role.' : 'The experiment has STARTED and the task clock is running. Read the task, view its initial images or use robot observe, then choose your own plan and actions within your assigned role. You may call robot ready for capabilities and limits; continue after its response without waiting for another START. In adaptive mode only, choose bounded forks through robot delegate when useful.'}
Scoring version terminal_outcome_v2: completion follows the task's published conditions. Supported process events follow their task-specific detection rules and are reported separately; they do not automatically veto completion. Observe, recover and continue after problems. Relay requires an actual released payload supported within GOAL tolerances; an airborne handover record is not a separate final-completion gate.
Follow policy-rules.md: continue observing, acting and recovering while unfinished. The host enforces the time limit. On pause, stop, run_ended or budget exhaustion, stop new work immediately. Propose finish when the task is complete or permitted evidence establishes that recovery is no longer possible.
Use your assigned native session and bound robot tools. Read public task evidence within your role; your connection is for authentication only. Keep experience local to this run. Oracle solutions, other trials, private scene/XML, private evaluation and engineering source are outside policy evidence. Preserve the benchmark, physics and harness.
`;
  }
  // After a normal finish, wait up to the grace for replies already in progress. No
  // dispatch or physics happens here. Returns whether every turn settled.
  async drainFinishedTurns(graceMs=FINISH_TURN_GRACE_MS,pollMs=500) {
    try {
      if ((await this.admin('snapshot')).lifecycle!=='ended') return null;
      const deadline=Date.now()+graceMs;let drained=false;
      for (;;) {
        const states=await Promise.all([...this.actors.keys()].map(id=>
          this.observe(id).then(s=>s.thread.status.type,()=>'unknown')));
        if (!states.includes('active')) {drained=true;break;}
        if (Date.now()>=deadline) break;
        await sleep(pollMs);
      }
      this.event({event:'finish_turns_drained',drained});
      return drained;
    } catch(error) {this.event({event:'finish_drain_error',message:error.message});return false;}
  }
  async startInitialRoles(roles, startupProtocol) {
    const direct=['direct_controller_v2','direct_team_v3'].includes(startupProtocol);
    if (!direct && startupProtocol!=='ready_barrier_v1') throw new Error('Unknown startup protocol');
    const policy=Object.entries(roles).filter(([,info])=>info.kind!=='manager');
    if (!policy.length || (startupProtocol==='direct_controller_v2' &&
        (policy.length!==1 || policy[0][0]!=='Controller'))) throw new Error('Unexpected initial policy roles');
    const bound=[];
    for (const [actor] of policy) {
      if (this.stopRequested()) throw new Error('Stop requested during initial session setup');
      // A run with a frozen access table runs under its permission profile from launch;
      // a thread `sandbox` would replace that profile, so only earlier runs send one.
      const system=frozenText(this.run,'system.md');
      const result=await this.rpc.call('thread/start',{model:this.launch.model,modelProvider:this.launch.provider,
        cwd:this.hostPath('policy_cwd'),approvalPolicy:'never',ephemeral:false,
        dynamicTools:[robotTool,...(fileTools.enabled(this.launch)?fileTools.tools:[])],
        ...(system===null?{sandbox:'workspace-write'}:{}),baseInstructions:system??LEGACY_SYSTEM_PROMPT,
        threadSource:'robofrontier-benchmark',config:{web_search:'disabled','features.multi_agent':false}},STARTUP_ACK_MS);
      const id=result.thread.id; this.actors.set(id,actor);
      this.event({event:'role_created',actor,thread_id:id,provider:this.launch.provider,model:this.launch.model});
      await this.rpc.call('thread/name/set',{threadId:id,name:`${this.launch.model} · ${path.basename(this.run)} · ${actor}`},STARTUP_ACK_MS);
      const resultBind=await this.bindInitialRole(actor,id);
      if (!resultBind.bound) throw new Error('Initial role binding was not confirmed');
      bound.push({actor,id});
      if (!direct) await this.send(id,this.bootstrap(actor,startupProtocol));
    }
    if (direct) {
      if (this.stopRequested()) throw new Error('Stop requested before START');
      const started=await this.admin('request-start');
      if (!started.started) throw new Error('Direct START was not confirmed');
      this.event({event:'direct_start',actors:bound.map(role=>role.actor)});
      for (const {actor,id} of bound) {
        if (this.stopRequested()) throw new Error('Stop requested before initial model input');
        await this.send(id,this.bootstrap(actor,startupProtocol));
      }
    }
  }
  // Only the app-server stopped; the world never did. Start a new one, reopen every
  // role's own thread and send each working role the frozen restart notice.
  async restartModelHost() {
    await this.startServer();
    const notice=fs.readFileSync(path.join(this.run,'private/inputs/bootstrap/model-restart.md'),'utf8');
    const snapshot=await this.admin('snapshot');
    for (const [actor,agent] of Object.entries(snapshot.agents)) {
      if (agent.kind==='manager' || !agent.thread_id) continue;
      await this.rpc.call('thread/resume',{threadId:agent.thread_id,cwd:this.hostPath('policy_cwd'),model:this.launch.model,
        modelProvider:this.launch.provider,approvalPolicy:'never',baseInstructions:frozenText(this.run,'system.md')??undefined,
        config:{web_search:'disabled','features.multi_agent':false}},STARTUP_ACK_MS);
      this.actors.set(agent.thread_id,actor);
      this.event({event:'role_resumed',actor,thread_id:agent.thread_id});
      if (agent.kind!=='delegate' || agent.delegation_state==='active') await this.send(agent.thread_id,notice);
    }
  }
  async bindInitialRole(actor, id) {
    const connection=path.join(this.run,'private/state/connections/Meta.json');
    const {stdout}=await execFileAsync(this.python,['-m','robofrontier.pipeline_client','--quiet',
      '--connection',connection,'--call-id','bind-'+actor,'bind','--data',JSON.stringify({actor,thread_id:id})],{cwd:this.cwd});
    return JSON.parse(stdout);
  }
  // A run continued after an unexpected exit (docs/running/run-segments.md): reopen every role's
  // own thread, let the world resume, then send each working role its frozen resume message.
  async resumeSessions() {
    const snapshot=await this.admin('snapshot');
    for (const [actor,agent] of Object.entries(snapshot.agents)) {
      if (agent.kind==='manager' || !agent.thread_id) continue;
      if (agent.kind==='delegate' && agent.delegation_state==='finished') continue;
      await this.rpc.call('thread/resume',{threadId:agent.thread_id,cwd:this.hostPath('policy_cwd'),model:this.launch.model,
        modelProvider:this.launch.provider,approvalPolicy:'never',baseInstructions:frozenText(this.run,'system.md')??undefined,
        config:{web_search:'disabled','features.multi_agent':false}},STARTUP_ACK_MS);
      this.actors.set(agent.thread_id,actor);
      this.event({event:'role_resumed',actor,thread_id:agent.thread_id});
    }
    const resumed=await this.admin('request-resume');
    if (!resumed.resumed) throw new Error('World did not confirm the resumed segment');
    this.event({event:'segment_resumed',segment:resumed.segment});
    for (const [id,actor] of this.actors) if (resumed.messages[actor]) await this.send(id,resumed.messages[actor]);
  }
  async runTask() {
    const manifest=read(path.join(this.run,'private/inputs/manifest.json'));
    if (manifest.model_requested!==this.launch.model || manifest.effort_requested!==this.launch.effort)
      throw new Error('Frozen model/harness mismatch');
    let failure;
    try {
      await this.startServer();
      const ownerLog=fs.openSync(this.hostPath('owner_log'),'a');
      this.owner=spawn(this.python,['-m','robofrontier.pipeline','--run-dir',this.run,'--hidden'],
        {cwd:this.cwd,stdio:['ignore',ownerLog,ownerLog]}); fs.closeSync(ownerLog);
      this.owner.on('error',error=>{this.ownerError=error;});
      const startupTimeout=read(path.join(this.run,'private/inputs/harness.json')).startup_timeout_s ?? 120;
      if (!Number.isFinite(startupTimeout) || startupTimeout<=0) throw new Error('Invalid owner startup timeout');
      const ownerDeadline=performance.now()+startupTimeout*1000;
      for (;;) {
        if (this.ownerError || this.owner.exitCode!==null || performance.now()>=ownerDeadline) throw new Error('Physical owner failed to publish its connection');
        if (read(path.join(this.run,'private/state/connections/Meta.json')).url) break;
        await sleep(1000);
      }
      const roles=read(path.join(this.run,'public/inputs/roles.json')).roles;
      const startupProtocol=read(path.join(this.run,'private/inputs/harness.json')).startup_protocol || 'ready_barrier_v1';
      // A run continued after an unexpected exit reopens its roles' own threads instead.
      if ((await this.admin('snapshot')).lifecycle==='resuming') await this.resumeSessions();
      else await this.startInitialRoles(roles,startupProtocol);
      const wrap=value=>({content:[{type:'text',text:JSON.stringify(value)}]});
      const createNativeFork=async (p,isSnapshot=false)=>{
        const forkStarted=Date.now();
        // The dispatcher passes what is left of the shared setup deadline; without it,
        // the ordinary request limit applies.
        if (p.timeoutMs!==undefined && !(p.timeoutMs>0)) throw new Error('Delegate setup deadline passed before native fork');
        const result=await this.rpc.call('thread/fork',{threadId:p.threadId,cwd:this.hostPath('policy_cwd'),model:this.launch.model,
          modelProvider:this.launch.provider,excludeTurns:true,ephemeral:false},p.timeoutMs);
        this.event({event:isSnapshot?'snapshot_created':'fork_created',thread_id:result.thread.id,parent:p.threadId,duration_s:(Date.now()-forkStarted)/1000});
        if (!isSnapshot) {
          this.actors.set(result.thread.id,pendingForkActor(await this.admin('snapshot')));
        }
        return wrap({threadId:result.thread.id,sourceThreadId:result.thread.forkedFromId,status:'created'});
      };
      const tools={
        exec_command:async a=>{const r=await execAsync(a.cmd,{cwd:this.cwd,maxBuffer:16*1024*1024});return {output:r.stdout,exit_code:0};},
        mcp__codex_app__wait_threads:async({targets})=>{await this.retryCapacity();return wrap({polls:await Promise.all(targets.map(t=>this.observe(t.threadId)))});},
        mcp__codex_app__send_message_to_thread:async p=>wrap(await this.send(p.threadId,p.prompt)),
        mcp__codex_app__set_thread_title:async p=>{await this.rpc.call('thread/name/set',{threadId:p.threadId,name:p.title});return wrap({threadId:p.threadId});},
        mcp__codex_app__fork_thread:async p=>createNativeFork(p)};
      // A run prepared with a restart notice survives its app-server stopping, up to the
      // run's allowance (runtime model-restart, shared with the Claude route); the world
      // keeps running throughout and the dispatcher keeps one owner.
      const restartable=frozenText(this.run,'model-restart.md')!==null;
      const owner='meta-'+Date.now()+'-'+Math.random().toString(16).slice(2);
      for (;;) {
        let outcome;
        try {
          outcome=await runMetaDispatcher({runDir:this.run,python:this.python,cwd:this.cwd,tools,owner,
            startWhenReady:true,observationSource:'codex.app-server',onEvent:e=>this.event(e),
            createSnapshot:async p=>JSON.parse((await createNativeFork(p,true)).content[0].text),
            stopRequested:()=>this.stopRequested()||this.rpcLost||this.ownerExited()});
        } catch (error) { if (!this.rpcLost) throw error; }
        if (!this.rpcLost || this.stopRequested()) return outcome;
        if(this.jobScoped)throw new Error('Shared Codex engine stopped; automatic redispatch is disabled');
        const claim=restartable?await this.admin('model-restart',{actor:'Meta',engine:'codex'}):{allowed:false};
        if (!claim.allowed) throw new Error('Codex app-server stopped; model restarts unavailable or exhausted');
        this.event({event:'model_host_restart',attempt:claim.restart});
        await this.restartModelHost();
      }
    } catch(error) {
      // Kept for the report: a failing seal below would otherwise replace this error.
      failure=error;this.event({event:'host_error',message:error.message});throw error;
    } finally {
      const stopRequested=this.stopped||fs.existsSync(this.hostPath('stop'));
      this.stopped=true;
      if (!failure && !stopRequested && this.rpc) await this.drainFinishedTurns();
      // Seal the existing owner; never recreate its physical world.
      let sealError;
      try {const result=await this.admin('seal',{timeout_s:fileTools.enabled(this.launch)?120:30});
        if (!result.sealed) throw new Error('Seal did not confirm closure');
      } catch(error) {sealError=error;this.event({event:'seal_error',message:error.message});}
      for (const id of this.actors.keys()) {
        try {const s=await this.observe(id);if(s.thread.status.type==='active')
          await this.rpc.call('turn/interrupt',{threadId:id,turnId:s.latestTurn.id});} catch {}
      }
      if (this.rpc) await this.rpc.close();
      // Codex has stopped writing: copy this run's threads into the run, verified. The home
      // keeps the originals so a continued segment can resume them (robofrontier.session_archive).
      try {
        // Runs prepared before run-v6 have no engine_transcripts and keep theirs in the home.
        if ('engine_transcripts' in this.layout) {
          const kept=JSON.parse(execFileSync(this.python,['-m','robofrontier.session_archive','keep',this.run],
            {cwd:this.cwd??path.resolve(__dirname,'../..'),encoding:'utf8',env:process.env}));
          this.event({event:'transcripts_kept',threads:kept.threads,complete:kept.complete});
        }
      } catch(error) {this.event({event:'transcripts_error',message:error.message});}
      if (sealError) throw new Error('Run seal incomplete; manual review required: '+sealError.message
        +(failure?' (after host error: '+failure.message+')':''));
    }
  }
}
if (require.main===module) {
  const [run,cwd,python]=process.argv.slice(2);
  const host=new PolicyHost(run,cwd,python);
  process.on('SIGTERM',()=>{host.stopped=true;});process.on('SIGINT',()=>{host.stopped=true;});
  host.runTask().then(r=>process.stdout.write(JSON.stringify(r)+'\n')).catch(e=>{process.stderr.write(e.stack+'\n');process.exitCode=1;});
}
module.exports={PolicyHost,robotTool,observationMime,pendingForkActor};
