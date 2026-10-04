import {reserveWriteBudget,settleWriteBudget,pendingWriteBudget} from './write-budget.mjs';
/* Dated, immutable published-list ranks. Active availability is not inferred. */
const HASH=/^[a-f0-9]{64}$/, ID=/^[a-f0-9]{32}$/;
const fold=value=>value.normalize('NFKD').replace(/\p{M}/gu,'').toUpperCase().replace(/\s+/g,' ').trim();
const validText=(value,max=180)=>typeof value==='string' && value.length>0 && value.length<=max && !/[\u0000-\u001f]/.test(value);
const invalid=()=>{throw Object.assign(new Error('Datos de consulta no válidos.'),{status:400});};
const FUNCTION=/^\d{4}[\dA-Z]\d{2}$/;
const ISO_DATE=/^\d{4}-\d{2}-\d{2}$/;
const date=value=>typeof value==='string'&&ISO_DATE.test(value)&&Number.isFinite(Date.parse(value+'T00:00:00Z'))&&new Date(value+'T00:00:00Z').toISOString().slice(0,10)===value;
function specialtyCounts(items){
  if(!Array.isArray(items)||!items.length||items.length>1000)invalid();
  const seen=new Set();
  return items.map(s=>{
    if(!(FUNCTION.test(s.code)||s.code==='0597')||seen.has(s.code)||!validText(s.name)||!validText(s.body)||!Number.isInteger(s.count)||s.count<1)invalid();
    if(s.code==='0597'&&(s.name!=='Lista única de Maestros'||s.body!=='CUERPO DE MAESTROS'))invalid();
    seen.add(s.code);return {code:s.code,name:s.name,body:s.body,count:s.count};
  });
}
function officialDocument(value,id){
  let u;try{u=new URL(value);}catch{invalid();}
  if(u.protocol!=='https:'||u.hostname!=='www.carm.es'||u.port||u.username||u.password||u.pathname!=='/web/descarga'||u.searchParams.get('IDCONTENIDO')!==id)invalid();
  return u.href;
}

async function jsonBody(request,limit){
  if(request.headers.get('Content-Type')?.split(';')[0] !== 'application/json') invalid();
  const reader=request.body?.getReader(); if(!reader)invalid();
  const parts=[];let size=0;
  try {while(true){const {done,value}=await reader.read();if(done)break;size+=value.length;if(size>limit)invalid();parts.push(value);}}
  finally {await reader.cancel().catch(()=>{});}
  try {const value=JSON.parse(new TextDecoder().decode(await new Blob(parts).arrayBuffer()));
    if(!value || typeof value!=='object' || Array.isArray(value))invalid();return value;
  } catch {invalid();}
}

