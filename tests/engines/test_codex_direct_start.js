const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {PolicyHost}=require('../../robofrontier/engines/codex/codex_policy_host');

// A run folder holding the frozen system and start messages a prepared run has.
function frozenRun() {
  const run=fs.mkdtempSync(path.join(os.tmpdir(),'codex-direct-start-'));
  const folder=path.join(run,'private/inputs/bootstrap');fs.mkdirSync(folder,{recursive:true});
  fs.writeFileSync(path.join(folder,'system.md'),'frozen system');
  for (const actor of ['Controller','A','B']) fs.writeFileSync(path.join(folder,actor+'.md'),'frozen start for '+actor);
  test.after(()=>fs.rmSync(run,{recursive:true,force:true}));
  return run;
}

function fixture() {
  const operations=[];
  let threads=0;
  const host={
    run:frozenRun(),layout:{policy_cwd:'.'},launch:{model:'offline',provider:'offline'},actors:new Map(),
    hostPath:PolicyHost.prototype.hostPath,
    event:e=>operations.push({type:'event',...e}),
    stopRequested:()=>false,
    rpc:{call:async(method,data)=>{
      operations.push({type:method,...data});
      return method==='thread/start'?{thread:{id:'thread-'+(++threads)}}:{};
    }},
    bindInitialRole:async(actor,id)=>{operations.push({type:'bind',actor,id});return {bound:true};},
    admin:async op=>{operations.push({type:op});return {started:true};},
    send:async(id,prompt)=>{operations.push({type:'send',id,prompt});},
    bootstrap:PolicyHost.prototype.bootstrap,
  };
  return {host,operations};
}
const standing={Meta:{kind:'manager'},Controller:{kind:'team-controller'},A:{kind:'worker'},B:{kind:'worker'}};

test('direct team binds every role, starts once, then supplies explicit START prompts',async()=>{
  const {host,operations}=fixture();
  await PolicyHost.prototype.startInitialRoles.call(host,standing,'direct_team_v3');
  const start=operations.findIndex(o=>o.type==='request-start');
  assert.equal(operations.filter(o=>o.type==='request-start').length,1);
  assert.equal(operations.slice(0,start).filter(o=>o.type==='bind').length,3);
  assert.equal(operations.slice(0,start).filter(o=>o.type==='send').length,0);
  const prompts=operations.filter(o=>o.type==='send');
  assert.equal(prompts.length,3);
  assert.deepEqual(prompts.map(item=>item.prompt),['Controller','A','B'].map(actor=>'frozen start for '+actor));
  for (const item of operations.filter(o=>o.type==='thread/start')) assert.equal(item.baseInstructions,'frozen system');
});
test('Controller-only direct startup still binds and starts before its first model input',async()=>{
  const {host,operations}=fixture();
  await PolicyHost.prototype.startInitialRoles.call(host,{Meta:{kind:'manager'},Controller:{kind:'controller'}},'direct_controller_v2');
  assert.ok(operations.findIndex(o=>o.type==='bind')<operations.findIndex(o=>o.type==='request-start'));
  assert.ok(operations.findIndex(o=>o.type==='request-start')<operations.findIndex(o=>o.type==='send'));
});
test('failed binding starts no task and sends no misleading started prompt',async()=>{
  const {host,operations}=fixture();
  host.bindInitialRole=async()=>({bound:false});
  await assert.rejects(PolicyHost.prototype.startInitialRoles.call(host,standing,'direct_team_v3'),/binding/);
  assert.equal(operations.filter(o=>['request-start','send'].includes(o.type)).length,0);
});
test('a rejected START cannot result in any initial model turn',async()=>{
  const {host,operations}=fixture();
  host.admin=async()=>({error:'not ready',started:false});
  await assert.rejects(PolicyHost.prototype.startInitialRoles.call(host,standing,'direct_team_v3'),/START/);
  assert.equal(operations.filter(o=>o.type==='send').length,0);
});
test('a run without its frozen system message creates no session',async()=>{
  const {host,operations}=fixture();
  fs.rmSync(path.join(host.run,'private/inputs/bootstrap/system.md'));
  await assert.rejects(PolicyHost.prototype.startInitialRoles.call(host,standing,'direct_team_v3'),/Missing frozen bootstrap message/);
  assert.equal(operations.length,0);
});
test('an unknown protocol fails before any native session creation',async()=>{
  const {host,operations}=fixture();
  await assert.rejects(PolicyHost.prototype.startInitialRoles.call(host,standing,'typo'),/protocol/);
  assert.equal(operations.length,0);
});
test('STOP during binding prevents START and all initial model turns',async()=>{
  const {host,operations}=fixture();
  const original=host.bindInitialRole;
  host.bindInitialRole=async(...args)=>{
    const result=await original(...args);
    host.stopRequested=()=>true;
    return result;
  };
  await assert.rejects(PolicyHost.prototype.startInitialRoles.call(host,standing,'direct_team_v3'),/Stop requested/);
  assert.equal(operations.filter(o=>['request-start','send'].includes(o.type)).length,0);
});
