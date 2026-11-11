// A robot_only Codex run: no file tools beside robot, and public_file results reach the model.
const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),os=require('node:os'),path=require('node:path');
const {PolicyHost}=require('../../robofrontier/engines/codex/codex_policy_host');
const broker=require('../../robofrontier/engines/codex/tool_broker');
const PNG=Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),Buffer.alloc(32)]);
function host(answer,launch={tool_backend:'native',tool_mode:'robot_only'}){
  const run=fs.mkdtempSync(path.join(os.tmpdir(),'rf-robot-only-'));
  fs.mkdirSync(path.join(run,'public/inputs'),{recursive:true});fs.mkdirSync(path.join(run,'private'));
  fs.writeFileSync(path.join(run,'public/inputs/target.png'),PNG);fs.writeFileSync(path.join(run,'private/secret.png'),PNG);
  const value=Object.create(PolicyHost.prototype);
  Object.assign(value,{run,launch,actors:new Map([['thread','Controller']]),event:()=>{},
    clients:new Map([['Controller',{call:async()=>({status:0,output:JSON.stringify(answer(run))})}]])});
  return value;
}
const call=(h,op,data={})=>h.toolRequest('item/tool/call',{threadId:'thread',tool:'robot',callId:'c1',arguments:{op,data}});
test('robot_only is separate from the tool worker and adds no file tools',()=>{
  const launch={tool_backend:'native',tool_mode:'robot_only'};
  assert.equal(broker.robotOnly(launch),true);assert.equal(broker.enabled(launch),false);
  assert.equal(broker.robotOnly({profile:{tool_mode:'robot_only'}}),true);
  assert.equal(broker.robotOnly({tool_backend:'landlock-v1'}),false);
  assert.equal(broker.robotOnly({}),false);
});
test('admission refuses a robot_only launch whose Codex tools are still on',async()=>{
  const rpc={call:async()=>({config:{mcp_servers:{},features:{shell_tool:true}}})};
  await assert.rejects(broker.admit(rpc,{tool_backend:'native',tool_mode:'robot_only',args:[]}),/not restricted/);
  // A full native launch is not checked here, as before.
  await broker.admit({call:async()=>{throw new Error('not consulted');}},{tool_backend:'native',args:[]});
});
test('file tools are not served in a robot_only run',async()=>{
  const h=host(()=>({}));
  for(const tool of ['policy_exec','policy_image','shell','apply_patch'])
    await assert.rejects(h.toolRequest('item/tool/call',{threadId:'thread',tool,arguments:{command:'pwd',path:'x'}}),/Unsupported host tool/);
});
test('public_file text is returned beside the result as it is',async()=>{
  const h=host(()=>({call_id:'c1',public_file:{path:'public/inputs/rules.md',kind:'text',text:'# Rules\n"quoted" line\n'}}));
  const result=await call(h,'public_file',{path:'rules.md'});
  assert.equal(result.success,true);
  assert.deepEqual(result.contentItems.map(item=>item.type),['inputText','inputText']);
  assert.equal(result.contentItems[1].text,'# Rules\n"quoted" line\n');
  assert.equal('text' in JSON.parse(result.contentItems[0].text).public_file,false);
});
test('a public_file image is returned as an image, and never from outside public',async()=>{
  let h=host(run=>({public_file:{path:'public/inputs/target.png',kind:'image',image:path.join(run,'public/inputs/target.png')}}));
  let result=await call(h,'public_file',{path:'target.png'});
  assert.equal(result.contentItems[1].type,'inputImage');
  assert.equal(result.contentItems[1].imageUrl,'data:image/png;base64,'+PNG.toString('base64'));
  h=host(run=>({public_file:{path:'x',kind:'image',image:path.join(run,'private/secret.png')}}));
  result=await call(h,'public_file',{path:'x'});
  assert.deepEqual(result.contentItems.map(item=>item.type),['inputText','inputText']);
  assert.match(result.contentItems[1].text,/could not be loaded/);
});
test('other results are unchanged',async()=>{
  const h=host(()=>({call_id:'c1',ready:true}));
  const result=await call(h,'ready');
  assert.deepEqual(result.contentItems,[{type:'inputText',text:JSON.stringify({call_id:'c1',ready:true})}]);
});
