// Invoked only by the loopback native test with synthetic credentials.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {GatewayRpc}=require('../robofrontier/codex/gateway_rpc');
const {robotTool}=require('../robofrontier/codex/codex_policy_host');
const fileTools=require('../robofrontier/codex/tool_broker');
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
    await Promise.all(clients.map(c=>c.rpc.close()));
    console.log(JSON.stringify({passed:true,parents:parents.length,children:childIds.length,completed,tool_calls:toolCalls,
      model_provider:'loopback fixture only',physical_actions:0}));
  }finally{for(const c of clients)c.rpc.socket.destroy();}
}
main(JSON.parse(fs.readFileSync(process.argv[2]))).catch(error=>{console.error(error.stack);process.exitCode=1;});
