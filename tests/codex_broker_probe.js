// Real native CLI, production role-bound broker, synthetic provider only.
const fs=require('node:fs'),path=require('node:path');
const {CodexRpc}=require('../robofrontier/engines/codex/codex_rpc');
const {PolicyHost,robotTool}=require('../robofrontier/engines/codex/codex_policy_host');
const broker=require('../robofrontier/engines/codex/tool_broker');
const out=process.argv[2],launch=JSON.parse(fs.readFileSync(path.join(out,'launch.json')));
const host=Object.create(PolicyHost.prototype);
Object.assign(host,{run:launch.tool_probe.run_dir,python:launch.python,launch,actors:new Map(),event:()=>{}});
let waits=new Map(),succeeded=0,privateImageRejected=false;
const rpc=new CodexRpc(launch.args,{stderr:fs.openSync(path.join(out,'server.log'),'w'),
  onEvent:m=>{if(m.method==='turn/completed')waits.get(m.params.threadId)?.(m.params.turn);},
  onRequest:async(method,p)=>{
    const result=await host.toolRequest(method,p);
    if(result.success)succeeded++;
    if(p.tool==='policy_image'&&!result.success)privateImageRejected=true;
    return result;
  }});
async function turn(id,scenario){
  let timer;const finished=new Promise((resolve,reject)=>{
    waits.set(id,resolve);timer=setTimeout(()=>reject(new Error('Turn timeout: '+scenario)),30000);
  });
  try{
    await rpc.call('turn/start',{threadId:id,input:[{type:'text',text:'scenario:'+scenario}]});
    const result=await finished;if(result.status!=='completed')throw new Error(JSON.stringify(result.error));
  }finally{clearTimeout(timer);waits.delete(id);}
}
async function start(actor){
  const result=await rpc.call('thread/start',{cwd:path.join(host.run,'workspace'),model:launch.model,
    modelProvider:launch.provider,approvalPolicy:'never',dynamicTools:[robotTool,...broker.tools],
    baseInstructions:'Offline broker protocol validation. No real robot world.'});
  host.actors.set(result.thread.id,actor);return result.thread.id;
}
(async()=>{
 try{
  await rpc.initialize();await broker.admit(rpc,launch);
  const parent=await start('Controller');
  for(const scenario of ['allowed','image','image_escape','native_shell','native_exec','native_stdin',
    'native_patch','native_image','native_read','native_list','native_js','native_agent','native_collab','native_freeform'])
    await turn(parent,scenario);
  const child=await rpc.call('thread/fork',{threadId:parent,excludeTurns:true});
  host.actors.set(child.thread.id,'Delegate');await turn(child.thread.id,'fork');
  await rpc.call('thread/resume',{threadId:child.thread.id,excludeTurns:true});await turn(child.thread.id,'resume');
  const roles=await Promise.all(Array.from({length:8},(_,n)=>start('Worker-'+n)));
  await Promise.all(roles.map((id,n)=>turn(id,'concurrent_'+n)));
  fs.writeFileSync(path.join(out,'client-report.json'),JSON.stringify({tools_succeeded:succeeded,
    private_image_rejected:privateImageRejected,concurrent_roles:roles.length,
    fork_verified:child.thread.forkedFromId===parent,resume_verified:true},null,2));
 }finally{
  for(const threadId of host.actors.keys())try{await rpc.call('thread/archive',{threadId});}catch{}
  await rpc.close();
 }
})().then(()=>process.exit(0)).catch(e=>{console.error(e.stack);process.exit(1)});
