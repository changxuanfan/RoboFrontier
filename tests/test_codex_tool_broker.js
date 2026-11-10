const test=require('node:test'),assert=require('node:assert/strict');
const {PolicyHost}=require('../robofrontier/engines/codex/codex_policy_host');
const broker=require('../robofrontier/engines/codex/tool_broker');
test('file tools reject unbound roles before accessing files',async()=>{
  const host=Object.create(PolicyHost.prototype);
  host.launch={tool_backend:'landlock-v1'};host.actors=new Map();
  await assert.rejects(host.toolRequest('item/tool/call',{threadId:'other',tool:'policy_exec',arguments:{command:'pwd'}}),/Unbound/);
});
test('model arguments cannot choose a different run, rules or executable',()=>{
  for(const args of [{command:'pwd',run_dir:'/other'},{command:'pwd',rules:'/other'},
                      {command:'pwd',python:'/other'},{command:'pwd',timeout_s:Infinity}])
    assert.throws(()=>broker.call('/run','python','policy_exec',args),/Unsupported|Invalid/);
});
test('native handler admission refuses weak inherited configuration',async()=>{
  const rpc={call:async()=>({config:{mcp_servers:{},features:{shell_tool:true}}})};
  await assert.rejects(broker.admit(rpc,{tool_backend:'landlock-v1',args:[]}),/not restricted/);
});
