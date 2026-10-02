/* Dated, immutable published-list ranks. Active availability is not inferred. */
const HASH=/^[a-f0-9]{64}$/, ID=/^[a-f0-9]{32}$/;
const fold=value=>value.normalize('NFKD').replace(/\p{M}/gu,'').toUpperCase().replace(/\s+/g,' ').trim();
const validText=(value,max=180)=>typeof value==='string' && value.length>0 && value.length<=max && !/[\u0000-\u001f]/.test(value);
const invalid=()=>{throw Object.assign(new Error('Datos de consulta no válidos.'),{status:400});};
const FUNCTION=/^\d{4}[\dA-Z]\d{2}$/;
function specialtyCounts(items){
  if(!Array.isArray(items)||!items.length||items.length>1000)invalid();
  const seen=new Set();
  return items.map(s=>{
    if(!FUNCTION.test(s.code)||seen.has(s.code)||!validText(s.name)||!validText(s.body)||!Number.isInteger(s.count)||s.count<1)invalid();
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
  if(!v || !HASH.test(v.id) || !HASH.test(v.sha256) || !/^\d{4}-\d{2}-\d{2}$/.test(v.published_at) ||
    !Number.isFinite(Date.parse(v.checked_at)) || !Number.isInteger(v.row_count) || v.row_count<1 || v.row_count>100000 ||
    v.scope!=='published_list' || !['baseline_only','reviewed_amendments','multi_source'].includes(v.coverage)) invalid();
  let url;try{url=new URL(v.source_url);}catch{invalid();}
  if(url.protocol!=='https:' || url.hostname!=='www.carm.es' || url.port || url.username || url.password || url.pathname!=='/web/descarga')invalid();
  const amendments=[];
  if(v.coverage==='baseline_only'){if(v.id!==v.sha256 || v.amendments?.length)invalid();}
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
    const ids=new Set(['208095',...amendments.map(a=>a.content_id)]);
    documents=v.documents.map(d=>{
      if(!/^\d{1,10}$/.test(d.content_id)||ids.has(d.content_id)||d.kind!=='award'||!HASH.test(d.sha256)||
        !/^\d{4}-\d{2}-\d{2}$/.test(d.published_at)||!Number.isInteger(d.pages)||d.pages<1||d.pages>1200||
        !Number.isInteger(d.row_count)||d.row_count<1)invalid();
      ids.add(d.content_id);const counts=specialtyCounts(d.specialties);
      if(counts.reduce((n,s)=>n+s.count,0)!==d.row_count)invalid();
      const aliases=d.assigned_function_groups||{};
      if(!aliases||typeof aliases!=='object'||Array.isArray(aliases)||Object.keys(aliases).length>100||Object.entries(aliases).some(([code,group])=>
        !/^\d{4}[A-Z0-9]{3}$/.test(code)||!counts.some(s=>s.code===group)))invalid();
      return {content_id:d.content_id,kind:d.kind,sha256:d.sha256,published_at:d.published_at,pages:d.pages,row_count:d.row_count,
        source_url:officialDocument(d.source_url,d.content_id),specialties:counts,...(Object.keys(aliases).length?{assigned_function_groups:aliases}:{})};
    });
    const totals=new Map();
    for(const s of [...ranked_specialties,...documents.flatMap(d=>d.specialties)])totals.set(s.code,(totals.get(s.code)||0)+s.count);
    if(totals.size!==specialties.length||specialties.some(s=>s.count!==totals.get(s.code)))invalid();
  }else if(v.documents?.length||v.ranked_specialties)invalid();
  return {id:v.id,sha256:v.sha256,published_at:v.published_at,checked_at:v.checked_at,source_url:url.href,
    row_count:v.row_count,scope:v.scope,coverage:v.coverage,...(amendments.length?{amendments}:{}),specialties,
    ...(documents?{documents,ranked_specialties}:{})};
}

function validateRow(r,v){
  const document=v.documents?.find(d=>d.content_id===r?.source_id);
  if(document){
    const specialty=document.specialties.find(s=>s.code===r?.specialty);
    if(!specialty||r.record_type!=='award'||r.rank!==null||!ID.test(r.id)||!/^\d{7,8}$/.test(r.list_number)||
      !validText(r.name)||!validText(r.destination,300)||!validText(r.workload,80)||!Number.isInteger(r.page)||r.page<1||r.page>document.pages)invalid();
    const assigned=r.assigned_function||r.specialty;
    if(assigned!==r.specialty&&document.assigned_function_groups?.[assigned]!==r.specialty)invalid();
    return {id:r.id,specialty:r.specialty,specialty_name:specialty.name,body_name:specialty.body,name:r.name,list_number:r.list_number,
      page:r.page,source_id:document.content_id,record_type:'award',rank:null,block:'',block_name:'',destination:r.destination,workload:r.workload,assigned_function:assigned};
  }
  const specialty=(v.ranked_specialties||v.specialties).find(s=>s.code===r?.specialty);
  const sourceId=r?.source_id||'208095', amendment=v.amendments?.find(a=>a.content_id===sourceId);
  if(sourceId!=='208095'&&!amendment)invalid();
  if(!r || (r.record_type&&r.record_type!=='list') || !ID.test(r.id) || !specialty || !/^\d{7,8}$/.test(r.list_number) || !/^\d{1,3}$/.test(r.block) ||
    !validText(r.name) || !validText(r.block_name) || !Number.isInteger(r.rank) || r.rank<1 || r.rank>specialty.count ||
    !Number.isInteger(r.page) || r.page<(amendment?1:2) || r.page>(amendment?amendment.pages:1200))invalid();
  // Whitelist fields: never accept masked DNI, scores or exclusion reasons.
  return {id:r.id,specialty:r.specialty,specialty_name:specialty.name,body_name:specialty.body,
    block:r.block,block_name:r.block_name,list_number:r.list_number,name:r.name,rank:r.rank,page:r.page,source_id:sourceId};
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
      if(body.action==='checked'){
        if(!saved.ready || !Number.isFinite(Date.parse(body.checked_at)))invalid();
        if(Date.parse(body.checked_at)>Date.parse(v.checked_at)){
          v.checked_at=body.checked_at;
          await db.prepare('UPDATE position_versions SET metadata=? WHERE id=?').bind(JSON.stringify(v),body.id).run();
        }
        return reply({id:body.id,ready:true});
      }
      if(saved.ready)return reply({error:'La versión publicada es inmutable.'},409);
      if(body.action==='rows'){
        if(!Array.isArray(body.rows) || !body.rows.length || body.rows.length>40)invalid();
        const rows=body.rows.map(r=>validateRow(r,v));
        await db.batch(rows.map(r=>db.prepare(`INSERT OR IGNORE INTO ${table}
          (version_id,id,specialty,list_number,search_name,rank,payload)
          SELECT ?,?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM position_versions WHERE id=? AND ready=0)`)
          .bind(body.id,r.id,r.specialty,r.list_number,fold(r.name),r.rank,JSON.stringify(r),body.id)));
        return reply({accepted:rows.length});
      }
      if(body.action==='activate'){
        const counts=v.ranked_specialties||v.specialties;
        const groups=(await db.prepare(`SELECT specialty,COUNT(*) AS n,MIN(rank) AS first,MAX(rank) AS last FROM ${table} WHERE version_id=? AND rank IS NOT NULL GROUP BY specialty`).bind(body.id).all()).results;
        if(groups.length!==counts.length || counts.some(s=>!groups.some(g=>g.specialty===s.code && g.n===s.count && g.first===1 && g.last===s.count)))
          return reply({error:'La extracción está incompleta. Se conserva la anterior.'},409);
        if(v.documents){
          const evidence=(await db.prepare(`SELECT json_extract(payload,'$.source_id') AS source_id,specialty,COUNT(*) AS n FROM ${table} WHERE version_id=? AND rank IS NULL GROUP BY source_id,specialty`).bind(body.id).all()).results;
          if(evidence.length!==v.documents.reduce((n,d)=>n+d.specialties.length,0)||v.documents.some(d=>d.specialties.some(s=>
            !evidence.some(g=>g.source_id===d.content_id&&g.specialty===s.code&&g.n===s.count))))
            return reply({error:'Faltan registros de documentos revisados. Se conserva la anterior.'},409);
        }
        await db.batch([
          db.prepare('UPDATE position_versions SET ready=1 WHERE id=?').bind(body.id),
          db.prepare('INSERT INTO position_active(singleton,version_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET version_id=excluded.version_id').bind(body.id)
        ]);
        return reply({id:body.id,ready:true});
      }
      invalid();
    }
    const active=await db.prepare('SELECT v.metadata FROM position_versions v JOIN position_active a ON a.version_id=v.id WHERE a.singleton=1 AND v.ready=1').bind().first();
    if(!active)return reply({error:'La consulta aún no está disponible.'},503);
    const version=JSON.parse(active.metadata), specialties=version.specialties;
    const table=version.coverage==='multi_source'?'position_entries':'position_rows';
    delete version.specialties;
    if(path==='/api/positions' && request.method==='GET')return reply({version,specialties,refresh_available:!!env.GITHUB_TOKEN});
    if(path==='/api/positions/search' && request.method==='POST'){
      const body=await jsonBody(request,2048);
      const offset=body.offset??0;
      if(!Number.isInteger(offset)||offset<0||offset>=100000||offset%20)invalid();
      if(offset&&body.version_id!==version.id)return reply({error:'Las publicaciones han cambiado. Repite la búsqueda.'},409);
      if(!validText(body.query,100) || (body.specialty!==undefined && body.specialty!=='' && !specialties.some(s=>s.code===body.specialty)))invalid();
      const query=fold(body.query), tokens=query.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
      if(query.replace(/[^\p{L}\p{N}]/gu,'').length<3 || tokens.length>6 || /[%_\\]/.test(query))invalid();
      const numeric=/^\d{7,8}$/.test(query);
      // Repeated surnames must occur twice; token order and accents do not matter.
      const counts=new Map();for(const t of tokens)counts.set(t,(counts.get(t)||0)+1);
      const condition=numeric?'list_number=?':[...counts].map(()=>'search_name LIKE ?').join(' AND ');
      const values=numeric?[query]:[...counts].map(([t,n])=>'%'+Array(n).fill(t).join('%')+'%');
      const scoped=Boolean(body.specialty);
      const results=(await db.prepare(`SELECT payload FROM ${table} WHERE version_id=? ${scoped?'AND specialty=?':''} AND ${condition} ORDER BY ${scoped?'rank IS NULL,rank':'search_name,specialty,rank IS NULL,rank'},id LIMIT 21 OFFSET ?`)
        .bind(version.id,...(scoped?[body.specialty]:[]),...values,offset).all()).results;
      return reply({version,results:results.slice(0,20).map(r=>JSON.parse(r.payload)),more:results.length>20,next_offset:results.length>20?offset+20:null});
    }
    const match=path.match(/^\/api\/positions\/([a-f0-9]{32})$/);
    if(match && request.method==='GET'){
      const row=await db.prepare(`SELECT payload FROM ${table} WHERE version_id=? AND id=?`).bind(version.id,match[1]).first();
      return row?reply({version,person:JSON.parse(row.payload)}):reply({error:'Esta persona no figura en la publicación consultada.'},404);
    }
    return reply({error:'Recurso o método no permitido.'},404);
  }catch(error){return reply({error:error.status===400?error.message:'No se ha podido consultar la lista.'},error.status||503);}
}
