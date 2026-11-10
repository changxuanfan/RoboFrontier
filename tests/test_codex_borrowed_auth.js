const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {borrowedAuth}=require('../robofrontier/engines/codex/borrowed_auth');
function fixture(t){
  const folder=fs.mkdtempSync(path.join(os.tmpdir(),'rf-access-'));t.after(()=>fs.rmSync(folder,{recursive:true,force:true}));
  const file=path.join(folder,'current.json');
  function write(generation=1,account='fixture-account',expiry=Date.now()/1000+3600){
    const claims={exp:expiry,generation,'https://api.openai.com/auth':{chatgpt_account_id:account,chatgpt_plan_type:'pro'}};
    fs.writeFileSync(file,JSON.stringify({schema:'robofrontier.codex-auth.v1',generation,owner:{subject:'fixture-user',account_id:account},
      auth:{auth_mode:'chatgpt',tokens:{account_id:account,access_token:'fixture.'+Buffer.from(JSON.stringify(claims)).toString('base64url')+'.fixture',refresh_token:'REFRESH_SECRET_NEVER_FORWARDED'}}}),{mode:0o600});
  }
  write();return {file,write,reader:borrowedAuth(file)};
}
test('access-only login and renewal return no refresh token or cached credentials',async t=>{
  const f=fixture(t),before=fs.readFileSync(f.file),initial=f.reader.initial();
  assert.equal(initial.chatgptAccountId,'fixture-account');assert.equal(initial.chatgptPlanType,'pro');
  assert.equal(JSON.stringify(initial).includes('REFRESH_SECRET'),false);assert.deepEqual(fs.readFileSync(f.file),before);
  f.write(2);const renewed=await f.reader.refresh({reason:'unauthorized',previousAccountId:'fixture-account'});
  assert.notEqual(renewed.accessToken,initial.accessToken);assert.equal(JSON.stringify(renewed).includes('REFRESH_SECRET'),false);
});
test('borrowed auth refuses owner changes, public files and expired access',async t=>{
  const f=fixture(t);f.reader.initial();f.write(2,'other-account');
  assert.throws(()=>f.reader.initial(),/unavailable or changed owner/);
  f.write();fs.chmodSync(f.file,0o644);assert.throws(()=>f.reader.initial());
  fs.chmodSync(f.file,0o600);f.write(1,'fixture-account',Date.now()/1000-10);assert.throws(()=>f.reader.initial());
});
