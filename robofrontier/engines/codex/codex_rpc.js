// Codex CLI app-server transport. No inference until an explicit turn/start.
const {spawn} = require('node:child_process');
const readline = require('node:readline');

// Startup requests (initialize, session creation and naming) can answer slowly when many
// runs start at once. They happen before START, so a longer wait uses no task time.
const STARTUP_ACK_MS = 180000;
class RpcError extends Error {
  constructor(value) { super(value.message); this.detail = value; }
}
class CodexRpc {
  constructor(args = [], {stderr = 'ignore', onEvent = () => {}, onRequest, onExit = () => {}} = {}) {
    this.next = 0; this.pending = new Map(); this.onEvent = onEvent;
    this.process = spawn('codex', ['app-server', ...args, '--listen', 'stdio://'],
      {stdio:['pipe','pipe',stderr]});
    const fail = error => {
      for (const {reject,timer} of this.pending.values()) { clearTimeout(timer); reject(error); }
      this.pending.clear(); this.closed = true;
    };
    this.process.on('error', fail);
    this.process.on('exit', (code, signal) => {
      // onExit reports only an exit the host did not ask for.
      const unexpected = !this.closing; fail(new Error('Codex app-server exited: '+code));
      if (unexpected) onExit(code, signal);
    });
    readline.createInterface({input:this.process.stdout}).on('line', async line => {
      let message;
      try { message = JSON.parse(line); } catch { return; }
      if (message.method && message.id !== undefined) {
        try {
          if (!onRequest) throw new Error('Unsupported server request: '+message.method);
          const result = await onRequest(message.method, message.params);
          this.write({id:message.id,result});
        } catch (error) {
          this.write({id:message.id,error:{code:-32603,message:String(error.message)}});
        }
      } else if (message.id !== undefined) {
        const p = this.pending.get(message.id); if (!p) return;
        clearTimeout(p.timer); this.pending.delete(message.id);
        if (message.error) p.reject(new RpcError(message.error)); else p.resolve(message.result);
      } else this.onEvent(message);
    });
  }
  write(value) {
    if (!this.closed) this.process.stdin.write(JSON.stringify(value)+'\n');
  }
  call(method, params = {}, timeoutMs = 30000) {
    if (this.closed) return Promise.reject(new Error('Codex connection closed'));
    const id = ++this.next;
    return new Promise((resolve,reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new Error(method+' acknowledgement unknown; do not repeat mutations'));
      }, timeoutMs);
      this.pending.set(id,{resolve,reject,timer}); this.write({id,method,params});
    });
  }
  async initialize(timeoutMs = STARTUP_ACK_MS) {
    const result = await this.call('initialize',{
      clientInfo:{name:'robofrontier_cli',title:'RoboFrontier benchmark',version:'1.0'},
      capabilities:{experimentalApi:true}},timeoutMs);
    this.write({method:'initialized'}); return result;
  }
  async close() {
    this.closing = true;
    if (this.closed) return;
    const exited = new Promise(resolve => this.process.once('exit',resolve));
    this.process.kill('SIGTERM');
    const timer = setTimeout(() => this.process.kill('SIGKILL'),3000);
    await exited; clearTimeout(timer);
  }
}
function capacityFailure(error) {
  const text = typeof error === 'string' ? error : JSON.stringify(error);
  return /model[_ ]?capacity|capacity[_ ]?limit|rate[_ ]?limit|too many requests|\b429\b|overloaded|server[_ ]?overloaded|insufficient[_ ]?capacity/i.test(text)
    // A plan's usage limit lasts hours or days; retrying within a task cannot help.
    && !/insufficient[_ ]quota|billing|invalid[_ ]api[_ ]key|usage[_ ]limit|weekly[_ ]limit|monthly[_ ]limit/i.test(text);
}
// A plan's usage limit (runtime/quota.py LIMIT): the world pauses until it resets.
function usageLimitFailure(error) {
  const text = typeof error === 'string' ? error : JSON.stringify(error);
  return /you'?ve hit your (?:\w+ )?(?:usage )?limit|usage limit reached|usage[_ ]limit[_ ]exceeded|usageLimitExceeded|weekly limit|session limit/i.test(text||'');
}
function networkFailure(error){
  const info=error?.codexErrorInfo;
  if(!info||typeof info!=='object')return false;
  for(const kind of ['responseStreamDisconnected','httpConnectionFailed']){
    if(Object.hasOwn(info,kind))return info[kind]?.httpStatusCode==null;
  }
  return false;
}
async function requireNoMcpServers(rpc) {
  const result = await rpc.call('config/read',{});
  if (!result || !result.config || typeof result.config !== 'object')
    throw new Error('Native benchmark tool configuration could not be verified');
  const servers=result.config.mcp_servers || {};
  if (typeof servers !== 'object' || Array.isArray(servers) ||
      Object.values(servers).some(server=>!server || server.enabled!==false))
    throw new Error('Native benchmark requires inherited MCP servers to be disabled');
}
module.exports = {CodexRpc,RpcError,STARTUP_ACK_MS,capacityFailure,networkFailure,usageLimitFailure,requireNoMcpServers};
