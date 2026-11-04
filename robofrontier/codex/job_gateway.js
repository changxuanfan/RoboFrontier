// One native refresh owner. Access-only attachments never rotate credentials.
// No interactive login, custom OAuth or RPC replay.
const fs=require('node:fs'),net=require('node:net'),readline=require('node:readline');
const {CodexRpc}=require('./codex_rpc');
const fileTools=require('./tool_broker');
const fields={
  'thread/start':['model','modelProvider','cwd','approvalPolicy','ephemeral','dynamicTools','baseInstructions','threadSource','config','permissions'],
  'thread/fork':['threadId','cwd','model','modelProvider','excludeTurns','ephemeral','permissions'],
  'thread/resume':['threadId','cwd','model','modelProvider','approvalPolicy','baseInstructions','config','permissions'],
  'thread/read':['threadId','includeTurns'],
  'thread/turns/list':['threadId','limit','sortDirection','itemsView','cursor'],
  'thread/name/set':['threadId','name'],
  'turn/start':['threadId','model','effort','input','turnTrigger'],
  'turn/interrupt':['threadId','turnId'], 'thread/compact/start':['threadId'], 'thread/archive':['threadId'],
  'config/read':[], 'account/read':['refreshToken'], 'account/rateLimits/read':[]
};
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
class JobGateway {
  constructor(tasks,{rpcFactory=options=>new CodexRpc(options.args,options.callbacks),persist=()=>{},recoveryDirectory}={}) {
    if(!tasks.length||new Set(tasks.map(t=>t.id)).size!==tasks.length)throw new Error('Distinct gateway tasks required');
    this.tasks=new Map(tasks.map(t=>[t.id,{...t,threads:new Set(),archived:new Set(),inflight:new Set(),state:'new'}]));
    this.owners=new Map();this.turns=new Map();this.serverRequests=new Map();this.nextRequest=0;
    this.persist=persist;this.rpcFactory=rpcFactory;this.clients=new Set();
    this.recoveryDirectory=recoveryDirectory;
    // A stopped engine can hand its exact persisted thread inventory to a new
    // engine. Only the trusted manifest supplies this list; task RPC cannot.
    for(const task of this.tasks.values())for(const id of task.resumeThreads||[]){
      if(typeof id!=='string'||!/^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/.test(id)||this.owners.has(id))
        throw new Error('Invalid cold-continuation ownership');
      this.owners.set(id,task);task.threads.add(id);
    }
  }
  async start(args,launch,{stderr='ignore',borrowedCredentials}={}) {
    const auth=borrowedCredentials?require('./borrowed_auth').borrowedAuth(borrowedCredentials):null;
    if(auth)args=[...args,'-c','cli_auth_credentials_store="ephemeral"'];
    this.native=this.rpcFactory({args,callbacks:{stderr,
      onEvent:m=>this.event(m),onRequest:(m,p)=>m==='account/chatgptAuthTokens/refresh'&&auth?
        auth.refresh(p):this.tool(m,p),onExit:()=>{this.unexpectedExit=true;this.fail();}}});
    await this.native.initialize();
    if(auth){
      const result=await this.native.call('account/login/start',{type:'chatgptAuthTokens',...auth.initial()});
      if(result.type!=='chatgptAuthTokens')throw new Error('Borrowed subscription admission failed');
    }
    await fileTools.admit(this.native,launch);
    // A local cached account/read success is not authenticated reachability.
    // This native endpoint performs the provider request and native renewal.
    const limits=await this.native.call('account/rateLimits/read',{},90000);
    if(!limits||typeof limits.rateLimits!=='object'||limits.rateLimits===null)throw new Error('Native authenticated account admission failed');
  }
  bind(client,taskId){
    const task=this.tasks.get(taskId);
    if(this.failed||!task||task.state!=='new'||client.task)throw new Error('Task channel is unknown or already consumed');
    task.state='bound';task.client=client;client.task=task;this.clients.add(client);
    return {backend:'slurm-managed-v1'};
  }
  capabilities(){return {backend:'slurm-managed-v1',singleTaskRecovery:this.recoveryDirectory?1:0};}
  async recoveryStatus(taskId){
    const task=this.tasks.get(taskId);
    if(!this.recoveryDirectory||this.failed||!task)throw new Error('Recovery is not available');
    const pending=[...this.serverRequests.values()].filter(p=>p.task===task).length;
    return {taskId,state:task.state,pendingTools:pending,inflight:task.inflight.size,
      recoveryUsed:!!task.recoveryUsed,threads:[...task.threads].sort()};
  }
  async recover(client,{taskId,nonce}={}){
    const task=this.tasks.get(taskId);
    if(!this.recoveryDirectory||this.failed||client.task||!task||task.state!=='closed'||task.recoveryUsed||
       task.inflight.size||[...this.serverRequests.values()].some(p=>p.task===task))throw new Error('Task is not recoverable');
    if(!/^[A-Za-z0-9_-]{1,128}$/.test(taskId)||typeof nonce!=='string')throw new Error('Invalid recovery grant');
    const folder=this.recoveryDirectory,dir=fs.lstatSync(folder);
    if(!dir.isDirectory()||dir.isSymbolicLink()||dir.uid!==process.getuid()||(dir.mode&0o077))throw new Error('Unsafe recovery authority');
    const file=require('node:path').join(folder,taskId+'.json');
    const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
    let grant;
    try{
      const info=fs.fstatSync(fd);
      if(!info.isFile()||info.uid!==process.getuid()||(info.mode&0o077)||info.nlink!==1||info.size>65536)throw new Error('Unsafe recovery grant');
      grant=JSON.parse(fs.readFileSync(fd,'utf8'));
    }finally{fs.closeSync(fd);}
    if(grant.schema!=='robofrontier.task-recovery-grant.v1'||grant.taskId!==task.id||grant.run!==task.run||
       grant.nonce!==nonce||!Number.isFinite(grant.expiresAt)||grant.expiresAt<=Date.now()/1000||
       grant.expiresAt>Date.now()/1000+300||JSON.stringify(grant.threads)!==JSON.stringify([...task.threads].sort()))
      throw new Error('Recovery grant does not match the closed task');
    // Consume before any native request. An uncertain admission is never repeated.
    if(fs.existsSync(file+'.consumed'))throw new Error('Recovery authority was already consumed');
    fs.renameSync(file,file+'.consumed');task.recoveryUsed=true;task.state='recovering';
    try{
      for(const id of task.threads){
        const result=await this.native.call('thread/read',{threadId:id});
        if(result.thread.status.type==='active')throw new Error('An original role is still active');
      }
      task.client=client;client.task=task;task.state='bound';this.clients.add(client);
      return {backend:'slurm-managed-v1',recovered:true};
    }catch{task.state='closed';throw new Error('Recovery admission uncertain; manual review required');}
  }
  own(task,id){if(!id||this.owners.get(id)!==task)throw new Error('Thread is not owned by this task');}
  async request(client,method,p={}) {
    const task=client.task;
    if(!task||task.client!==client||task.state!=='bound'||this.failed)throw new Error('Task channel is not admitted');
    if(method==='gateway/release'){await this.release(task);return {released:true};}
    if(task.kind==='preflight'&&p.sandbox==='read-only') {p={...p};delete p.sandbox;}
    if(!fields[method]||!p||typeof p!=='object'||Array.isArray(p)||Object.keys(p).some(k=>!fields[method].includes(k)))
      throw new Error('Unsupported task RPC surface');
    if(method==='account/read'&&p.refreshToken)throw new Error('Only the shared native manager may request renewal');
    if(method==='account/read')return {account:{type:'chatgpt'}};
    if(method==='account/rateLimits/read')throw new Error('Account admission belongs to the job supervisor');
    if(method==='config/read')return this.native.call(method,{});
    if(['thread/compact/start','thread/archive'].includes(method)&&task.kind!=='preflight')throw new Error('Preflight-only RPC');
    if(method!=='thread/start')this.own(task,p.threadId);
    if(p.permissions!==undefined&&p.permissions!==task.permissions)throw new Error('Cross-task permission selection denied');
    if(p.cwd!==undefined&&p.cwd!==task.cwd)throw new Error('Cross-task working directory denied');
    if(p.model!==undefined&&p.model!==task.model)throw new Error('Frozen model mismatch');
    if(p.modelProvider!==undefined&&p.modelProvider!==task.provider)throw new Error('Frozen provider mismatch');
    if(p.effort!==undefined&&p.effort!==task.effort)throw new Error('Frozen effort mismatch');
    if(p.approvalPolicy!==undefined&&p.approvalPolicy!=='never')throw new Error('Interactive approval is disabled');
    if(p.config&&JSON.stringify(p.config)!==JSON.stringify({web_search:'disabled','features.multi_agent':false}))
      throw new Error('Task configuration overrides denied');
    if(method==='thread/start'){
      const names=(p.dynamicTools||[]).map(t=>t.name);
      const expected=new Set([task.kind==='preflight'?'protocol_check':'robot','policy_exec','policy_image']);
      if(names.length!==3||new Set(names).size!==3||names.some(t=>!expected.has(t)))throw new Error('Unexpected task tool inventory');
    }
    if(method==='turn/start'&&(!Array.isArray(p.input)||p.input.some(item=>
      item.type==='text'?typeof item.text!=='string':
        !(task.kind==='preflight'&&item.type==='localImage'&&item.path===task.image))))
      throw new Error('Unbound native input denied');
    if(['thread/start','thread/fork','thread/resume'].includes(method))
      p={...p,cwd:task.cwd,model:task.model,modelProvider:task.provider,permissions:task.permissions};
    if(method==='thread/resume')p={...p,excludeTurns:true};
    // Native transport generates globally unique request IDs. Caller IDs never
    // reach it, so 36 clients may all issue local request 1 concurrently.
    const pending=(async()=>{
      const result=await this.native.call(method,p,180000);
      if(['thread/start','thread/fork'].includes(method)){
        const id=result.thread?.id;
        if(!id||this.owners.has(id))throw new Error('Native thread ownership collision');
        if(method==='thread/fork'&&result.thread.forkedFromId!==p.threadId)throw new Error('Native fork lineage mismatch');
        this.owners.set(id,task);task.threads.add(id);this.persist(this.ownership());
      }
      if(method==='turn/start')this.turns.set(p.threadId,result.turn);
      if(method==='thread/archive')task.archived.add(p.threadId);
      return result;
    })();
    task.inflight.add(pending);
    try{return await pending;}finally{task.inflight.delete(pending);}
  }
  ownership(){return [...this.tasks.values()].map(t=>({task_id:t.id,run:t.run,threads:[...t.threads]}));}
  event(m){
    const p=m.params||{},id=p.threadId??p.thread?.id,task=this.owners.get(id);
    // No global account/config/log broadcasts, or unknown-thread payloads.
    if(!task||task.state!=='bound')return;
    if(m.method==='turn/started'||m.method==='turn/completed')this.turns.set(id,p.turn);
    task.client.send(m);
  }
  tool(method,p){
    const task=this.owners.get(p?.threadId);
    const allowed=new Set([task?.kind==='preflight'?'protocol_check':'robot','policy_exec','policy_image']);
    if(method!=='item/tool/call'||!task||task.state!=='bound'||!allowed.has(p.tool))
      return Promise.reject(new Error('Unbound or forbidden native tool request'));
    const id='tool-'+ ++this.nextRequest;
    return new Promise((resolve,reject)=>{
      // A dispatched tool is owned by this task until its result or channel
      // closure. Robot waits/actions have their own runtime deadlines; the
      // startup RPC timeout cannot discard ownership of a legitimate long wait.
      this.serverRequests.set(id,{task,resolve,reject});task.client.send({id,method,params:p});
    });
  }
  respond(client,m){
    const pending=this.serverRequests.get(m.id);
    if(!pending||pending.task!==client.task||pending.task.client!==client)throw new Error('Tool response ownership mismatch');
    this.serverRequests.delete(m.id);
    if(m.error)pending.reject(new Error('Bound task tool failed'));else pending.resolve(m.result);
  }
  async release(task){
    task.state='closing';
    // A timed-out caller may still have a native acknowledgement in flight.
    // Settle it before unloading threads; never send the mutation again.
    let timer;
    try{
      await Promise.race([Promise.allSettled([...task.inflight]),new Promise((resolve,reject)=>{
        timer=setTimeout(()=>reject(new Error('Native mutation still uncertain at task closure')),30000);
      })]);
    }finally{clearTimeout(timer);}
    for(const [id,p]of this.serverRequests)if(p.task===task){p.reject(new Error('Task channel closed'));this.serverRequests.delete(id);}
    for(const id of task.threads){
      if(task.archived.has(id))continue;
      let state=await this.native.call('thread/read',{threadId:id});
      if(state.thread.status.type==='notLoaded')continue;
      const turn=this.turns.get(id);
      if(state.thread.status.type==='active'){
        if(!turn?.id)throw new Error('Cannot settle unknown active turn');
        await this.native.call('turn/interrupt',{threadId:id,turnId:turn.id});
        const deadline=Date.now()+30000;
        do{await delay(100);state=await this.native.call('thread/read',{threadId:id});}
        while(state.thread.status.type==='active'&&Date.now()<deadline);
        if(state.thread.status.type==='active')throw new Error('Task turn did not settle before transcript handback');
      }
      await this.native.call('thread/unsubscribe',{threadId:id});
    }
    task.state='closed';
  }
  disconnected(client){
    this.clients.delete(client);
    const task=client.task;
    if(task?.client===client&&task.state==='bound')this.release(task).catch(()=>this.fail());
  }
  fail(){
    if(this.failed)return;this.failed=true;
    for(const p of this.serverRequests.values())p.reject(new Error('Shared engine stopped'));
    this.serverRequests.clear();for(const client of this.clients)client.destroy();
    if(this.server?.listening)this.server.close();
  }
  async listen(endpoint){
    this.server=net.createServer(socket=>{
      const client={send:m=>{if(!socket.destroyed)socket.write(JSON.stringify(m)+'\n');},destroy:()=>socket.destroy()};
      let bytes=0;
      socket.on('data',data=>{bytes+=data.length;if(bytes>32*1024*1024)socket.destroy();});
      // The byte cap bounds one connection's lifetime input between messages.
      readline.createInterface({input:socket}).on('line',async line=>{
        bytes=0;let m;
        try{
          m=JSON.parse(line);
          if(!m.method){this.respond(client,m);return;}
          if(client.task&&['gateway/capabilities','gateway/recovery/status'].includes(m.method))throw new Error('Supervisor-only control query');
          const result=m.method==='gateway/capabilities'?this.capabilities():
            m.method==='gateway/recovery/status'?await this.recoveryStatus(m.params?.taskId):
            m.method==='gateway/recover'?await this.recover(client,m.params):
            m.method==='gateway/bind'?this.bind(client,m.params?.taskId):await this.request(client,m.method,m.params);
          client.send({id:m.id,result});
        }catch{
          // Raw provider exceptions may contain auth context; never forward them.
          if(m?.method)client.send({id:m.id,error:{code:-32603,message:'Shared gateway request rejected or acknowledgement unknown; do not repeat mutations'}});
          else socket.destroy();
        }
      });
      socket.on('error',()=>{});socket.on('close',()=>this.disconnected(client));
    });
    await new Promise((resolve,reject)=>{this.server.once('error',reject);this.server.listen(endpoint,resolve);});
    fs.chmodSync(endpoint,0o600);
  }
  async close(){
    this.fail();
    if(this.server)await new Promise(resolve=>this.server.close(resolve));
    if(this.native)await this.native.close();
  }
}
async function main(file){
  const manifest=JSON.parse(fs.readFileSync(file));
  let gateway;
  try{
    const log=fs.openSync(manifest.log,'a',0o600);
    gateway=new JobGateway(manifest.tasks,{recoveryDirectory:manifest.recovery_directory,persist:rows=>{
      const temporary=manifest.ownership+'.tmp';fs.writeFileSync(temporary,JSON.stringify(rows),{mode:0o600});fs.renameSync(temporary,manifest.ownership);
    }});
    try{await gateway.start(manifest.args,manifest.launch,{stderr:log,borrowedCredentials:manifest.borrowed_credentials});}finally{fs.closeSync(log);}
    gateway.persist(gateway.ownership());
    await gateway.listen(manifest.endpoint);
    gateway.server.on('close',()=>{if(gateway.unexpectedExit)process.exitCode=1;});
    fs.writeFileSync(manifest.ready,JSON.stringify({backend:'slurm-managed-v1',tasks:manifest.tasks.length}),{mode:0o600});
    let closing=false;
    const stop=async()=>{if(closing)return;closing=true;await gateway.close();};
    process.on('SIGTERM',()=>stop().catch(()=>{process.exitCode=1;}));
    process.on('SIGINT',()=>stop().catch(()=>{process.exitCode=1;}));
  }catch{
    if(gateway)await gateway.close().catch(()=>{});
    process.stderr.write('Shared Codex admission failed; inspect private supervisor state.\n');process.exitCode=1;
  }
}
if(require.main===module)main(process.argv[2]);
module.exports={JobGateway};
