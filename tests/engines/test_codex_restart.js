const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {PolicyHost}=require('../../robofrontier/engines/codex/codex_policy_host');

test('a lost app-server is replaced and each working role resumes with the frozen notice',async()=>{
  const dir=fs.mkdtempSync(path.join(os.tmpdir(),'rf-restart-'));
  try {
    fs.mkdirSync(path.join(dir,'private/inputs/bootstrap'),{recursive:true});
    fs.writeFileSync(path.join(dir,'private/inputs/bootstrap/model-restart.md'),'RESTART NOTICE');
    fs.writeFileSync(path.join(dir,'private/inputs/bootstrap/system.md'),'frozen system');
    const calls=[],sent=[];
    const host={run:dir,launch:{model:'m',provider:'p'},actors:new Map(),layout:{policy_cwd:'workspace'},
      hostPath:PolicyHost.prototype.hostPath,event:()=>{},
      startServer:async()=>{host.rpc={call:async(method,params)=>{calls.push([method,params.threadId]);return {};}};},
      admin:async()=>({agents:{Meta:{kind:'manager'},Controller:{kind:'controller',thread_id:'t-c'},
        D1:{kind:'delegate',thread_id:'t-d1',delegation_state:'active'},
        D2:{kind:'delegate',thread_id:'t-d2',delegation_state:'returned'}}}),
      send:async(id,text)=>sent.push([id,text])};
    await PolicyHost.prototype.restartModelHost.call(host);
    assert.deepEqual(calls.map(c=>c[1]),['t-c','t-d1','t-d2']);
    assert(calls.every(c=>c[0]==='thread/resume'));
    // Only working roles get the notice; every thread is mapped back to its role.
    assert.deepEqual(sent,[['t-c','RESTART NOTICE'],['t-d1','RESTART NOTICE']]);
    assert.equal(host.actors.get('t-d2'),'D2');
  } finally {fs.rmSync(dir,{recursive:true,force:true});}
});