function validateVersion(v){
  if(v?.parser_revision!==undefined&&!validText(v.parser_revision,80))invalid();
  if(v?.course!==undefined&&(typeof v.course!=='string'||!/^\d{4}[\/-]\d{4}$/.test(v.course)))invalid();
  if(!v || !HASH.test(v.id) || !HASH.test(v.sha256) || !/^\d{4}-\d{2}-\d{2}$/.test(v.published_at) ||
    (v.checked_at!==null&&!Number.isFinite(Date.parse(v.checked_at))) || !Number.isInteger(v.row_count) || v.row_count<1 || v.row_count>100000 ||
    v.scope!=='published_list' || !['baseline_only','reviewed_amendments','multi_source'].includes(v.coverage)) invalid();
  let url;try{url=new URL(v.source_url);}catch{invalid();}
  if(url.protocol!=='https:' || url.hostname!=='www.carm.es' || url.port || url.username || url.password || url.pathname!=='/web/descarga')invalid();
  const amendments=[];
  if(v.coverage==='baseline_only'){if(v.amendments?.length||(v.id!==v.sha256&&(!v.parser_revision||!v.course)))invalid();}
  else if(v.coverage==='reviewed_amendments'||v.amendments?.length){
    if(!Array.isArray(v.amendments) || !v.amendments.length || v.amendments.length>10 || v.id===v.sha256)invalid();
    for(const a of v.amendments){
      let u;try{u=new URL(a.source_url);}catch{invalid();}
      if(!/^\d{1,10}$/.test(a.content_id)||a.content_id==='208095'||amendments.some(x=>x.content_id===a.content_id)||!HASH.test(a.sha256)||
        !/^\d{4}-\d{2}-\d{2}$/.test(a.signed_at)||!Number.isInteger(a.pages)||a.pages<1||a.pages>1200||
        u.protocol!=='https:'||u.hostname!=='www.carm.es'||u.port||u.username||u.password||u.pathname!=='/web/descarga'||u.searchParams.get('IDCONTENIDO')!==a.content_id)invalid();
      amendments.push({content_id:a.content_id,sha256:a.sha256,signed_at:a.signed_at,pages:a.pages,source_url:u.href});
    }
  }
  const specialties=specialtyCounts(v.specialties);
  const total=specialties.reduce((n,s)=>n+s.count,0);
  if(total!==v.row_count)invalid();
  let documents,ranked_specialties;
  if(v.coverage==='multi_source'){
    if(!Array.isArray(v.documents)||!v.documents.length||v.documents.length>100||v.id===v.sha256)invalid();
    ranked_specialties=specialtyCounts(v.ranked_specialties);
    if(ranked_specialties.some(s=>s.code==='0597'))invalid();
    const ids=new Set(['208095',...amendments.map(a=>a.content_id)]);
    documents=v.documents.map(d=>{
      if(!d||!/^\d{1,10}$/.test(d.content_id)||ids.has(d.content_id)||!['award','maestros_roster'].includes(d.kind)||!HASH.test(d.sha256)||
        !/^\d{4}-\d{2}-\d{2}$/.test(d.published_at)||!Number.isInteger(d.pages)||d.pages<1||d.pages>1200||
        !Number.isInteger(d.row_count)||d.row_count<1)invalid();
      if(d.course!==undefined&&(typeof d.course!=='string'||!/^\d{4}[\/-]\d{4}$/.test(d.course)))invalid();
      ids.add(d.content_id);const counts=specialtyCounts(d.specialties);
      if(counts.reduce((n,s)=>n+s.count,0)!==d.row_count)invalid();
      if(d.kind==='maestros_roster'&&(d.rank_scope!=='maestros_unique_list'||counts.length!==1||counts[0].code!=='0597'))invalid();
      if(d.kind==='award'&&counts.some(s=>s.code==='0597'))invalid();
      const reviewed=[];
      if(d.amendments!==undefined){
        if(d.kind!=='maestros_roster'||!Array.isArray(d.amendments)||d.amendments.length>10)invalid();
        for(const a of d.amendments){
          if(!/^\d{1,10}$/.test(a.content_id)||ids.has(a.content_id)||!HASH.test(a.sha256)||!date(a.signed_at)||!Number.isInteger(a.pages)||a.pages<1||a.pages>1200)invalid();
          ids.add(a.content_id);reviewed.push({content_id:a.content_id,sha256:a.sha256,signed_at:a.signed_at,pages:a.pages,source_url:officialDocument(a.source_url,a.content_id)});
        }
      }
      const aliases=d.assigned_function_groups||{};
      if(d.kind==='maestros_roster'&&aliases&&typeof aliases==='object'&&Object.keys(aliases).length)invalid();
      if(!aliases||typeof aliases!=='object'||Array.isArray(aliases)||Object.keys(aliases).length>100||Object.entries(aliases).some(([code,group])=>
        !/^\d{4}[A-Z0-9]{3}$/.test(code)||!counts.some(s=>s.code===group)))invalid();
      return {content_id:d.content_id,kind:d.kind,sha256:d.sha256,published_at:d.published_at,pages:d.pages,row_count:d.row_count,
        source_url:officialDocument(d.source_url,d.content_id),specialties:counts,...(d.course?{course:d.course}:{}),...(d.kind==='maestros_roster'?{rank_scope:'maestros_unique_list',...(reviewed.length?{amendments:reviewed}:{})}:{}),...(Object.keys(aliases).length?{assigned_function_groups:aliases}:{})};
    });
    const totals=new Map();
    for(const s of [...ranked_specialties,...documents.flatMap(d=>d.specialties)])totals.set(s.code,(totals.get(s.code)||0)+s.count);
    if(totals.size!==specialties.length||specialties.some(s=>s.count!==totals.get(s.code)))invalid();
  }else if(v.documents?.length||v.ranked_specialties)invalid();
  return {id:v.id,sha256:v.sha256,published_at:v.published_at,checked_at:v.checked_at,source_url:url.href,
    row_count:v.row_count,scope:v.scope,coverage:v.coverage,...(v.parser_revision?{parser_revision:v.parser_revision}:{}),...(v.course?{course:v.course}:{}),...(amendments.length?{amendments}:{}),specialties,
    ...(documents?{documents,ranked_specialties}:{})};
}

