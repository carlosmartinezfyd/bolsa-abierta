const HOUR=3600000;
export function assessHealth(health,active,now){
 const issues=[],validTime=value=>Number.isFinite(Date.parse(value))&&Date.parse(value)<=now+60000;
 if(!health||!validTime(health.published_at))return {status:'unavailable',issues:['publication_unavailable'],needs_refresh:true};
 if(now-Date.parse(health.published_at)>90*60000)issues.push('publication_stale');
 if(!active||!validTime(health.checked_at)||now-Date.parse(health.checked_at)>90*60000)issues.push('position_stale');
 if(health.origin_check_complete!==true||health.position_status!=='verified')issues.push('origin_unverified');
 const mismatch=!active||health.active_version!==active.id||health.record_count!==active.row_count||Date.parse(health.checked_at)!==Date.parse(active.checked_at);
 if(mismatch)issues.push('publication_mismatch');
 if(health.run_status==='failed'||health.vacancy_status==='failed')issues.push('collection_failed');
 if(health.coverage_complete!==true||health.pending_documents||health.unavailable_documents||health.vacancy_status==='partial')issues.push('coverage_partial');
 if(health.cache_status!=='ready')issues.push('recovery_unavailable');
 // A short API -> Pages publication interval is observable, but not retried.
 const actionable=issues.filter(i=>!['coverage_partial','recovery_unavailable'].includes(i)&&
   (i!=='publication_mismatch'||now-Date.parse(health.published_at)>20*60000));
 return {status:actionable.length?'degraded':issues.length?'partial':'healthy',issues,needs_refresh:!!actionable.length};
}
async function readJSON(fetch,url,options={},limit=16384){
 const response=await fetch(url,{redirect:'manual',cache:'no-store',...options,signal:AbortSignal.timeout(10000)});
 if(!response.ok)throw new Error('Observation unavailable');
 const reader=response.body.getReader();let size=0,chunks=[];
 try{while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit)throw new Error('Observation oversized');chunks.push(value);}}
 finally{await reader.cancel().catch(()=>{});}
 return JSON.parse(await new Blob(chunks).text());
}
export function createWatchdog(dependencies={}){
 const fetch=dependencies.fetch||globalThis.fetch,now=dependencies.now||Date.now;
 return async function watchdog(controller,env){
  if(env.WATCHDOG_ENABLED!=='true')return {status:'disabled'};
  const db=env.DB.withSession('first-primary'),start=now(),day=new Date(start).toISOString().slice(0,10);
  const previous=await db.prepare('UPDATE gateway_watchdog SET lease_until=? WHERE singleton=1 AND lease_until<=? RETURNING *').bind(start+5*60000,start).first();
  if(!previous)return {status:'shared_observation'};
  await db.prepare(`DELETE FROM position_client_budget WHERE (day,client) IN
   (SELECT day,client FROM position_client_budget WHERE day<date('now','-7 days') LIMIT 100)`).bind().run();
  let report,health,active;
  try{
   if(dependencies.readPublished)health=await dependencies.readPublished();
   else{
    const url=new URL(env.SNAPSHOT_URL);
    if(url.protocol!=='https:'||url.hostname!=='carlosmartinezfyd.github.io'||url.pathname!=='/bolsa-abierta/data/state.json'||url.username||url.password)throw new Error('Invalid status URL');
    url.pathname='/bolsa-abierta/data/gateway-status.json';url.search='?watchdog='+start;
    health=(await readJSON(fetch,url.href)).health;
   }
   if(dependencies.readActive)active=await dependencies.readActive();
   else{const value=await db.prepare('SELECT v.metadata FROM position_versions v JOIN position_active a ON a.version_id=v.id WHERE a.singleton=1 AND v.ready=1').bind().first();active=value?JSON.parse(value.metadata):null;}
   report=assessHealth(health,active,start);
  }catch{report={status:'unavailable',issues:['observation_failed'],needs_refresh:true};}
  await db.prepare(`UPDATE gateway_watchdog SET observed_at=?,status=?,issues=?,
   first_failure=CASE WHEN ? THEN COALESCE(first_failure,?) ELSE NULL END,
   last_good=CASE WHEN ? THEN last_good ELSE ? END WHERE singleton=1`).bind(start,report.status,JSON.stringify(report.issues),report.needs_refresh?1:0,start,report.needs_refresh?1:0,start).run();
  let dispatchStatus='not_needed';
  const transient=report.status==='unavailable'&&!previous.first_failure;
  if(report.needs_refresh&&!transient&&previous.next_retry<=start&&(previous.day!==day||previous.retries<4)){
   try{
    let running;
    if(dependencies.isRunning)running=await dependencies.isRunning();
    else{
     if(env.GITHUB_REPOSITORY!=='carlosmartinezfyd/bolsa-abierta'||!env.GITHUB_TOKEN)throw new Error('Invalid dispatch configuration');
     running=false;
     // Completed/skipped runs cannot hide an older active run behind pagination.
     for(const status of ['queued','in_progress','waiting','requested','pending']){
      const runs=await readJSON(fetch,`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/refresh.yml/runs?per_page=1&branch=main&status=${status}`,{headers:{Authorization:'Bearer '+env.GITHUB_TOKEN,Accept:'application/vnd.github+json','User-Agent':'BolsaAbierta-Watchdog','X-GitHub-Api-Version':'2022-11-28'}},64000);
      if(!Array.isArray(runs.workflow_runs))throw new Error('Invalid workflow state');
      if(runs.workflow_runs.length){running=true;break;}
     }
    }
    if(running)dispatchStatus='workflow_active';
    else{
     // Reserve before sending; an uncertain response consumes the bounded attempt.
     await db.prepare(`UPDATE gateway_watchdog SET next_retry=?,retries=CASE WHEN day=? THEN retries+1 ELSE 1 END,day=? WHERE singleton=1`).bind(start+HOUR,day,day).run();
     const result=await dependencies.dispatch(controller,env,start);
     dispatchStatus=result.status==='failed'?'dispatch_failed':result.id?'requested':'dispatch_rejected';
     await db.prepare('UPDATE gateway_watchdog SET request_id=? WHERE singleton=1').bind(/^[a-f0-9]{32}$/.test(result.id||'')?result.id:null).run();
    }
   }catch{dispatchStatus='dispatch_unavailable';}
  }else if(report.needs_refresh)dispatchStatus=transient?'awaiting_confirmation':'retry_limited';
  await db.prepare('UPDATE gateway_watchdog SET dispatch_status=? WHERE singleton=1').bind(dispatchStatus).run();
  return {...report,dispatch_status:dispatchStatus};
 };
}
