const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {PolicyHost}=require('../robofrontier/engines/codex/codex_policy_host');

test('seal failure propagates after cleanup and never reports host success',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rf-seal-'));
  try {
    fs.mkdirSync(path.join(dir,'private/inputs'),{recursive:true});
    fs.writeFileSync(path.join(dir,'private/inputs/manifest.json'),JSON.stringify({model_requested:'m',effort_requested:'high'}));
    let closed=false;const events=[];
    const host={run:dir,launch:{model:'m',effort:'high'},actors:new Map(),layout:{stop:'STOP'},hostPath:PolicyHost.prototype.hostPath,
      startServer:async()=>{throw new Error('startup failure');},
      admin:async()=>{throw new Error('unresolved physical action');},
      event:e=>events.push(e),rpc:{close:async()=>{closed=true;}}};
    // The error names both the seal failure and the host failure that came before it.
    await assert.rejects(PolicyHost.prototype.runTask.call(host),/seal incomplete.*after host error: startup failure/);
    assert.equal(closed,true);assert.deepEqual(events.map(e=>e.event).slice(0,2),['host_error','seal_error']);
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});

test('after a normal finish existing turns may finish their reply before the seal',async()=>{
  const events=[];let polls=0;
  const host={actors:new Map([['t','Controller']]),admin:async()=>({lifecycle:'ended'}),
    observe:async()=>({thread:{status:{type:++polls<3?'active':'idle'}}}),event:e=>events.push(e)};
  assert.equal(await PolicyHost.prototype.drainFinishedTurns.call(host,1000,1),true);
  assert.equal(polls,3);assert.deepEqual(events.at(-1),{event:'finish_turns_drained',drained:true});
  const stuck={...host,observe:async()=>({thread:{status:{type:'active'}}})};
  assert.equal(await PolicyHost.prototype.drainFinishedTurns.call(stuck,20,1),false);
  const running={...host,admin:async()=>({lifecycle:'running'})};
  assert.equal(await PolicyHost.prototype.drainFinishedTurns.call(running,20,1),null);
});
