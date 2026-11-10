// Invoked only by the loopback native test with synthetic credentials.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {GatewayRpc}=require('../robofrontier/engines/codex/gateway_rpc');
const {robotTool}=require('../robofrontier/engines/codex/codex_policy_host');
const fileTools=require('../robofrontier/engines/codex/tool_broker');
async function main(manifest){
  let toolCalls=0,completed=0;
  const clients=manifest.tasks.map(t=>{
    const waiters=new Map();
    const rpc=new GatewayRpc(manifest.endpoint,t.id,{
      onRequest:async(method,p)=>{assert.equal(method,'item/tool/call');assert.equal(p.tool,'robot');toolCalls++;
        return {success:true,contentItems:[{type:'inputText',text:'LOCAL_FIXTURE_HANDOFF_OK'}]};},
      onEvent:m=>{if(m.method==='turn/completed'){completed++;waiters.get(m.params.threadId)?.(m.params.turn);}}
    });
    return {rpc,task:t,waiters};
  });
  const turn=async(client,id)=>{
    let timer;
    const finished=new Promise((resolve,reject)=>{timer=setTimeout(()=>reject(new Error('Loopback turn deadline')),20000);client.waiters.set(id,resolve);});
    try{
      await client.rpc.call('turn/start',{threadId:id,model:client.task.model,effort:'high',input:[{type:'text',text:'Offline fixture turn.'}]});
      const result=await finished;assert.equal(result.status,'completed');
    }finally{clearTimeout(timer);client.waiters.delete(id);}
  };
  try{
    await Promise.all(clients.map(c=>c.rpc.initialize()));
    const parents=await Promise.all(clients.map(c=>c.rpc.call('thread/start',{
      cwd:c.task.cwd,model:c.task.model,modelProvider:c.task.provider,approvalPolicy:'never',ephemeral:false,
      baseInstructions:'Offline protocol fixture only.',dynamicTools:[robotTool,...fileTools.tools]
    })));
    for(let i=0;i<parents.length;i++)assert.ok(JSON.stringify(parents[i].activePermissionProfile).includes(clients[i].task.permissions));
    await Promise.all(clients.map((c,i)=>turn(c,parents[i].thread.id)));
    const childIds=[];
    // Finish bounded children, then fork a fresh round on the same parent.
    for(let round=0;round<2;round++){
      const children=await Promise.all(clients.map((c,i)=>c.rpc.call('thread/fork',{
        threadId:parents[i].thread.id,cwd:c.task.cwd,model:c.task.model,modelProvider:c.task.provider,excludeTurns:true,ephemeral:false
      })));
      for(let i=0;i<children.length;i++){
        assert.equal(children[i].thread.forkedFromId,parents[i].thread.id);
        assert.ok(JSON.stringify(children[i].activePermissionProfile).includes(clients[i].task.permissions));
        childIds.push(children[i].thread.id);
      }
      await Promise.all(clients.map((c,i)=>turn(c,children[i].thread.id)));
    }
    await assert.rejects(clients[0].rpc.call('thread/read',{threadId:parents[1].thread.id}));
    assert.equal(new Set(childIds).size,childIds.length);
    assert.equal(completed,clients.length*3);assert.equal(toolCalls,clients.length*3);
    await clients[0].rpc.close();
    const nonce='fixture-recovery-authority',task=clients[0].task;
    const control=new GatewayRpc(manifest.endpoint,task.id);
    await control.ready;
    assert.equal((await control.call('gateway/capabilities')).singleTaskRecovery,1);
    const status=await control.call('gateway/recovery/status',{taskId:task.id});
    assert.equal(status.state,'closed');assert.equal(status.pendingTools,0);
    control.socket.destroy();
    fs.writeFileSync(manifest.recovery_directory+'/'+task.id+'.json',JSON.stringify({
      schema:'robofrontier.task-recovery-grant.v1',taskId:task.id,run:task.run,
      threads:status.threads,nonce,expiresAt:Date.now()/1000+120}),{mode:0o600});
    let recoveryTools=0,finished;
    const recovered=new GatewayRpc(manifest.endpoint,task.id,{recoveryNonce:nonce,
      onRequest:async(method,p)=>{
        recoveryTools++;assert.equal((typeof p.arguments==='string'?JSON.parse(p.arguments):p.arguments).op,'inbox');
        return {success:true,contentItems:[{type:'inputText',text:'RECOVERY_FIXTURE_OK'}]};},
      onEvent:m=>{if(m.method==='turn/completed')finished?.(m.params.turn);}
    });
    try{
      assert.equal((await recovered.initialize()).recovered,true);
      const resumed=await recovered.call('thread/resume',{threadId:parents[0].thread.id});
      assert.equal(resumed.thread.id,parents[0].thread.id);
      assert.equal(recoveryTools,0,'history must not redispatch a recorded tool');
      assert.ok(JSON.stringify(resumed.activePermissionProfile).includes(task.permissions));
      await assert.rejects(recovered.call('thread/read',{threadId:parents[1].thread.id}));
      for(let round=0;round<2;round++){
        const id=round===0?resumed.thread.id:(await recovered.call('thread/fork',{
          threadId:resumed.thread.id,excludeTurns:true,ephemeral:false})).thread.id;
        let timer;
        const done=new Promise((resolve,reject)=>{finished=resolve;timer=setTimeout(()=>reject(Error('Recovery fixture deadline')),20000);});
        try{
          await recovered.call('turn/start',{threadId:id,input:[{type:'text',text:'Recovery fixture, inbox only.'}]});
          assert.equal((await done).status,'completed');
        }finally{clearTimeout(timer);finished=null;}
        await clients[1].rpc.call('thread/read',{threadId:parents[1].thread.id});
      }
      assert.equal(recoveryTools,2);
      await recovered.close();
    }finally{recovered.socket.destroy();}
    await Promise.all(clients.slice(1).map(c=>c.rpc.close()));
    console.log(JSON.stringify({passed:true,parents:parents.length,children:childIds.length,completed,tool_calls:toolCalls,
      single_task_recovery:true,recovery_tools:recoveryTools,model_provider:'loopback fixture only',physical_actions:0}));
  }finally{for(const c of clients)c.rpc.socket.destroy();}
}
main(JSON.parse(fs.readFileSync(process.argv[2]))).catch(error=>{console.error(error.stack);process.exitCode=1;});
