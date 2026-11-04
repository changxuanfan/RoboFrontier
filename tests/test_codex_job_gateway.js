const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {JobGateway}=require('../robofrontier/codex/job_gateway');
const {GatewayRpc}=require('../robofrontier/codex/gateway_rpc');

function fixture(count=2){
  const tasks=Array.from({length:count},(_,i)=>({id:'task-'+i,run:'/runs/'+i,cwd:'/runs/'+i+'/workspace',
    permissions:'rf_'+i,model:'gpt-6-luna',provider:'managed',effort:'high',kind:'policy'}));
  const calls=[];let next=0;
  const gateway=new JobGateway(tasks),native={
    async call(method,p){
      calls.push({method,p});await new Promise(r=>setTimeout(r,(next%3)+1));
      if(method==='thread/start'||method==='thread/fork')return {thread:{id:'thread-'+ ++next,forkedFromId:p.threadId}};
      if(method==='turn/start')return {turn:{id:'turn-'+ ++next,status:'inProgress'}};
      if(method==='thread/read')return {thread:{id:p.threadId,status:{type:'idle'}}};
      return {ack:method};
    },async close(){calls.push({method:'close'});}
  };
  gateway.native=native;
  const clients=tasks.map(t=>({events:[],send(m){this.events.push(m);},destroy(){this.destroyed=true;}}));
  clients.forEach((c,i)=>gateway.bind(c,tasks[i].id));
  const start=client=>gateway.request(client,'thread/start',{model:'gpt-6-luna',modelProvider:'managed',
    dynamicTools:['robot','policy_exec','policy_image'].map(name=>({name}))});
  return {gateway,native,calls,tasks,clients,start};
}

test('36 simultaneous task channels retain distinct profiles, parents, forks and handback',async()=>{
  const f=fixture(36);
  const parents=await Promise.all(f.clients.map(f.start));
  assert.equal(new Set(parents.map(p=>p.thread.id)).size,36);
  const children=await Promise.all(f.clients.map((c,i)=>f.gateway.request(c,'thread/fork',{threadId:parents[i].thread.id})));
  for(let i=0;i<36;i++){
    assert.equal(children[i].thread.forkedFromId,parents[i].thread.id);
    f.gateway.event({method:'turn/completed',params:{threadId:children[i].thread.id,turn:{id:'finished-'+i,status:'completed'}}});
    assert.equal(f.clients[i].events.length,1);
    assert.equal(f.clients[i].events[0].params.threadId,children[i].thread.id);
    await f.gateway.release(f.clients[i].task);
  }
  const starts=f.calls.filter(c=>c.method==='thread/start');
  assert.equal(new Set(starts.map(c=>c.p.permissions)).size,36);
  assert.equal(f.calls.filter(c=>c.method==='thread/unsubscribe').length,72);
  assert.equal(f.calls.some(c=>c.method==='close'),false);
});

test('cross-task read, fork, interrupt, profile and input references are rejected before native dispatch',async()=>{
  const f=fixture(),parent=await f.start(f.clients[0]);
  const before=f.calls.length;
  for(const method of ['thread/read','thread/fork','thread/resume','turn/interrupt','turn/start'])
    await assert.rejects(f.gateway.request(f.clients[1],method,{threadId:parent.thread.id}));
  await assert.rejects(f.gateway.request(f.clients[0],'thread/fork',{threadId:parent.thread.id,permissions:'rf_1'}));
  await assert.rejects(f.gateway.request(f.clients[0],'thread/start',{sandbox:'danger-full-access'}));
  await assert.rejects(f.gateway.request(f.clients[0],'thread/start',{config:{'features.shell_tool':true}}));
  await assert.rejects(f.gateway.request(f.clients[0],'account/login/start',{}));
  await assert.rejects(f.gateway.request(f.clients[0],'account/read',{refreshToken:true}));
  await assert.rejects(f.gateway.request(f.clients[0],'turn/start',{threadId:parent.thread.id,input:[{type:'localImage',path:'/private/auth.json'}]}));
  assert.equal(f.calls.length,before);
});

test('native tools are routed only to the owner and another task cannot answer them',async()=>{
  const f=fixture(),parent=await f.start(f.clients[0]);
  const pending=f.gateway.tool('item/tool/call',{threadId:parent.thread.id,tool:'robot',callId:'physical-action-once'});
  const message=f.clients[0].events.at(-1);
  assert.throws(()=>f.gateway.respond(f.clients[1],{id:message.id,result:{success:true}}),/ownership/);
  f.gateway.respond(f.clients[0],{id:message.id,result:{success:true}});
  assert.deepEqual(await pending,{success:true});
  assert.equal(f.clients[1].events.length,0);
  await assert.rejects(f.gateway.tool('item/tool/call',{threadId:parent.thread.id,tool:'shell_command'}));
  await assert.rejects(f.gateway.tool('item/tool/call',{threadId:'unknown',tool:'robot'}));
  f.gateway.event({method:'account/updated',params:{account:{private:'never broadcast'}}});
  assert.equal(f.clients[1].events.length,0);
});

test('shared engine loss fences channels and never retries an uncertain turn',async()=>{
  const f=fixture(),parent=await f.start(f.clients[0]);
  await f.gateway.request(f.clients[0],'turn/start',{threadId:parent.thread.id,input:[{type:'text',text:'work'}]});
  f.gateway.fail();
  await assert.rejects(f.gateway.request(f.clients[0],'turn/start',{threadId:parent.thread.id,input:[]}));
  assert.equal(f.calls.filter(c=>c.method==='turn/start').length,1);
  assert.ok(f.clients.every(c=>c.destroyed));
  assert.throws(()=>f.gateway.bind({send(){}},'task-0'));
});

