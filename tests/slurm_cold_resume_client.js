// Real native cold resume, only against the synthetic loopback fixture.
const assert=require('node:assert/strict'),fs=require('node:fs');
const {GatewayRpc}=require('../robofrontier/engines/codex/gateway_rpc');
async function main(manifest){
  let tools=0;const clients=[];
  try{
    for(const task of manifest.tasks){
      let finish;
      const rpc=new GatewayRpc(manifest.endpoint,task.id,{
        onRequest:async(m,p)=>{assert.equal(m,'item/tool/call');assert.equal(p.tool,'robot');tools++;
          return {success:true,contentItems:[{type:'inputText',text:'COLD_RESUME_FIXTURE_OK'}]};},
        onEvent:m=>{if(m.method==='turn/completed')finish?.(m.params.turn);}
      });clients.push(rpc);await rpc.initialize();
      for(const id of task.resumeThreads){
        const resumed=await rpc.call('thread/resume',{threadId:id});
        assert.equal(resumed.thread.id,id);
        assert.ok(JSON.stringify(resumed.activePermissionProfile).includes(task.permissions));
      }
      assert.equal(tools,clients.length-1,'loading history must not replay tool calls');
      let timer;
      const done=new Promise((resolve,reject)=>{finish=resolve;timer=setTimeout(()=>reject(Error('Cold resume fixture deadline')),20000);});
      try{
        await rpc.call('turn/start',{threadId:task.resumeThreads[0],input:[{type:'text',text:'Continue the fixture with inbox only.'}]});
        assert.equal((await done).status,'completed');
      }finally{clearTimeout(timer);}
      await rpc.close();
    }
    assert.equal(tools,manifest.tasks.length);
    console.log(JSON.stringify({passed:true,original_thread_ids_preserved:true,tools,physical_replays:0}));
  }finally{for(const rpc of clients)rpc.socket.destroy();}
}
main(JSON.parse(fs.readFileSync(process.argv[2]))).catch(e=>{console.error(e.stack);process.exitCode=1;});
