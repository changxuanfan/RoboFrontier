// Bound task transport. Closing this client never terminates the shared engine.
const net=require('node:net'),readline=require('node:readline');
const {RpcError,STARTUP_ACK_MS}=require('./codex_rpc');
class GatewayRpc {
  constructor(endpoint,taskId,{onEvent=()=>{},onRequest,onExit=()=>{},recoveryNonce=process.env.ROBOFRONTIER_CODEX_RECOVERY_NONCE,
    pauseGraceMs=Number(process.env.ROBOFRONTIER_EGRESS_PAUSE_S||0)*1000}={}) {
    if(!Number.isFinite(pauseGraceMs)||pauseGraceMs<0||pauseGraceMs>600000)throw new Error('Invalid network pause grace');
    this.pauseGraceMs=pauseGraceMs;
    this.taskId=taskId;this.next=0;this.pending=new Map();this.onEvent=onEvent;this.recoveryNonce=recoveryNonce;
    this.socket=net.createConnection(endpoint);
    this.ready=new Promise((resolve,reject)=>{
      this.socket.once('connect',resolve);this.socket.once('error',reject);
    });
    const fail=()=>{
      if(this.closed)return;this.closed=true;
      for(const p of this.pending.values()) {clearTimeout(p.timer);p.reject(new Error('Shared Codex connection lost; mutations must not be repeated'));}
      this.pending.clear();if(!this.closing)onExit(null,'gateway-lost');
    };
    this.socket.on('error',fail);this.socket.on('close',fail);
    readline.createInterface({input:this.socket}).on('line',async line=>{
      let m;try{m=JSON.parse(line);}catch{return;}
      if(m.method&&m.id!==undefined) {
        try {
          if(!onRequest)throw new Error('Unsupported shared engine request');
          const result=await onRequest(m.method,m.params);this.write({id:m.id,result});
        }catch{this.write({id:m.id,error:{code:-32603,message:'Bound task tool request failed'}});}
      }else if(m.id!==undefined) {
        const p=this.pending.get(m.id);if(!p)return;
        this.pending.delete(m.id);clearTimeout(p.timer);
        if(m.error)p.reject(new RpcError(m.error));else p.resolve(m.result);
      }else onEvent(m);
    });
  }
  write(value){if(!this.closed)this.socket.write(JSON.stringify(value)+'\n');}
  call(method,params={},timeoutMs=30000){
    if(['thread/start','thread/fork','thread/resume','turn/start','thread/compact/start'].includes(method))timeoutMs+=this.pauseGraceMs;
    if(this.closed)return Promise.reject(new Error('Shared Codex connection closed'));
    const id=++this.next;
    return new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{this.pending.delete(id);reject(new Error(method+' acknowledgement unknown; do not repeat mutations'));},timeoutMs);
      this.pending.set(id,{resolve,reject,timer});this.write({id,method,params});
    });
  }
  async initialize(timeoutMs=STARTUP_ACK_MS){
    await this.ready;return this.call(this.recoveryNonce?'gateway/recover':'gateway/bind',
      {taskId:this.taskId,...(this.recoveryNonce?{nonce:this.recoveryNonce}:{})},timeoutMs);
  }
  async close(){
    this.closing=true;
    try{if(!this.closed)await this.call('gateway/release',{},45000);}
    finally{this.socket.destroy();}
  }
}
module.exports={GatewayRpc};