test('real Unix transport supports identical client request IDs without crossing results',async()=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'rf-gw-'));
  const f=fixture(36); // Recreate channels through the socket instead of binding in memory.
  for(const task of f.gateway.tasks.values()){task.state='new';delete task.client;}
  f.gateway.clients.clear();
  const endpoint=path.join(directory,'s');let clients=[];
  try{
    await f.gateway.listen(endpoint);
    clients=f.tasks.map(t=>new GatewayRpc(endpoint,t.id));
    await Promise.all(clients.map(c=>c.initialize()));
    assert.ok(clients.every(c=>c.next===1));
    const parents=await Promise.all(clients.map(c=>c.call('thread/start',{
      dynamicTools:['robot','policy_exec','policy_image'].map(name=>({name}))})));
    assert.equal(new Set(parents.map(p=>p.thread.id)).size,36);
    await Promise.all(clients.map((c,i)=>c.call('thread/read',{threadId:parents[i].thread.id}).then(r=>assert.equal(r.thread.id,parents[i].thread.id))));
    await Promise.all(clients.map(c=>c.close()));
    assert.equal(f.calls.some(c=>c.method==='close'),false);
  }finally{for(const c of clients)c.socket.destroy();await f.gateway.close();fs.rmSync(directory,{recursive:true,force:true});}
});

test('long robot waits retain response ownership beyond the startup RPC timeout',async t=>{
  const f=fixture(),parent=await f.start(f.clients[0]);
  t.mock.timers.enable({apis:['setTimeout']});
  let settled=false;
  const response=f.gateway.tool('item/tool/call',{threadId:parent.thread.id,tool:'robot',
    callId:'original-wait-once',arguments:{op:'wait_events',data:{timeout_s:300}}});
  const result=response.then(value=>{settled=true;return {value};},error=>{settled=true;return {error};});
  const message=f.clients[0].events.at(-1);
  try{
    t.mock.timers.tick(190000);await Promise.resolve();
    assert.equal(settled,false,'A live task may still be waiting for a delegate');
    f.gateway.respond(f.clients[0],{id:message.id,result:{wait_status:'events'}});
    assert.deepEqual((await result).value,{wait_status:'events'});
    assert.equal(f.calls.filter(c=>c.method==='turn/start').length,0);
  }finally{f.gateway.fail();await result;t.mock.timers.reset();}
});

test('closing one task settles its pending tools without stopping peer tasks',async()=>{
  const f=fixture(),parent=await f.start(f.clients[0]);
  const response=f.gateway.tool('item/tool/call',{threadId:parent.thread.id,tool:'robot',
    callId:'wait-until-task-closes',arguments:{op:'wait_events',data:{timeout_s:300}}})
    .then(value=>({value}),error=>({error:error.message}));
  await f.gateway.release(f.clients[0].task);
  assert.match((await response).error,/Task channel closed/);
  assert.equal(f.gateway.serverRequests.size,0);
  assert.equal(f.clients[1].task.state,'bound');
  await f.gateway.request(f.clients[1],'config/read');
  assert.equal(f.calls.some(c=>c.method==='close'),false);
});

test('a delayed tool response keeps its Unix task channel and leaves peers usable',async t=>{
  const directory=fs.mkdtempSync(path.join(os.tmpdir(),'rf-gw-long-')),f=fixture();
  for(const task of f.gateway.tasks.values()){task.state='new';delete task.client;}
  f.gateway.clients.clear();let reply,received;
  const requestArrived=new Promise(resolve=>{received=resolve;});
  const deferred=new Promise(resolve=>{reply=resolve;});let clients=[],response;
  try{
    await f.gateway.listen(path.join(directory,'s'));
    clients=[new GatewayRpc(path.join(directory,'s'),'task-0',{onRequest:()=>{received();return deferred;}}),
             new GatewayRpc(path.join(directory,'s'),'task-1')];
    await Promise.all(clients.map(c=>c.initialize()));
    const parent=await clients[0].call('thread/start',{dynamicTools:['robot','policy_exec','policy_image'].map(name=>({name}))});
    t.mock.timers.enable({apis:['setTimeout']});
    response=f.gateway.tool('item/tool/call',{threadId:parent.thread.id,tool:'robot',callId:'wait-no-replay',
      arguments:{op:'wait_events',data:{timeout_s:300}}}).then(value=>({value}),error=>({error}));
    await requestArrived;t.mock.timers.tick(190000);await Promise.resolve();t.mock.timers.reset();
    reply({wait_status:'events'});
    await new Promise(resolve=>setTimeout(resolve,30));
    assert.equal(Boolean(clients[0].closed),false,'Late owned result must not disconnect its task');
    assert.equal(Boolean(clients[1].closed),false);
    assert.deepEqual((await response).value,{wait_status:'events'});
    await clients[1].call('config/read');
    assert.equal(f.calls.some(c=>c.method==='close'),false);
  }finally{
    t.mock.timers.reset();reply?.({wait_status:'events'});
    for(const c of clients)c.socket.destroy();
    await f.gateway.close();if(response)await response;fs.rmSync(directory,{recursive:true,force:true});
  }
});