function validateRow(r,v){
  if(r?.membership_id!==undefined&&!ID.test(r.membership_id))invalid();
  const document=v.documents?.find(d=>d.content_id===(r?.roster_id||r?.source_id));
  if(document?.kind==='maestros_roster'){
    const amendment=document.amendments?.find(a=>a.content_id===r.source_id),specialty=document.specialties[0];
    if(r.roster_id!==document.content_id||(r.source_id!==document.content_id&&!amendment)||r.record_type!=='list'||r.specialty!=='0597'||r.rank_scope!=='maestros_unique_list'||!ID.test(r.id)||!/^\d{7,8}$/.test(r.list_number)||!validText(r.name)||!Number.isInteger(r.rank)||r.rank<1||r.rank>specialty.count||!Number.isInteger(r.page)||r.page<1||r.page>(amendment?.pages||document.pages)||!Array.isArray(r.habilitations)||r.habilitations.length>100)invalid();
    const seen=new Set(), habilitations=r.habilitations.map(h=>{
      if(!h||!/^(?:03[1-9]|59703[1-9]|059703[1-9])$/.test(h.code)||seen.has(h.code.slice(-3))||!validText(h.name))invalid();
      seen.add(h.code.slice(-3));return {code:h.code,name:h.name};
    });
    const habilitations_status=r.habilitations_status||(habilitations.length?'published':'not_stated');
    if(!['published','not_stated'].includes(habilitations_status)||(habilitations_status==='not_stated'&&habilitations.length))invalid();
    if(r.baseline_page!==undefined&&(!Number.isInteger(r.baseline_page)||r.baseline_page<1||r.baseline_page>document.pages))invalid();
    if(!['I','II'].includes(r.block)||!validText(r.block_name))invalid();
    let amendment_relation;
    if(r.amendment_relation!==undefined){
      const a=r.amendment_relation;
      if(!amendment||!a||!['inclusion','habilitation_added'].includes(a.kind))invalid();
      if(a.kind==='inclusion'){
        if(a.previous_id!==null||a.previous_list_number!==null)invalid();
        amendment_relation={kind:a.kind,previous_id:null,previous_list_number:null};
      }else{
        if(!ID.test(a.previous_id)||a.previous_id!==r.id||a.previous_list_number!==r.list_number||a.baseline_source_id!==document.content_id||!Number.isInteger(a.baseline_page)||a.baseline_page<1||a.baseline_page>document.pages||a.baseline_page!==r.baseline_page||!/^03[1-9]$/.test(a.code)||!habilitations.some(h=>h.code===a.code)||!['597'+a.code,'0597'+a.code].includes(a.published_code))invalid();
        amendment_relation={kind:a.kind,previous_id:a.previous_id,previous_list_number:a.previous_list_number,baseline_source_id:a.baseline_source_id,baseline_page:a.baseline_page,code:a.code,published_code:a.published_code};
      }
    }
    return {id:r.id,specialty:'0597',specialty_name:specialty.name,body_name:specialty.body,name:r.name,list_number:r.list_number,rank:r.rank,record_type:'list',rank_scope:'maestros_unique_list',habilitations,habilitations_status,block:r.block,block_name:r.block_name,roster_id:document.content_id,source_id:r.source_id,page:r.page,...(r.membership_id?{membership_id:r.membership_id}:{}),...(amendment_relation?{amendment_relation}:{}),...(r.baseline_page?{baseline_page:r.baseline_page}:{})};
  }
  if(document){
    const specialty=document.specialties.find(s=>s.code===r?.specialty);
    if(!specialty||r.record_type!=='award'||r.rank!==null||!ID.test(r.id)||!/^\d{7,8}$/.test(r.list_number)||
      !validText(r.name)||!validText(r.destination,300)||!validText(r.workload,80)||!Number.isInteger(r.page)||r.page<1||r.page>document.pages)invalid();
    if(r.incorporation_at!==undefined&&!date(r.incorporation_at))invalid();
    if(r.appointment_status!==undefined&&!['definitive','provisional'].includes(r.appointment_status))invalid();
    const assigned=r.assigned_function||r.specialty;
    if(assigned!==r.specialty&&document.assigned_function_groups?.[assigned]!==r.specialty)invalid();
    return {id:r.id,specialty:r.specialty,specialty_name:specialty.name,body_name:specialty.body,name:r.name,list_number:r.list_number,
      page:r.page,source_id:document.content_id,record_type:'award',rank:null,block:'',block_name:'',destination:r.destination,workload:r.workload,assigned_function:assigned,...(r.incorporation_at?{incorporation_at:r.incorporation_at}:{}),...(r.appointment_status?{appointment_status:r.appointment_status}:{})};
  }
  const specialty=(v.ranked_specialties||v.specialties).find(s=>s.code===r?.specialty);
  const sourceId=r?.source_id||'208095', amendment=v.amendments?.find(a=>a.content_id===sourceId);
  if(sourceId!=='208095'&&!amendment)invalid();
  if(!r || (r.record_type&&r.record_type!=='list') || !ID.test(r.id) || !specialty || !/^\d{7,8}$/.test(r.list_number) || !/^\d{1,3}$/.test(r.block) ||
    !validText(r.name) || !validText(r.block_name) || !Number.isInteger(r.rank) || r.rank<1 || r.rank>specialty.count ||
    !Number.isInteger(r.page) || r.page<(amendment?1:2) || r.page>(amendment?amendment.pages:1200))invalid();
  // Whitelist fields: never accept masked DNI, scores or exclusion reasons.
  return {id:r.id,specialty:r.specialty,specialty_name:specialty.name,body_name:specialty.body,
    block:r.block,block_name:r.block_name,list_number:r.list_number,name:r.name,rank:r.rank,page:r.page,source_id:sourceId,...(r.membership_id?{membership_id:r.membership_id}:{})};
}

