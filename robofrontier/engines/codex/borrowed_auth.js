// Access-only attachment to a live native credential owner. No OAuth client,
// refresh-token transfer, credential write, or fallback to API billing.
const fs=require('node:fs');
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function borrowedAuth(file){
  let owner,last;
  function read(){
    let fd;
    try{
      fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
      const info=fs.fstatSync(fd);
      if(!info.isFile()||info.uid!==process.getuid()||(info.mode&0o077)||info.nlink!==1||info.size>1048576)throw Error();
      const state=JSON.parse(fs.readFileSync(fd,'utf8')),auth=state.auth,tokens=auth.tokens;
      if(state.schema!=='robofrontier.codex-auth.v1'||auth.auth_mode!=='chatgpt'||auth.OPENAI_API_KEY)throw Error();
      const claims=JSON.parse(Buffer.from(tokens.access_token.split('.')[1],'base64url'));
      const identity=state.owner,key=JSON.stringify(identity);
      if(!identity?.subject||identity.account_id!==tokens.account_id||
         claims['https://api.openai.com/auth']?.chatgpt_account_id!==identity.account_id||
         !Number.isFinite(claims.exp)||claims.exp*1000<Date.now()+60000||owner&&owner!==key)throw Error();
      owner=key;
      return {accessToken:tokens.access_token,chatgptAccountId:tokens.account_id,
        ...(claims['https://api.openai.com/auth']?.chatgpt_plan_type?
          {chatgptPlanType:claims['https://api.openai.com/auth'].chatgpt_plan_type}:{})};
    }catch{throw new Error('Borrowed subscription access is unavailable or changed owner');}
    finally{if(fd!==undefined)fs.closeSync(fd);}
  }
  return {initial(){return last=read();},async refresh(p){
    if(p.reason!=='unauthorized'||p.previousAccountId&&p.previousAccountId!==last?.chatgptAccountId)
      throw new Error('Unexpected borrowed-access renewal request');
    const until=Date.now()+8000;
    do{
      const value=read();
      if(value.accessToken!==last.accessToken)return last=value;
      await delay(100);
    }while(Date.now()<until);
    throw new Error('The original native owner has not published renewed access');
  }};
}
module.exports={borrowedAuth};
