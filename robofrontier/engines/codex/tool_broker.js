// The host binds every file operation to its own run and an authenticated role.
const fs=require('node:fs'),path=require('node:path'),{spawn}=require('node:child_process');
const {requireNoMcpServers}=require('./codex_rpc');
const tools=[
  {type:'function',name:'policy_exec',description:'Run a shell command within your run file permissions. Read public inputs and edit workspace notes. No network access. Commands time out after at most 60 seconds.',
   inputSchema:{type:'object',properties:{command:{type:'string'},timeout_s:{type:'number',minimum:1,maximum:60}},required:['command'],additionalProperties:false}},
  {type:'function',name:'policy_image',description:'View a permitted PNG or JPEG by absolute path or relative to the run workspace. File access is enforced inside the isolated worker.',
   inputSchema:{type:'object',properties:{path:{type:'string'}},required:['path'],additionalProperties:false}}
];
function enabled(launch){return (launch.tool_backend??launch.profile?.tool_backend??'native')==='landlock-v1';}
// A robot_only run (runtime/tool_mode.py): Codex's own tools are off and no file tools replace them.
function robotOnly(launch){return (launch.tool_mode??launch.profile?.tool_mode??'full')==='robot_only';}
function subscription(launch){return (launch.profile?.provider??launch.provider)==='openai';}
async function admit(rpc,launch){
  if(!enabled(launch)&&!robotOnly(launch))return;
  await requireNoMcpServers(rpc);
  const {config}=await rpc.call('config/read',{});
  const flags=['shell_tool','view_image','shell_snapshot','unified_exec','apps','goals','plugins',
    'browser_use','browser_use_external','browser_use_full_cdp_access','computer_use',
    'code_mode','code_mode_only','code_mode_host','multi_agent','multi_agent_v2'];
  const overrides=new Map();
  for(let n=0;n<launch.args.length-1;n++)if(launch.args[n]==='-c'){
    const value=launch.args[++n],split=value.indexOf('=');
    overrides.set(value.slice(0,split),value.slice(split+1));
  }
  // config/read omits this experimental tools field in CLI 0.165.0. Its
  // process override is pinned here and its actual absence is tested offline.
  if(!config||flags.some(k=>config.features?.[k]!==false)||config.agents?.enabled!==false||
      overrides.get('tools.experimental_request_user_input.enabled')!=='false')
    throw new Error('Codex broker native tool configuration is not restricted');
  if(overrides.get('model_catalog_json')!==JSON.stringify(launch.model_catalog))throw new Error('Missing pinned broker model catalog');
  const models=JSON.parse(fs.readFileSync(launch.model_catalog)).models;
  if(models.length!==1||models[0].slug!==launch.model||models[0].apply_patch_tool_type!==null||
      models[0].multi_agent_version!=='disabled'||models[0].node_repl_disabled!==true||
      models[0].tool_mode!==null||models[0].experimental_supported_tools?.length!==0)
    throw new Error('Codex broker model metadata is not restricted');
  if(enabled(launch)&&subscription(launch)){
    const account=await rpc.call('account/read',{refreshToken:false});
    if(account.account?.type!=='chatgpt')throw new Error('Codex subscription broker requires native ChatGPT authentication');
  }
}
function call(run,python,tool,args){
  if(!args||typeof args!=='object'||Array.isArray(args))throw new Error('Invalid file tool arguments');
  const allowed=tool==='policy_exec'?['command','timeout_s']:tool==='policy_image'?['path']:[];
  if(!allowed.length||Object.keys(args).some(k=>!allowed.includes(k)))throw new Error('Unsupported file tool');
  const value=tool==='policy_exec'?args.command:args.path;
  if(typeof value!=='string'||!value.length||Buffer.byteLength(value)>131000)throw new Error('Invalid file tool input');
  const timeout=tool==='policy_exec'?(args.timeout_s??30):15;
  if(!Number.isFinite(timeout)||timeout<1||timeout>60)throw new Error('Invalid file tool timeout');
  const payload=tool==='policy_exec'?{tool,command:value}:{tool,path:value};
  return new Promise((resolve,reject)=>{
    const child=spawn(python,['-I','-m','robofrontier.engines.codex.tool_worker','--run-dir',run],
      {cwd:path.join(run,'workspace'),env:{PATH:process.env.PATH??'/usr/bin:/bin',LANG:'C.UTF-8'},
       stdio:['pipe','pipe','pipe'],detached:true});
    let stdout=[],stderr=[],size=0,limited=false,timedOut=false;
    const kill=()=>{try{process.kill(-child.pid,'SIGKILL');}catch{}};
    const timer=setTimeout(()=>{timedOut=true;kill();},timeout*1000);
    child.on('error',error=>{clearTimeout(timer);reject(error);});
    for(const [stream,chunks]of [[child.stdout,stdout],[child.stderr,stderr]])stream.on('data',data=>{
      size+=data.length;if(size>12*1024*1024){limited=true;kill();}else chunks.push(data);
    });
    child.stdin.on('error',()=>{});child.stdin.end(JSON.stringify(payload));
    child.on('close',(code,signal)=>{
      clearTimeout(timer);kill(); // Reap background descendants, including after a normal shell exit.
      if(limited||timedOut){resolve({success:false,contentItems:[{type:'inputText',text:limited?'File tool output limit exceeded.':'File tool timed out; inspect existing workspace state before retrying.'}]});return;}
      const out=Buffer.concat(stdout).toString('utf8'),err=Buffer.concat(stderr).toString('utf8');
      if(tool==='policy_image'&&code===0){
        try{const image=JSON.parse(out);
          if(!['image/png','image/jpeg'].includes(image.mime)||typeof image.data!=='string')throw new Error('Invalid image');
          resolve({success:true,contentItems:[{type:'inputImage',imageUrl:'data:'+image.mime+';base64,'+image.data}]});
        }catch{reject(new Error('Invalid isolated image response'));}
      }else resolve({success:code===0,contentItems:[{type:'inputText',text:JSON.stringify({exit_code:code,signal,stdout:out,stderr:err})}]});
    });
  });
}
module.exports={tools,enabled,robotOnly,subscription,admit,call};
