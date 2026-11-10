const test=require('node:test'),assert=require('node:assert/strict');
const {CodexRpc,STARTUP_ACK_MS,capacityFailure,networkFailure,requireNoMcpServers}=require('../robofrontier/engines/codex/codex_rpc');
const {PolicyHost,robotTool}=require('../robofrontier/engines/codex/codex_policy_host');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const failedNetworkState={
  thread:{status:{type:'systemError'}},
  latestTurn:{id:'failed',status:'failed',error:{codexErrorInfo:{responseStreamDisconnected:{httpStatusCode:null}}}}
};
test('native subscription tool admission rejects inherited MCP before a model turn',async()=>{
  for(const config of [{mcp_servers:{personal:{command:'unused'}}},
                       {mcp_servers:{personal:{enabled:true}}}]) {
    const calls=[];
    await assert.rejects(requireNoMcpServers({call:async(method)=>{
      calls.push(method);return {config};}}),/MCP servers/);
    assert.deepEqual(calls,['config/read']);
  }
});
test('native subscription tool admission accepts empty or disabled MCP configuration',async()=>{
  for(const config of [{},{mcp_servers:{personal:{enabled:false}}}])
    await requireNoMcpServers({call:async()=>({config})});
  await assert.rejects(requireNoMcpServers({call:async()=>({})}),/could not be verified/);
});
test('capacity retry distinguishes quota/auth/permanent errors',()=>{
  for(const message of ['model_capacity_limit','429 Too Many Requests','server_overloaded'])assert.equal(capacityFailure({message}),true);
  for(const message of ['insufficient_quota 429','invalid_api_key','Bad Request 400',"429 You've hit your usage limit"])assert.equal(capacityFailure({message}),false);
});
test('network recovery accepts only structured transport failures without HTTP status',()=>{
  assert.equal(networkFailure({codexErrorInfo:{responseStreamDisconnected:{httpStatusCode:null}}}),true);
  assert.equal(networkFailure({message:'network error'}),false);
  for(const httpStatusCode of [401,403,429,500])assert.equal(networkFailure({codexErrorInfo:{httpConnectionFailed:{httpStatusCode}}}),false);
});
test('network continuation is one fresh notice after a durable claim, never an old turn replay',async t=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'rf-network-host-'));t.after(()=>fs.rmSync(folder,{recursive:true,force:true}));
  fs.mkdirSync(path.join(folder,'private/inputs/bootstrap'),{recursive:true});
  fs.writeFileSync(path.join(folder,'private/inputs/bootstrap/network-resume.md'),'Frozen network continuation notice');
  const sent=[],operations=[];
  const host={run:folder,stopped:false,actors:new Map([['thread','Controller']]),retries:new Set(),
    networkFailures:new Map([['thread:failed',Date.now()/1000]]),
    admin:async(op)=>{operations.push(op);return op==='snapshot'?{lifecycle:'running',paused:false,egress_recovery:{claim:'one'}}:{allowed:true};},
    observe:async()=>structuredClone(failedNetworkState),
    send:async(id,notice)=>{sent.push({id,notice});},event:()=>{}};
  await PolicyHost.prototype.retryCapacity.call(host);await PolicyHost.prototype.retryCapacity.call(host);
  assert.deepEqual(sent,[{id:'thread',notice:'Frozen network continuation notice'}]);
  assert.equal(operations.filter(v=>v==='network-recovery').length,1);
});
test('unknown network continuation acknowledgement holds review and is never repeated',async t=>{
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'rf-network-host-'));t.after(()=>fs.rmSync(folder,{recursive:true,force:true}));
  fs.mkdirSync(path.join(folder,'private/inputs/bootstrap'),{recursive:true});fs.writeFileSync(path.join(folder,'private/inputs/bootstrap/network-resume.md'),'notice');
  let sends=0,reviews=0;
  const host={run:folder,stopped:false,actors:new Map([['thread','Controller']]),retries:new Set(),networkFailures:new Map([['thread:failed',Date.now()/1000]]),
    admin:async(op)=>{if(op==='network-recovery-uncertain')reviews++;return op==='snapshot'?{lifecycle:'running',paused:false,egress_recovery:{claim:'one'}}:{allowed:true};},
    observe:async()=>structuredClone(failedNetworkState),
    send:async()=>{sends++;throw new Error('unknown acknowledgement');},event:()=>{}};
  await PolicyHost.prototype.retryCapacity.call(host);await PolicyHost.prototype.retryCapacity.call(host);
  assert.equal(sends,1);assert.equal(reviews,1);
});
test('an active turn cannot be steered by the scheduler',async()=>{
  let called=false;
  await assert.rejects(PolicyHost.prototype.send.call({observe:async()=>({thread:{status:{type:'active'}}}),rpc:{call:()=>{called=true;}}},'t','wake'),/active/);
  assert.equal(called,false);
});
test('cold resume reopens only working roles and never returned delegates',async()=>{
  const resumed=[],sent=[];
  const host={run:'/tmp/stopped-run',launch:{model:'stub',provider:'openai'},actors:new Map(),
    hostPath:()=>'/tmp/stopped-run/workspace',event:()=>{},
    rpc:{call:async(method,p)=>{resumed.push(p.threadId);}},
    send:async(id,message)=>sent.push([id,message]),
    admin:async(op)=>op==='snapshot'?{agents:{
      Controller:{kind:'controller',thread_id:'parent'},
      Active:{kind:'delegate',thread_id:'active',delegation_state:'active'},
      Returned:{kind:'delegate',thread_id:'returned',delegation_state:'finished'}
    }}:{resumed:true,segment:2,messages:{Controller:'continue',Active:'finish scope'}}};
  await PolicyHost.prototype.resumeSessions.call(host);
  assert.deepEqual(resumed,['parent','active']);
  assert.deepEqual(sent,[['parent','continue'],['active','finish scope']]);
  assert.equal(host.actors.has('returned'),false);
});
test('robot transport cannot select another role connection',()=>{
  assert.equal(robotTool.name,'robot');
  assert.equal(robotTool.inputSchema.properties.connection,undefined);
});
test('direct bootstrap names shared rules and does not promise all drop counters',()=>{
  const prompt=PolicyHost.prototype.bootstrap.call({run:'/tmp/test-run',wallLimit:300},'Controller');
  assert.match(prompt,/policy-rules\.md/);
  assert.match(prompt,/Supported process events follow their task-specific detection rules/);
  assert.match(prompt,/do not automatically veto completion/);
  assert.match(prompt,/without waiting for another START/);
});
test('frozen legacy roles retain the readiness barrier and read their work after wake',()=>{
  const prompt=PolicyHost.prototype.bootstrap.call({run:'/tmp/test-run',wallLimit:36000},'A','ready_barrier_v1');
  assert.match(prompt,/call robot ready/);
  assert.match(prompt,/call robot work/);
  assert.doesNotMatch(prompt,/The experiment has STARTED and the task clock is running/);
});
test('capacity recovery resumes a started task without a READY barrier',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'capacity-retry-'));
  try {
    const fakePython=path.join(dir,'python');
    fs.writeFileSync(fakePython,'#!/bin/sh\nprintf "false\\n"\n',{mode:0o755});
    const prompts=[];
    const host={stopped:false,began:Date.now(),run:dir,cwd:dir,python:fakePython,
      actors:new Map([['thread','Controller']]),failures:new Map([['thread:turn',Date.now()-11000]]),retries:new Set(),
      admin:async()=>({paused:false,lifecycle:'running'}),
      observe:async()=>({thread:{status:{type:'systemError'}},latestTurn:{id:'turn',status:'failed',error:{message:'429 Too Many Requests'}}}),
      send:async(id,prompt)=>prompts.push(prompt),event:()=>{}};
    await PolicyHost.prototype.retryCapacity.call(host);
    assert.equal(prompts.length,1);
    assert.match(prompts[0],/The experiment has started/);
    assert.match(prompts[0],/continue without waiting for another START/);
    assert.doesNotMatch(prompts[0],/legacy startup barrier has not opened/);
    await PolicyHost.prototype.retryCapacity.call(host);
    assert.equal(prompts.length,1);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
test('initialize waits for the startup acknowledgement limit unless told otherwise',async()=>{
  let waited;const fake={call:async(method,params,timeoutMs)=>{waited=timeoutMs;return {};},write(){}};
  await CodexRpc.prototype.initialize.call(fake);assert.equal(waited,STARTUP_ACK_MS);assert.equal(STARTUP_ACK_MS,180000);
  await CodexRpc.prototype.initialize.call(fake,5000);assert.equal(waited,5000);
});
test('capacity recovery stops after three consecutive retries and pauses for review',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'capacity-limit-'));
  try {
    const fakePython=path.join(dir,'python');
    fs.writeFileSync(fakePython,'#!/bin/sh\nprintf "false\\n"\n',{mode:0o755});
    const prompts=[],admin=[];let turn=0;
    const host={stopped:false,run:dir,cwd:dir,python:fakePython,actors:new Map([['thread','Controller']]),
      failures:new Map(),retries:new Set(),capacityAttempts:new Map([['thread',3]]),
      admin:async(op,data)=>{admin.push([op,data]);return {paused:false,lifecycle:'running'};},
      observe:async()=>({thread:{status:{type:'systemError'}},latestTurn:{id:'turn-'+turn,status:'failed',error:{message:'429 Too Many Requests'}}}),
      send:async(id,prompt)=>prompts.push(prompt),event:()=>{}};
    await PolicyHost.prototype.retryCapacity.call(host);
    assert.equal(prompts.length,0);
    assert.equal(admin.at(-1)[0],'pause');
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
