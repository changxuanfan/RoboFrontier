// A Codex turn that failed on the plan's usage limit pauses the world until the reset and is then
// continued once with the frozen quota notice (runtime/quota.py), as on Claude.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {PolicyHost}=require('../../robofrontier/engines/codex/codex_policy_host');
const {usageLimitFailure,capacityFailure}=require('../../robofrontier/engines/codex/codex_rpc');
const ROOT=path.resolve(__dirname,'../..');

test('a usage limit is not a capacity failure',()=>{
  const error={message:"You've hit your usage limit. Try again in 2 days 4 hours.",codexErrorInfo:{usageLimitExceeded:{}}};
  assert.equal(usageLimitFailure(error),true);
  assert.equal(capacityFailure(error),false);
  assert.equal(usageLimitFailure({message:'429 Too Many Requests'}),false);
});

test('the host asks for a pause, waits for the reset, then continues the turn once',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rf-quota-'));
  try {
    fs.mkdirSync(path.join(dir,'private/inputs/bootstrap'),{recursive:true});
    fs.writeFileSync(path.join(dir,'private/inputs/bootstrap/quota-resume.md'),'QUOTA NOTICE');
    const failed={id:'turn-1',status:'failed',error:{message:"You've hit your usage limit. Try again in 3 hours."}};
    const admin=[],sent=[];let snapshot={lifecycle:'running',paused:false,agents:{Controller:{kind:'controller'}}};
    const host=Object.create(PolicyHost.prototype);
    Object.assign(host,{run:dir,cwd:ROOT,python:path.join(ROOT,'.venv/bin/python'),stopped:false,retries:new Set(),failures:new Map(),
      actors:new Map([['thread-1','Controller']]),event(){},
      observe:async()=>({thread:{status:{type:'systemError'}},latestTurn:failed}),
      send:async(id,text)=>{sent.push([id,text]);},
      admin:async(op,data)=>{admin.push([op,data]);if(op==='snapshot')return snapshot;if(op==='network-recovery')return {allowed:true};return {};}});
    await host.retryCapacity();
    const pause=admin.find(([op])=>op==='quota-pause');
    assert.ok(pause);assert.ok(pause[1].resets_at>Date.now()/1000+3*3600-60);
    snapshot={...snapshot,paused:true};await host.retryCapacity();
    assert.equal(sent.length,0);
    snapshot={...snapshot,paused:false,egress_recovery:{claim:'quota-1',paused_at:Date.now()/1000-5,resumed_at:Date.now()/1000+1}};
    fs.mkdirSync(path.join(dir,'private/state'),{recursive:true});
    await host.retryCapacity();
    assert.deepEqual(sent,[['thread-1','QUOTA NOTICE']]);
    assert.equal(admin.filter(([op])=>op==='quota-pause').length,1);
    await host.retryCapacity();
    assert.equal(sent.length,1);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
