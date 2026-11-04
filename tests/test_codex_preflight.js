const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {preflight}=require('../robofrontier/codex/codex_preflight');
function fakeRpc({badParent=false,badChild=false,badImage=false,noFork=false,inheritedMcp=false,onThreadStart=()=>{},onFork=()=>{}}={}) {
  return class {
    constructor(args,handlers){this.handlers=handlers;}
    async initialize(){}
    async close(){}
    async call(method,p={}) {
      if(method==='config/read')return {config:{mcp_servers:inheritedMcp?{personal:{enabled:true}}:{}}};
      if(method==='thread/start'){onThreadStart(p);return {thread:{id:'parent'}};}
      if(noFork && ['thread/fork','thread/compact/start'].includes(method))throw new Error('Smoke must not fork/compact');
      if(method==='thread/fork'){onFork(p);return {thread:{id:'child',forkedFromId:badParent?'other':'parent'}};}
      if(method==='thread/compact/start') {
        this.handlers.onEvent({method:'thread/compacted',params:{threadId:'parent'}});return {};
      }
      if(method==='turn/start') {
        const child=p.threadId==='child';
        await this.handlers.onRequest('item/tool/call',{tool:'protocol_check',threadId:p.threadId,
          arguments:JSON.stringify({left:badImage||child&&badChild?'green':'red',right:'blue'})});
        this.handlers.onEvent({method:'turn/completed',params:{threadId:p.threadId,turn:{status:'completed'}}});
        return {};
      }
      return {};
    }
  };
}
async function run(opts,mode={},provider='sample') {
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'rf-preflight-'));
  try {
    fs.writeFileSync(path.join(folder,'launch.json'),JSON.stringify({args:[],model:'sample',provider,effort:'high',context_window:272000,auto_compact_token_limit:245000,
      ...(opts?.jobScoped?{profile:{runner_backend:'slurm-managed-v1'},tool_probe:{run_dir:path.join(folder,'bound-run')}}:{})}));
    fs.writeFileSync(path.join(folder,'probe.json'),JSON.stringify({version:'test',left:'red',right:'blue',
      colors:['blue','green','red','yellow'],prompt:'Name the left and right colors.'}));
    return await preflight(folder,fakeRpc(opts),mode);
  } finally {fs.rmSync(folder,{recursive:true,force:true});}
}
test('preflight verifies fork parent and inherited tool result',async()=>{
  const result=await run();assert.equal(result.passed,true);assert.equal(result.fork_history_and_tool,true);
  assert.equal(result.automatic_compaction_tested,false);assert.equal(result.context_stress_tested,false);
});
test('preflight fails closed on incorrect fork parent',async()=>{
  const result=await run({badParent:true});assert.equal(result.passed,false);assert.match(result.error,/parent mismatch/);
});
test('preflight fails closed when child cannot recover image colors',async()=>{
  const result=await run({badChild:true});assert.equal(result.passed,false);assert.match(result.error,/inherit/);
});
test('smoke checks vision and tools without compaction or fork qualification',async()=>{
  const result=await run({noFork:true},{smokeOnly:true});
  assert.equal(result.passed,true);assert.equal(result.smoke_only,true);
  assert.equal(result.fork_history_and_tool,undefined);
});
test('smoke rejects incorrect image interpretation',async()=>{
  const result=await run({badImage:true},{smokeOnly:true});assert.equal(result.passed,false);
});
test('subscription preflight rejects inherited MCP before starting a native thread',async()=>{
  let starts=0;
  const result=await run({inheritedMcp:true,onThreadStart:()=>starts++},{},'openai');
  assert.equal(result.passed,false);assert.match(result.error,/MCP servers/);
  assert.equal(starts,0);
});
test('subscription preflight retains full protocol checks after native tool admission',async()=>{
  const result=await run({}, {}, 'openai');
  assert.equal(result.passed,true);assert.equal(result.native_mcp_config_verified,true);
  assert.equal(result.auth_mode,'native_managed_subscription');
  assert.equal(result.fork_history_and_tool,true);
});
test('the colour check offers a fixed list and reports what the model answered',async()=>{
  let start;const ok=await run({onThreadStart:p=>{start=p;}});assert.equal(ok.passed,true);assert.equal(ok.probe_version,'test');
  const schema=start.dynamicTools[0].inputSchema.properties;
  assert.deepEqual(schema.left.enum,['blue','green','red','yellow']);assert.deepEqual(schema.right.enum,schema.left.enum);
  const bad=await run({badImage:true},{smokeOnly:true});
  assert.equal(bad.passed,false);assert.match(bad.error,/"tool_called":true/);assert.match(bad.error,/"left":"green"/);
});
test('job preflight starts and forks in the gateway-bound workspace',async()=>{
  const calls=[];const result=await run({jobScoped:true,onThreadStart:p=>calls.push(p.cwd),onFork:p=>calls.push(p.cwd)});
  assert.equal(result.passed,true);assert.equal(calls.length,2);assert.equal(calls[0],calls[1]);
  assert.ok(calls[0].endsWith(path.join('bound-run','workspace')));
});