async function authorized(request,env){
  if(!env.POSITION_INGEST_TOKEN || env.POSITION_INGEST_TOKEN.length<40)return false;
  const value=request.headers.get('Authorization')||'';
  if(value.length>256)return false;
  const encoder=new TextEncoder();
  const digests=await Promise.all([value,'Bearer '+env.POSITION_INGEST_TOKEN].map(x=>crypto.subtle.digest('SHA-256',encoder.encode(x))));
  const a=new Uint8Array(digests[0]),b=new Uint8Array(digests[1]);let difference=0;
  for(let i=0;i<a.length;i++)difference|=a[i]^b[i];return difference===0;
}

export async function positionRoute(request,env,reply){
  const url=new URL(request.url), path=url.pathname;
  try{
    if(url.search)invalid();
    if(path==='/internal/positions' && !await authorized(request,env))return reply({error:'Acceso no autorizado.'},403);
    if(request.method==='OPTIONS')return reply(null,204);
    if(!env.DB)return reply({error:'La consulta aún no está disponible.'},503);
    const db=env.DB.withSession('first-primary');
    if(path==='/internal/positions'){
      if(request.method!=='POST')return reply({error:'Método no permitido.'},405);
      const body=await jsonBody(request,1_000_000);
      if(body.action==='begin'){
        const v=validateVersion(body.version);
        await db.prepare('INSERT OR IGNORE INTO position_versions(id,metadata) VALUES(?,?)').bind(v.id,JSON.stringify(v)).run();
        await db.prepare('INSERT OR IGNORE INTO position_search_status(version_id,ready) VALUES(?,1)').bind(v.id).run();
        const saved=await db.prepare('SELECT metadata,ready FROM position_versions WHERE id=?').bind(v.id).first();
        const stored=JSON.parse(saved.metadata);
        if(JSON.stringify({...stored,checked_at:null})!==JSON.stringify({...v,checked_at:null}))return reply({error:'Versión incompatible.'},409);
        return reply({id:v.id,ready:!!saved.ready});
      }
      if(!HASH.test(body.id))invalid();
      const saved=await db.prepare('SELECT metadata,ready FROM position_versions WHERE id=?').bind(body.id).first();
      if(!saved)return reply({error:'Versión desconocida.'},404);
      const v=JSON.parse(saved.metadata);
      const table=v.coverage==='multi_source'?'position_entries':'position_rows';
      if(body.action==='index'){
        const status=await db.prepare('SELECT ready,after_rowid FROM position_search_status WHERE version_id=?').bind(body.id).first();
        if(status?.ready)return reply({id:body.id,index_ready:true,indexed:0});
        const cursor=status?.after_rowid||0,markers=table+'_search_indexed';
        const rows=(await db.prepare(`SELECT rowid FROM ${table} WHERE version_id=? AND rowid>? ORDER BY rowid LIMIT 40`).bind(body.id,cursor).all()).results;
        if(!rows.length){
          await db.prepare('INSERT INTO position_search_status(version_id,ready,after_rowid) VALUES(?,1,?) ON CONFLICT(version_id) DO UPDATE SET ready=1').bind(body.id,cursor).run();
          await db.prepare(`UPDATE position_ingest_metrics SET updated_at=?,phase='search_ready',failure_status=NULL WHERE version_id=?`).bind(new Date().toISOString(),body.id).run();
          return reply({id:body.id,index_ready:true,indexed:0});
        }
        const reservation=await reserveWriteBudget(db,env,rows.length,7);
        if(!reservation)return reply({error:'El índice espera al presupuesto diario. Se conserva la generación anterior.',...await pendingWriteBudget(db)},429);
        const written=await db.batch([
          db.prepare(`INSERT OR IGNORE INTO ${markers}(row_id) SELECT rowid FROM ${table} WHERE rowid IN (${rows.map(()=>'?').join(',')}) AND EXISTS(SELECT 1 FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id WHERE r.id=? AND r.settled=0 AND l.expires_at>unixepoch('now'))`).bind(...rows.map(r=>r.rowid),reservation.id),
          db.prepare('INSERT INTO position_search_status(version_id,ready,after_rowid) SELECT ?,0,? WHERE EXISTS(SELECT 1 FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id WHERE r.id=? AND r.settled=0 AND l.expires_at>unixepoch(\'now\')) ON CONFLICT(version_id) DO UPDATE SET after_rowid=MAX(after_rowid,excluded.after_rowid)').bind(body.id,rows.at(-1).rowid,reservation.id)
        ]);
        const write_budget=await settleWriteBudget(db,reservation,written),actual=write_budget.batch_writes;
        if(write_budget.expired)return reply({error:'La reserva de escritura ha caducado. Repite la operación.',reservation_expired:true},409);
        await db.prepare(`INSERT INTO position_ingest_metrics(version_id,started_at,updated_at,phase,rows_written) VALUES(?,?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET updated_at=excluded.updated_at,phase=excluded.phase,failure_status=NULL,rows_written=position_ingest_metrics.rows_written+excluded.rows_written`).bind(body.id,new Date().toISOString(),new Date().toISOString(),'indexing',actual).run();
        return reply({id:body.id,index_ready:false,indexed:rows.length,write_budget});
      }
      if(body.action==='checked'){
        if(!saved.ready || !Number.isFinite(Date.parse(body.checked_at)))invalid();
        if(v.checked_at===null||Date.parse(body.checked_at)>Date.parse(v.checked_at)){
          v.checked_at=body.checked_at;
          await db.prepare('UPDATE position_versions SET metadata=? WHERE id=?').bind(JSON.stringify(v),body.id).run();
        }
        return reply({id:body.id,ready:true});
      }
      if(body.action==='status'||body.action==='metadata'){
        let progress={};
        if(body.action==='status'){
          if(body.after_id!==undefined&&!ID.test(body.after_id))invalid();
          const ids=(await db.prepare(`SELECT id FROM ${table} WHERE version_id=? AND id>? ORDER BY id LIMIT 41`).bind(body.id,body.after_id||'').all()).results;
          progress={existing_ids:ids.slice(0,40).map(r=>r.id),more:ids.length>40,next_id:ids.length>40?ids[39].id:null};
        }
        return reply({version:v,ready:!!saved.ready,active:!!await db.prepare('SELECT 1 FROM position_active WHERE singleton=1 AND version_id=?').bind(body.id).first(),...progress});
      }
      if(body.action==='rollback'){
        if(!(await db.prepare('SELECT ready FROM position_search_status WHERE version_id=?').bind(body.id).first())?.ready)return reply({error:'El índice de la generación aún no está preparado. Se conserva la anterior.',index_pending:true},409);
        if(!saved.ready)return reply({error:'Solo puede recuperarse una generación validada.'},409);
        const changed=await db.prepare('UPDATE position_active SET version_id=? WHERE singleton=1 AND EXISTS(SELECT 1 FROM position_versions WHERE id=? AND ready=1) AND EXISTS(SELECT 1 FROM position_search_status WHERE version_id=? AND ready=1)').bind(body.id,body.id,body.id).run();
        if(changed.meta?.changes===0)return reply({error:'La generación no está lista. Se conserva la anterior.',index_pending:true},409);
        return reply({id:body.id,ready:true});
      }
      if(body.action==='recover'){
        if(saved.ready)return reply({error:'La versión publicada es inmutable.'},409);
        const ids=(await db.prepare(`SELECT id FROM ${table} WHERE version_id=? ORDER BY id LIMIT 40`).bind(body.id).all()).results;
        if(!ids.length)return reply({id:body.id,ready:false,restart:true,more:false});
        const reservation=await reserveWriteBudget(db,env,ids.length);
        if(!reservation)return reply({error:'La recuperación espera al presupuesto diario.',...await pendingWriteBudget(db)},429);
        const result=await db.prepare(`DELETE FROM ${table} WHERE version_id=? AND id IN (${ids.map(()=>'?').join(',')}) AND EXISTS(SELECT 1 FROM position_versions WHERE id=? AND ready=0) AND EXISTS(SELECT 1 FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id WHERE r.id=? AND r.settled=0 AND l.expires_at>unixepoch('now'))`).bind(body.id,...ids.map(r=>r.id),body.id,reservation.id).run();
        const write_budget=await settleWriteBudget(db,reservation,[result]);
        if(write_budget.expired)return reply({error:'La reserva de escritura ha caducado. Repite la operación.',reservation_expired:true},409);
        const remaining=!!await db.prepare(`SELECT 1 FROM ${table} WHERE version_id=? LIMIT 1`).bind(body.id).first();
        return reply({id:body.id,ready:false,restart:!remaining,more:remaining});
      }
      if(saved.ready)return reply({error:'La versión publicada es inmutable.'},409);
      if(body.action==='rows'){
        if(!Array.isArray(body.rows) || !body.rows.length || body.rows.length>40)invalid();
        const rows=body.rows.map(r=>validateRow(r,v));
        const reservation=await reserveWriteBudget(db,env,rows.length);
        if(!reservation){
          await db.prepare(`INSERT INTO position_ingest_metrics(version_id,started_at,updated_at,phase,failure_status) VALUES(?,?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET updated_at=excluded.updated_at,phase=excluded.phase,failure_status=excluded.failure_status`).bind(body.id,new Date().toISOString(),new Date().toISOString(),'pending_budget','daily_write_cap').run();
          return reply({error:'Se ha alcanzado el presupuesto diario de ingesta. La generación anterior sigue activa.',...await pendingWriteBudget(db)},429);
        }
        const written=await db.batch(rows.map(r=>db.prepare(`INSERT OR IGNORE INTO ${table}
          (version_id,id,specialty,list_number,search_name,rank,payload)
          SELECT ?,?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM position_versions WHERE id=? AND ready=0) AND EXISTS(SELECT 1 FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id WHERE r.id=? AND r.settled=0 AND l.expires_at>unixepoch('now'))`)
          .bind(body.id,r.id,r.specialty,r.list_number,fold(r.name),r.rank,JSON.stringify(r),body.id,reservation.id)));
        const write_budget=await settleWriteBudget(db,reservation,written),actual=write_budget.batch_writes;
        if(write_budget.expired)return reply({error:'La reserva de escritura ha caducado. Repite la operación.',reservation_expired:true},409);
        await db.prepare(`INSERT INTO position_ingest_metrics(version_id,started_at,updated_at,phase,rows_written) VALUES(?,?,?,?,?)
          ON CONFLICT(version_id) DO UPDATE SET updated_at=excluded.updated_at,phase=excluded.phase,failure_status=NULL,rows_written=position_ingest_metrics.rows_written+excluded.rows_written`).bind(body.id,new Date().toISOString(),new Date().toISOString(),'staging',actual).run();
        return reply({accepted:rows.length,write_budget});
      }
      if(body.action==='activate'){
        if(!(await db.prepare('SELECT ready FROM position_search_status WHERE version_id=?').bind(body.id).first())?.ready)return reply({error:'El índice de la generación aún no está preparado. Se conserva la anterior.',index_pending:true},409);
        const failed=async(message,code)=>{await db.prepare(`INSERT INTO position_ingest_metrics(version_id,started_at,updated_at,phase,failure_status) VALUES(?,?,?,?,?) ON CONFLICT(version_id) DO UPDATE SET updated_at=excluded.updated_at,phase=excluded.phase,failure_status=excluded.failure_status`).bind(body.id,new Date().toISOString(),new Date().toISOString(),'validation_failed',code).run();return reply({error:message},409);};
        const snapshot=(await db.prepare('SELECT revision FROM position_staging_revisions WHERE version_id=?').bind(body.id).first())?.revision||0;
        const counts=v.ranked_specialties||v.specialties;
        const groups=(await db.prepare(`SELECT specialty,COUNT(*) AS n,MIN(rank) AS first,MAX(rank) AS last FROM ${table} WHERE version_id=? AND rank IS NOT NULL AND json_extract(payload,'$.roster_id') IS NULL GROUP BY specialty`).bind(body.id).all()).results;
        if(groups.length!==counts.length || counts.some(s=>!groups.some(g=>g.specialty===s.code && g.n===s.count && g.first===1 && g.last===s.count)))
          return failed('La extracción está incompleta. Se conserva la anterior.','baseline_counts');
        if(v.documents){
          const rosters=v.documents.filter(d=>d.kind==='maestros_roster');
          const rosterGroups=(await db.prepare(`SELECT json_extract(payload,'$.roster_id') AS roster_id,COUNT(*) AS n,MIN(rank) AS first,MAX(rank) AS last FROM ${table} WHERE version_id=? AND json_extract(payload,'$.roster_id') IS NOT NULL GROUP BY roster_id`).bind(body.id).all()).results;
          if(rosterGroups.length!==rosters.length||rosters.some(d=>!rosterGroups.some(g=>g.roster_id===d.content_id&&g.n===d.row_count&&g.first===1&&g.last===d.row_count)))return failed('La lista única de Maestros está incompleta. Se conserva la anterior.','maestros_counts');
          const awards=v.documents.filter(d=>d.kind==='award');
          const evidence=(await db.prepare(`SELECT json_extract(payload,'$.source_id') AS source_id,specialty,COUNT(*) AS n FROM ${table} WHERE version_id=? AND rank IS NULL GROUP BY source_id,specialty`).bind(body.id).all()).results;
          if(evidence.length!==awards.reduce((n,d)=>n+d.specialties.length,0)||awards.some(d=>d.specialties.some(s=>
            !evidence.some(g=>g.source_id===d.content_id&&g.specialty===s.code&&g.n===s.count))))
            return failed('Faltan registros de documentos revisados. Se conserva la anterior.','document_counts');
        }
        await db.batch([
          db.prepare(`UPDATE position_versions SET ready=1 WHERE id=? AND ready=0 AND (SELECT COUNT(*) FROM ${table} WHERE version_id=?)=? AND COALESCE((SELECT revision FROM position_staging_revisions WHERE version_id=?),0)=? AND EXISTS(SELECT 1 FROM position_search_status WHERE version_id=? AND ready=1)`).bind(body.id,body.id,v.row_count,body.id,snapshot,body.id),
          db.prepare('INSERT INTO position_active(singleton,version_id) SELECT 1,? WHERE EXISTS(SELECT 1 FROM position_versions WHERE id=? AND ready=1) AND EXISTS(SELECT 1 FROM position_search_status WHERE version_id=? AND ready=1) ON CONFLICT(singleton) DO UPDATE SET version_id=excluded.version_id').bind(body.id,body.id,body.id)
        ]);
        if(!(await db.prepare('SELECT ready FROM position_versions WHERE id=?').bind(body.id).first())?.ready)return failed('La generación cambió durante la validación. Repite la activación; se conserva la anterior.','concurrent_change');
        await db.prepare(`UPDATE position_ingest_metrics SET updated_at=?,phase='activated',failure_status=NULL WHERE version_id=?`).bind(new Date().toISOString(),body.id).run();
        return reply({id:body.id,ready:true});
      }
      invalid();
    }
    const active=await db.prepare('SELECT v.metadata,COALESCE(s.ready,0) AS search_ready FROM position_versions v JOIN position_active a ON a.version_id=v.id LEFT JOIN position_search_status s ON s.version_id=v.id WHERE a.singleton=1 AND v.ready=1').bind().first();
    if(!active)return reply({error:'La consulta aún no está disponible.'},503);
    const version=JSON.parse(active.metadata), specialties=version.specialties;
    const table=version.coverage==='multi_source'?'position_entries':'position_rows';
    delete version.specialties;
    if(path==='/api/positions' && request.method==='GET')return reply({version,specialties,search_ready:!!active.search_ready,refresh_available:!!env.GITHUB_TOKEN});
    if(path==='/api/positions/search' && request.method==='POST'){
      const body=await jsonBody(request,2048);
      const offset=body.offset??0;
      if(!Number.isInteger(offset)||offset<0||offset>=100000||offset%20)invalid();
      if(offset&&body.version_id!==version.id)return reply({error:'Las publicaciones han cambiado. Repite la búsqueda.'},409);
      if(!validText(body.query,100) || (body.specialty!==undefined && body.specialty!=='' && !specialties.some(s=>s.code===body.specialty)))invalid();
      if(!active.search_ready&&!/^\d{7,8}$/.test(fold(body.query)))return reply({error:'El índice de búsqueda se está preparando. Puedes consultar por número completo de lista.',index_pending:true},503);
      const query=fold(body.query), tokens=query.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
      if(query.replace(/[^\p{L}\p{N}]/gu,'').length<3 || tokens.length>6 || /[%_\\]/.test(query))invalid();
      const numeric=/^\d{7,8}$/.test(query);
      // Repeated surnames must occur twice; token order and accents do not matter.
      const counts=new Map();for(const t of tokens)counts.set(t,(counts.get(t)||0)+1);
      const condition=numeric?'list_number=?':[...counts].map(()=>'search_name LIKE ?').join(' AND ');
      const values=numeric?[query]:[...counts].map(([t,n])=>'%'+Array(n).fill(t).join('%')+'%');
      const scoped=Boolean(body.specialty);
      const cap=5000, fts=table+'_fts', longTokens=[...counts.keys()].filter(t=>[...t].length>=3);
      if(!numeric&&!longTokens.length)return reply({error:'Escribe al menos una parte del nombre de tres letras o el número completo de lista.'},400);
      let after=null;
      if(body.cursor!==undefined){
        if(typeof body.cursor!=='string'||body.cursor.length>1600)invalid();
        try{after=JSON.parse(new TextDecoder().decode(Uint8Array.from(atob(body.cursor),c=>c.charCodeAt(0))));}catch{invalid();}
        if(!after||typeof after!=='object'||Array.isArray(after))invalid();
        if(after.v!==1||after.g!==version.id||after.q!==query||after.s!==(body.specialty||''))return reply({error:'La búsqueda o publicación ha cambiado. Repite la búsqueda.'},409);
        if(!Array.isArray(after.k)||after.k.length!==(scoped?2:4)||!ID.test(after.k.at(-1)))invalid();
        if(scoped){if(!Number.isInteger(after.k[0])||after.k[0]<1||after.k[0]>2147483647)invalid();}
        else if(!validText(after.k[0])||typeof after.k[1]!=='string'||!specialties.some(s=>s.code===after.k[1])||!Number.isInteger(after.k[2])||after.k[2]<1||after.k[2]>2147483647)invalid();
      }
      const order=scoped?'COALESCE(rank,2147483647),id':'search_name,specialty,COALESCE(rank,2147483647),id';
      // Materialize a bounded candidate set BEFORE short/repeated-token filtering.
      // A 16-hex generation prefix intersects postings without evaluating a 64-character phrase.
      // The exact SQL version_id predicate always distinguishes prefix collisions.
      const match='version_id : "'+version.id.slice(0,16)+'" AND '+longTokens.map(t=>'search_name : "'+t+'"').join(' AND ');
      const candidateSQL=numeric?`SELECT * FROM ${table} WHERE version_id=? ${scoped?'AND specialty=?':''} AND list_number=? LIMIT ${cap+1}`:
        `SELECT p.* FROM ${fts} JOIN ${table} p ON p.rowid=${fts}.rowid WHERE ${fts} MATCH ? AND p.version_id=? ${scoped?'AND p.specialty=?':''} LIMIT ${cap+1}`;
      const candidateArgs=numeric?[version.id,...(scoped?[body.specialty]:[]),query]:[match,version.id,...(scoped?[body.specialty]:[])];
      const keyCondition=after?`AND (${order}) > (${after.k.map(()=>'?').join(',')})`:'';
      const sql=`WITH candidates AS MATERIALIZED (${candidateSQL}), bounded AS (SELECT COUNT(*) AS n FROM candidates)
        SELECT payload,search_name,specialty,rank,id FROM candidates WHERE (SELECT n FROM bounded)<=${cap} AND ${numeric?'1':condition}
        ${keyCondition} ORDER BY ${order} LIMIT 21 OFFSET ?`;
      const results=(await db.prepare(sql).bind(...candidateArgs,...(numeric?[]:values),...(after?after.k:[]),after?0:offset).all()).results;
      // A separate bounded count runs only for an empty page, never a full COUNT of names.
      if(!results.length){
        const count=await db.prepare(`SELECT COUNT(*) AS n FROM (${candidateSQL})`).bind(...candidateArgs).first();
        if(count.n>cap)return reply({error:'La búsqueda es demasiado amplia. Añade otro apellido, el nombre o elige una lista.',search_limit:cap},422);
      }
      const more=results.length>20, page=results.slice(0,20), last=page.at(-1);
      const next=more?{v:1,g:version.id,q:query,s:body.specialty||'',k:scoped?[last.rank??2147483647,last.id]:[last.search_name,last.specialty,last.rank??2147483647,last.id]}:null;
      const next_cursor=next?btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(next)))):null;
      return reply({version,results:page.map(r=>JSON.parse(r.payload)),more,next_offset:more?offset+20:null,next_cursor});
    }
    const match=path.match(/^\/api\/positions\/([a-f0-9]{32})$/);
    if(match && request.method==='GET'){
      const row=await db.prepare(`SELECT payload FROM ${table} WHERE version_id=? AND id=?`).bind(version.id,match[1]).first();
      return row?reply({version,person:JSON.parse(row.payload)}):reply({error:'Esta persona no figura en la publicación consultada.'},404);
    }
    return reply({error:'Recurso o método no permitido.'},404);
  }catch(error){return reply({error:error.status===400?error.message:'No se ha podido consultar la lista.'},error.status||503);}
}
