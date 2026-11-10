const test=require('node:test'),assert=require('node:assert/strict');
const {pendingForkActor}=require('../../robofrontier/engines/codex/codex_policy_host');

test('a new fork maps to the batch being created, never to a stale batch left for review',()=>{
  const snapshot={delegations:[
    {id:'old',status:'needs_review',children:[{actor:'Delegate-1',thread_id:null}]},
    {id:'done',status:'active',children:[{actor:'Delegate-2',thread_id:'t2'}]},
    {id:'new',status:'creating',children:[{actor:'Delegate-3',thread_id:'t3'},{actor:'Delegate-4',thread_id:null},
                                          {actor:'Delegate-5',thread_id:null}]}]};
  assert.equal(pendingForkActor(snapshot),'Delegate-4');
});
test('a fork with no batch being created, or with two, is refused',()=>{
  assert.throws(()=>pendingForkActor({delegations:[{status:'needs_review',children:[{actor:'D',thread_id:null}]}]}),
                /No pending runtime delegation/);
  const creating={status:'creating',children:[{actor:'D',thread_id:null}]};
  assert.throws(()=>pendingForkActor({delegations:[creating,creating]}),/More than one/);
});
