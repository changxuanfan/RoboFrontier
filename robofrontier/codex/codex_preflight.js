// Explicitly invoked paid connectivity test, separate from scored robot trials.
const fs=require('node:fs'),path=require('node:path');
const {CodexRpc,STARTUP_ACK_MS,requireNoMcpServers}=require('./codex_rpc');
const {GatewayRpc}=require('./gateway_rpc');
const fileTools=require('./tool_broker');
async function preflight(folder, Rpc=CodexRpc, {smokeOnly=false}={}) {
  const launch=JSON.parse(fs.readFileSync(path.join(folder,'launch.json')));
  // Written with colors.png by robofrontier/preflight_probe.py: random left/right colours.
  const probe=JSON.parse(fs.readFileSync(path.join(folder,'probe.json')));
  const waits=new Map();
  let resolveCompact;
  const compacted=new Promise(r=>resolveCompact=r);
  const tools=new Map(),calls=new Map(),brokerExec=new Set(),brokerImage=new Set(),bound=new Set();
  let compact=false,id,childId;
  const serverLog=fs.openSync(path.join(folder,'server.log'),'a');
  const rpc=new Rpc(launch.args,{stderr:serverLog,
    onEvent:m=>{
      if(m.method==='turn/completed') waits.get(m.params.threadId)?.(m.params.turn);
      if(m.method==='thread/compacted' || m.method==='item/completed' && m.params?.item?.type==='contextCompaction') {compact=true;resolveCompact(true);}
      if(m.method==='error' && !m.params?.willRetry)resolveCompact(false);
    },onRequest:async(m,p)=>{
      if(m==='item/tool/call'&&fileTools.enabled(launch)&&bound.has(p.threadId)&&
          ['policy_exec','policy_image'].includes(p.tool)) {
        const a=typeof p.arguments==='string'?JSON.parse(p.arguments):p.arguments;
        const result=await fileTools.call(launch.tool_probe.run_dir,process.env.ROBOFRONTIER_PYTHON||'python3',p.tool,a);
        if(result.success&&p.tool==='policy_exec'&&a.command===launch.tool_probe.command) {
          const output=JSON.parse(result.contentItems[0].text);
          if(output.exit_code===0&&output.stdout.trim()==='BROKER_ISOLATION_OK')brokerExec.add(p.threadId);
        }
        if(result.success&&p.tool==='policy_image'&&a.path===launch.tool_probe.image)brokerImage.add(p.threadId);
        return result;
      }
      if(m!=='item/tool/call' || p.tool!=='protocol_check')throw new Error('Unsupported preflight request');
      const a=typeof p.arguments==='string'?JSON.parse(p.arguments):p.arguments;
      const valid=a.left===probe.left&&a.right===probe.right; tools.set(p.threadId,valid); calls.set(p.threadId,a);
      return {success:valid,contentItems:[{type:'inputText',text:valid?'VISION_TOOL_OK':'Incorrect image colors'}]};
    }});
  fs.closeSync(serverLog);
  let report={passed:false,model:launch.model,provider:launch.provider,effort:launch.effort,probe_version:probe.version,
    actual_provider_model_verified:false,context_window:launch.context_window,
    auto_compact_token_limit:launch.auto_compact_token_limit,context_stress_tested:false,
    automatic_compaction_tested:false,smoke_only:smokeOnly,
    scope:smokeOnly?'Small real API image/function round trip; no robot trial or run qualification':
      'Small real API image/function/manual-compaction/fork test; no robot trial'};
  const deadline=(promise,ms)=>new Promise((resolve,reject)=>{
    const t=setTimeout(()=>reject(new Error('Preflight deadline exceeded')),ms);
    promise.then(v=>{clearTimeout(t);resolve(v);},e=>{clearTimeout(t);reject(e);});
  });
  const nextTurn=thread=>new Promise(resolve=>waits.set(thread,resolve));
  try {
    await rpc.initialize();
    await fileTools.admit(rpc,launch);
    if(fileTools.subscription(launch)) {
      await requireNoMcpServers(rpc);
      report.native_mcp_config_verified=true;
      report.auth_mode='native_managed_subscription';
      report.scope=report.scope.replace('real API','native subscription');
    }
    const a=await rpc.call('thread/start',{cwd:folder,model:launch.model,modelProvider:launch.provider,
      approvalPolicy:'never',sandbox:'read-only',dynamicTools:[{type:'function',name:'protocol_check',
        description:'Submit the color of the left half and of the right half of the image.',inputSchema:{type:'object',
                   properties:{left:{type:'string',enum:probe.colors},right:{type:'string',enum:probe.colors}},required:['left','right']}},
                   ...(fileTools.enabled(launch)?fileTools.tools:[])]},
      STARTUP_ACK_MS);id=a.thread.id;bound.add(id);
    await rpc.call('thread/name/set',{threadId:id,name:'API preflight · '+launch.model});
    const finished=nextTurn(id);
    const brokerPrompt=fileTools.enabled(launch)?' First call policy_exec with command '+JSON.stringify(launch.tool_probe.command)+
      ', require BROKER_ISOLATION_OK, then call policy_image with path '+JSON.stringify(launch.tool_probe.image)+'. ':'';
    await rpc.call('turn/start',{threadId:id,model:launch.model,effort:launch.effort,input:[
      {type:'text',text:probe.prompt+brokerPrompt+' Call protocol_check with those two colors. Then reply with the tool result.'},
      {type:'localImage',path:path.join(folder,'colors.png')} ]});
    const turn=await deadline(finished,180000);
    // Say which check failed: the turn itself, a missing tool call, or wrong colors.
    if(turn.status!=='completed' || !tools.get(id))throw new Error('Parent image/tool turn failed: '+JSON.stringify(
      {status:turn.status,error:turn.error,tool_called:calls.has(id),arguments:calls.get(id)??null}));
    if(fileTools.enabled(launch)&&(!brokerExec.has(id)||!brokerImage.has(id)))throw new Error('Parent broker tools were not verified');
    if(smokeOnly) {
      report={...report,passed:true,vision_and_function:true,thread_id:id};
      return report;
    }
    await rpc.call('thread/compact/start',{threadId:id});
    if(!await deadline(compacted,180000))throw new Error('Compaction failed');
    const fork=await rpc.call('thread/fork',{threadId:id,cwd:folder,model:launch.model,
      modelProvider:launch.provider,excludeTurns:true,ephemeral:false});
    childId=fork.thread.id;bound.add(childId);
    if(fork.thread.forkedFromId!==id)throw new Error('Fork parent mismatch');
    const childFinished=nextTurn(childId);
    await rpc.call('turn/start',{threadId:childId,model:launch.model,effort:launch.effort,input:[
      {type:'text',text:'Using the image and tool result from our prior conversation,'+brokerPrompt+' call protocol_check again with the same left and right colors.'}]});
    const child=await deadline(childFinished,180000);
    if(child.status!=='completed' || !tools.get(childId))throw new Error('Fork did not inherit usable image history and tool');
    if(fileTools.enabled(launch)&&(!brokerExec.has(childId)||!brokerImage.has(childId)))throw new Error('Fork broker tools were not verified');
    report={...report,passed:true,vision_and_function:true,compaction:compact,
      fork_parent_verified:true,fork_history_and_tool:true,thread_id:id,child_thread_id:childId,
      broker_tools_verified:fileTools.enabled(launch)?true:undefined};
  } catch(e) {report.error=e.message;}
  finally {
    for(const thread of [childId,id])if(thread)try{await rpc.call('thread/archive',{threadId:thread});}catch{}
    await rpc.close();
    fs.writeFileSync(path.join(folder,'report.json'),JSON.stringify(report,null,2)+'\n');
  }
  return report;
}
if(require.main===module){
  const folder=path.resolve(process.argv[2]);
  const jobScoped=JSON.parse(fs.readFileSync(path.join(folder,'launch.json'))).profile?.runner_backend==='slurm-managed-v1';
  const Rpc=jobScoped?class extends GatewayRpc {constructor(args,callbacks){
    if(!process.env.ROBOFRONTIER_CODEX_GATEWAY||!process.env.ROBOFRONTIER_CODEX_TASK)throw new Error('Missing admitted job preflight channel');
    super(process.env.ROBOFRONTIER_CODEX_GATEWAY,process.env.ROBOFRONTIER_CODEX_TASK,callbacks);
  }}:CodexRpc;
  preflight(folder,Rpc,{smokeOnly:process.argv.includes('--smoke-only')})
    .then(r=>{console.log(JSON.stringify(r));process.exitCode=r.passed?0:1;});
}
module.exports={preflight};
