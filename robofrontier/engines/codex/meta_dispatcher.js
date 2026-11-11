// Loaded by Meta into functions.exec; definitions alone perform no I/O.
// It has no task planner and never selects robot actions or delegation scopes.
//
// Native session control goes through one adapter, so the same deterministic loop
// serves every engine:
//   observe({threadId,hostId,afterCursor}) -> {thread:{id,status:{type}},latestTurn:{id,status},cursor} | undefined
//   fork({threadId})                       -> {threadId,sourceThreadId,status:'created'}
//   send({threadId,model,thinking,prompt}) -> {threadId}
//   title({threadId,title})                -> {threadId}       (optional)
// An adapter throws on any rejected or unacknowledged operation.
function errorText(value) {
  return String(value)
    .replace(/Bearer\s+[^\s,;"']+/gi,'Bearer <redacted>')
    .replace(/\bsk-[A-Za-z0-9_-]+/g,'<redacted>')
    .replace(/((?:token|api[_-]?key|authorization|cookie)\s*[:=]\s*)(?:"[^"]*"|'[^']*'|[^\s,;]+)/gi,'$1<redacted>')
    .slice(0,2000);
}
// Adapter over the Codex app tools; the platform's JSON envelope is decoded here only.
function codexAdapter(tools) {
  function decode(result) {
    if (result.isError) throw new Error('Codex adapter rejected operation: '+errorText(
      result.content?.filter(c=>c.type==='text').map(c=>c.text).join('\n') || 'No platform error detail'));
    const text = result.content?.find(c => c.type === 'text')?.text;
    if (!text) throw new Error('Missing Codex adapter response');
    return JSON.parse(text);
  }
  const adapter = {
    observe: async params => decode(await tools.mcp__codex_app__wait_threads({targets:[{...params,hostId:'local'}],timeoutMs:0})).polls?.[0],
    fork: async params => decode(await tools.mcp__codex_app__fork_thread({...params,environment:{type:'same-directory'}})),
    send: async params => decode(await tools.mcp__codex_app__send_message_to_thread({...params,hostId:'local'})),
  };
  if (typeof tools.mcp__codex_app__set_thread_title === 'function')
    adapter.title = async params => decode(await tools.mcp__codex_app__set_thread_title(params));
  return adapter;
}
async function runMetaDispatcher({runDir, python, cwd, tools, adapter = codexAdapter(tools), onEvent = () => {}, stopRequested = () => false, maxCycles = Infinity, observationSource = 'codex.wait_threads', createSnapshot, owner: givenOwner = null}) {
  const quote = value => "'" + String(value).replaceAll("'", "'\\''") + "'";
  // A host that restarts its model process keeps one owner, so it keeps its scheduler lease.
  const owner = givenOwner || 'meta-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  const cursors = new Map();
  const failures = new Map();
  let statusPaused = false;
  async function runtime(op, data = {}) {
    const command = `${quote(python)} -m robofrontier.runtime.cli --run-dir ${quote(runDir)} --owner ${quote(owner)} ${op} --data ${quote(JSON.stringify(data))}`;
    const result = await tools.exec_command({cmd:command,workdir:cwd,max_output_tokens:12000});
    if (result.exit_code !== 0) throw new Error('Runtime operation failed: ' + op + ': ' + result.output);
    try { return JSON.parse(result.output); }
    catch { throw new Error('Incomplete runtime JSON; do not infer or restart sessions from this output'); }
  }
  async function labelFork(child) {
    if (typeof adapter.title !== 'function') return;
    const runName=String(runDir).split(/[\\/]/).filter(Boolean).pop();
    const title=`Fork [${child.robots.join('+')}] · ${child.actor.slice(-6)} · ${runName}`;
    let timer;
    try {
      const result=await Promise.race([
        adapter.title({threadId:child.thread_id,title}),
        new Promise((_,reject)=>{timer=setTimeout(()=>reject(new Error('Optional UI title deadline')),1500);})
      ]);
      if(result.threadId!==child.thread_id)throw new Error('Title acknowledgement mismatch');
      onEvent({event:'fork_named',actor:child.actor,thread_id:child.thread_id,robots:child.robots,title});
    } catch(error) {
      onEvent({event:'fork_title_unavailable',actor:child.actor,error:errorText(error)});
    } finally {clearTimeout(timer);}
  }
  async function observe(actor, agent) {
    const params = {threadId:agent.thread_id};
    if (cursors.has(actor)) params.afterCursor = cursors.get(actor);
    const p = await adapter.observe(params);
    if (!p) throw new Error('No authoritative session status for ' + actor);
    if (p.thread?.id && p.thread.id!==agent.thread_id) throw new Error('Status belongs to a different thread');
    const status = p.thread?.status?.type==='systemError'?'error':p.thread?.status?.type;
    if (!['idle','active','notLoaded','error','needsAttention'].includes(status)) throw new Error('Unrecognized native session status');
    if (p.cursor) cursors.set(actor,p.cursor);
    return {actor,thread_id:agent.thread_id,status,
            turn_id:p.latestTurn?.id ?? null,turn_status:p.latestTurn?.status ?? null,
            observed_at:Date.now()/1000,source:observationSource};
  }
  async function safeObserve(actor, agent) {
    let error;
    // Only repeat read-only observations. Never retry native creation or sends
    // whose acceptance is unknown.
    for (let attempt=0;attempt<2;attempt++) {
      try { const value=await observe(actor,agent);failures.delete(actor);return value; }
      catch (e) {error=errorText(e);cursors.delete(actor);}
    }
    const previous=failures.get(actor);
    const count=previous?.cycle===cycle?previous.count:(previous?.count??0)+1;
    failures.set(actor,{cycle,count});
    await runtime('session-unavailable',{actor,thread_id:agent.thread_id,reason:error});
    onEvent({event:'session_status_unavailable',actor,count,error});
    if (count>=3 && !statusPaused) {
      statusPaused=true;
      await runtime('pause',{reason:'Repeated native status unavailable',actor});
      onEvent({event:'dispatcher_paused_for_status',actor,error});
    }
    return null;
  }
  async function establishForks(snapshot) {
    for (const batch of snapshot.delegations ?? []) {
      if (batch.status !== 'creating') continue;
      if (batch.claimed_by !== null) {
        if (batch.claimed_by !== owner)
          await runtime('delegate-uncertain',{id:batch.id,reason:'Dispatcher changed during native creation; inspect existing forks before retrying'});
        continue;
      }
      const claimed = (await runtime('delegate-claim',{id:batch.id})).delegation;
      let activated = false;
      // Every native step of this batch shares the runtime setup deadline. Once it has
      // passed, or a stop arrives, no new creation is started; a step already sent is
      // never repeated, because its outcome may be unknown.
      const deadlineMs = Number(claimed.setup_deadline)*1000;
      const remainingMs = () => {
        if (stopRequested()) throw new Error('Stop requested during delegate setup');
        if (!Number.isFinite(deadlineMs)) return undefined;  // Runs recorded before the deadline existed.
        const left = deadlineMs-Date.now();
        if (left <= 0) throw new Error('Delegate setup deadline passed before native creation');
        return left;
      };
      try {
        let sourceThreadId = claimed.source_thread_id;
        if ((snapshot.config.engine || 'codex') === 'codex') {
          const anchor = await (createSnapshot || adapter.fork)({threadId:sourceThreadId,timeoutMs:remainingMs()});
          if (!anchor.threadId) throw new Error('Native snapshot response incomplete; creation outcome unknown');
          onEvent({event:'snapshot_created',thread_id:anchor.threadId,id:batch.id,verified:false});
          await runtime('delegate-snapshot-bind',{id:batch.id,thread_id:anchor.threadId});
          if (anchor.status!=='created' || anchor.sourceThreadId!==sourceThreadId)
            throw new Error('Native snapshot response inconsistent; known ID retained for review');
          sourceThreadId=anchor.threadId;
        }
        for (const child of claimed.children) {
          const fork = await adapter.fork({threadId:sourceThreadId,timeoutMs:remainingMs()});
          if (!fork.threadId)
            throw new Error('Native fork response incomplete; creation outcome unknown');
          child.thread_id = fork.threadId;
          onEvent({event:'fork_created',actor:child.actor,thread_id:fork.threadId,id:batch.id,verified:false});
          // The CLI checks the native parent pointer, exclusive ordinal and
          // prefix hash. It rejects a batch whose forks diverged at creation.
          await runtime('delegate-bind',{id:batch.id,actor:child.actor,thread_id:fork.threadId});
          if (fork.status!=='created' || fork.sourceThreadId!==sourceThreadId)
            throw new Error('Native response inconsistent; known ID retained for review');
        }
        await runtime('delegate-activate',{id:batch.id}); activated = true;
        for (const child of claimed.children) {
          // Runs prepared with policy_bootstrap.py freeze the delegate message; fill every
          // placeholder, as robofrontier/runtime/bootstrap.py delegate_prompt does.
          // Required here, not at load: Meta may load these definitions where no I/O is allowed.
          const fs = require('node:fs'), frozenDelegate = require('node:path').join(runDir,'private/inputs/bootstrap/delegate.md');
          const prompt = fs.existsSync(frozenDelegate) ? fs.readFileSync(frozenDelegate,'utf8').split('{{ACTOR}}').join(child.actor)
              .split('{{SCOPE}}').join(JSON.stringify({robots:child.robots,goal:child.goal,done_when:child.done_when,constraints:child.constraints||''})) :
            'Your current identity is temporary delegate '+child.actor+' for this task. This runtime authority replaces inherited parent-role identity, connection and team-finish permissions; shared task and evidence restrictions remain in force. The parent session\'s unfinished calls and plans are history: do not retry them or execute them for the parent.'+
            '\nThe task Controller submitted this scope verbatim: '+JSON.stringify({robots:child.robots,goal:child.goal,done_when:child.done_when,constraints:child.constraints??''})+
            '\nUse only your own connection '+runDir+'/private/state/connections/'+child.actor+'.json; Python '+python+'. Prefix future call IDs with '+child.actor+'; do not reuse parent call IDs.'+
            '\nYou are a temporary delegate, not a permanent per-arm Worker. Follow the frozen Skill\'s references/adaptive.md for lifecycle and handback rules; restore that reference if context is missing. The team has STARTED. Act independently within this scope, process parent messages, and report milestones or blockers when useful. On normal completion, call return_task and end. Follow the reference for waiting, pauses and incomplete handback. Do not create more sessions, use management APIs, modify the harness, read private evaluation or execute team finish.';
          try {
            const reply = await adapter.send({threadId:child.thread_id,
              model:snapshot.config.model,thinking:snapshot.config.effort,prompt});
            if (reply.threadId!==child.thread_id) throw new Error('Initial child input acceptance unknown');
            await runtime('delegate-started',{id:batch.id,actor:child.actor,outcome:'sent'});
            await labelFork(child);
          } catch (error) {
            const recorded=await runtime('delegate-started',{id:batch.id,actor:child.actor,outcome:'uncertain'});
            if (recorded.status==='needs_review') {
              onEvent({event:'fork_needs_review',id:batch.id,actor:child.actor,error:errorText(error)});break;
            }
          }
        }
      } catch (error) {
        await runtime('delegate-uncertain',{id:batch.id,reason:errorText(error)});
        onEvent({event:'fork_needs_review',id:batch.id,activated,error:errorText(error)});
      }
    }
  }
  let cycle = 0;
  while (cycle++ < maxCycles && !stopRequested()) {
    const snapshot = await runtime('snapshot');
    if(snapshot.egress_paused && !['ended','interrupted','recovery_required'].includes(snapshot.lifecycle)){
      onEvent({event:snapshot.egress_review_hold?'dispatcher_held_for_network_review':'dispatcher_waiting_for_network'});
      await new Promise(resolve=>setTimeout(resolve,snapshot.config.poll_interval_s*1000));
      continue;
    }
    if (['ended','interrupted','recovery_required'].includes(snapshot.lifecycle) || snapshot.paused) {
      onEvent({event:'dispatcher_stopped',lifecycle:snapshot.lifecycle,paused:snapshot.paused});
      return {lifecycle:snapshot.lifecycle,paused:!!snapshot.paused,cycles:cycle-1};
    }
    if (snapshot.lifecycle==='running') await establishForks(snapshot);
    // The host starts the run after binding its initial roles; a prepared run stays inert here.
    // Adaptive fork creation executes only the task Controller's durable, explicitly bounded
    // requests above.
    const policy = Object.entries(snapshot.agents).filter(([,a])=>a.kind!=='manager' && a.thread_id &&
      (a.kind!=='delegate'||a.delegation_state==='active'));
    const observations = (await Promise.all(policy.map(([actor,a])=>safeObserve(actor,a)))).filter(Boolean);
    if (observations.length) await runtime('observe-sessions',{observations,cycle});
    if (statusPaused) return {lifecycle:snapshot.lifecycle,paused:true,cycles:cycle};
    if (snapshot.lifecycle==='running') {
      for (const command of (await runtime('plan')).commands) {
        if (statusPaused) break;
        // Recheck immediately before claiming. The App API itself has no
        // compare-and-send primitive; exclusive experiment control is required.
        const fresh = await safeObserve(command.actor,snapshot.agents[command.actor]);
        if (!fresh) continue;
        await runtime('observe-sessions',{observations:[fresh]});
        const claimed = (await runtime('claim',{wake_id:command.wake_id})).command;
        if (!claimed) continue;
        try {
          const acknowledgement = await adapter.send({threadId:claimed.thread_id,
            model:snapshot.config.model,thinking:snapshot.config.effort,prompt:claimed.prompt});
          if (acknowledgement.threadId !== claimed.thread_id) throw new Error('Unexpected send acknowledgement; outcome unknown');
        } catch (error) {
          await runtime('dispatch-result',{wake_id:claimed.wake_id,outcome:'uncertain',result:{error:errorText(error)}});
          onEvent({event:'dispatch_uncertain',actor:claimed.actor,wake_id:claimed.wake_id});
          continue;
        }
        await runtime('dispatch-result',{wake_id:claimed.wake_id,outcome:'sent',result:{accepted:true}});
        onEvent({event:'wake_sent',actor:claimed.actor,wake_id:claimed.wake_id,reasons:claimed.reasons});
      }
    }
    if (statusPaused) return {lifecycle:snapshot.lifecycle,paused:true,cycles:cycle};
    onEvent({event:'cycle',cycle,lifecycle:snapshot.lifecycle});
    // The Meta tool cell stays alive; onEvent can yield output without ending
    // this loop. There is no model decision between polling cycles.
    await new Promise(resolve=>setTimeout(resolve,snapshot.config.poll_interval_s*1000));
  }
  return {lifecycle:'stopped_by_manager',cycles:cycle-1};
}
if (typeof module !== 'undefined') module.exports = {runMetaDispatcher, codexAdapter};
