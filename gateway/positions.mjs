/* Dated, immutable published-list ranks. Active availability is not inferred. */
const HASH=/^[a-f0-9]{64}$/, ID=/^[a-f0-9]{32}$/;
const fold=value=>value.normalize('NFKD').replace(/\p{M}/gu,'').toUpperCase().replace(/\s+/g,' ').trim();
const validText=(value,max=180)=>typeof value==='string' && value.length>0 && value.length<=max && !/[\u0000-\u001f]/.test(value);
const invalid=()=>{throw Object.assign(new Error('Datos de consulta no válidos.'),{status:400});};

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
  if(!v || !HASH.test(v.id) || v.id!==v.sha256 || !/^\d{4}-\d{2}-\d{2}$/.test(v.published_at) ||
    !Number.isFinite(Date.parse(v.checked_at)) || !Number.isInteger(v.row_count) || v.row_count<1 || v.row_count>100000 ||
    v.scope!=='published_list' || v.coverage!=='baseline_only' || !Array.isArray(v.specialties) ||
    !v.specialties.length || v.specialties.length>300) invalid();
  let url;try{url=new URL(v.source_url);}catch{invalid();}
  if(url.protocol!=='https:' || url.hostname!=='www.carm.es' || url.port || url.username || url.password || url.pathname!=='/web/descarga')invalid();
  const seen=new Set();let total=0;
  for(const s of v.specialties){
    if(!/^\d{7}$/.test(s.code) || seen.has(s.code) || !validText(s.name) || !validText(s.body) || !Number.isInteger(s.count) || s.count<1)invalid();
    total+=s.count;seen.add(s.code);
  }
  if(total!==v.row_count)invalid();
  return {id:v.id,sha256:v.sha256,published_at:v.published_at,checked_at:v.checked_at,source_url:url.href,
    row_count:v.row_count,scope:v.scope,coverage:v.coverage,specialties:v.specialties.map(s=>({code:s.code,name:s.name,body:s.body,count:s.count}))};
}

function validateRow(r,v){
  const specialty=v.specialties.find(s=>s.code===r?.specialty);
  if(!r || !ID.test(r.id) || !specialty || !/^\d{7,8}$/.test(r.list_number) || !/^\d{1,3}$/.test(r.block) ||
    !validText(r.name) || !validText(r.block_name) || !Number.isInteger(r.rank) || r.rank<1 || r.rank>specialty.count ||
    !Number.isInteger(r.page) || r.page<2 || r.page>1200)invalid();
  // Whitelist fields: never accept masked DNI, scores or exclusion reasons.
  return {id:r.id,specialty:r.specialty,specialty_name:specialty.name,body_name:specialty.body,
    block:r.block,block_name:r.block_name,list_number:r.list_number,name:r.name,rank:r.rank,page:r.page};
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
      const body=await jsonBody(request,160000);
      if(body.action==='begin'){
        const v=validateVersion(body.version);
        await db.prepare('INSERT OR IGNORE INTO position_versions(id,metadata) VALUES(?,?)').bind(v.id,JSON.stringify(v)).run();
        const saved=await db.prepare('SELECT metadata,ready FROM position_versions WHERE id=?').bind(v.id).first();
        const stored=JSON.parse(saved.metadata);
        if(stored.sha256!==v.sha256 || stored.row_count!==v.row_count)return reply({error:'Versión incompatible.'},409);
        return reply({id:v.id,ready:!!saved.ready});
      }
      if(!HASH.test(body.id))invalid();
      const saved=await db.prepare('SELECT metadata,ready FROM position_versions WHERE id=?').bind(body.id).first();
      if(!saved)return reply({error:'Versión desconocida.'},404);
      const v=JSON.parse(saved.metadata);
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
        await db.batch(rows.map(r=>db.prepare(`INSERT OR IGNORE INTO position_rows
          (version_id,id,specialty,list_number,search_name,rank,payload)
          SELECT ?,?,?,?,?,?,? WHERE EXISTS(SELECT 1 FROM position_versions WHERE id=? AND ready=0)`)
          .bind(body.id,r.id,r.specialty,r.list_number,fold(r.name),r.rank,JSON.stringify(r),body.id)));
        return reply({accepted:rows.length});
      }
      if(body.action==='activate'){
        const groups=(await db.prepare('SELECT specialty,COUNT(*) AS n,MIN(rank) AS first,MAX(rank) AS last FROM position_rows WHERE version_id=? GROUP BY specialty').bind(body.id).all()).results;
        if(groups.length!==v.specialties.length || v.specialties.some(s=>!groups.some(g=>g.specialty===s.code && g.n===s.count && g.first===1 && g.last===s.count)))
          return reply({error:'La extracción está incompleta. Se conserva la anterior.'},409);
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
    delete version.specialties;
    if(path==='/api/positions' && request.method==='GET')return reply({version,specialties,refresh_available:!!env.GITHUB_TOKEN});
    if(path==='/api/positions/search' && request.method==='POST'){
      const body=await jsonBody(request,2048);
      if(!validText(body.query,100) || !specialties.some(s=>s.code===body.specialty))invalid();
      const query=fold(body.query), tokens=query.split(/[ ,]+/).filter(Boolean);
      if(query.replace(/[^\p{L}\p{N}]/gu,'').length<3 || tokens.length>6 || /[%_\\]/.test(query))invalid();
      const numeric=/^\d{7,8}$/.test(query);
      const condition=numeric?'list_number=?':tokens.map(()=>'search_name LIKE ?').join(' AND ');
      const values=numeric?[query]:tokens.map(t=>'%'+t+'%');
      const results=(await db.prepare(`SELECT payload FROM position_rows WHERE version_id=? AND specialty=? AND ${condition} ORDER BY rank LIMIT 21`)
        .bind(version.id,body.specialty,...values).all()).results;
      return reply({version,results:results.slice(0,20).map(r=>JSON.parse(r.payload)),more:results.length>20});
    }
    const match=path.match(/^\/api\/positions\/([a-f0-9]{32})$/);
    if(match && request.method==='GET'){
      const row=await db.prepare('SELECT payload FROM position_rows WHERE version_id=? AND id=?').bind(version.id,match[1]).first();
      return row?reply({version,person:JSON.parse(row.payload)}):reply({error:'Esta persona no figura en la publicación consultada.'},404);
    }
    return reply({error:'Recurso o método no permitido.'},404);
  }catch(error){return reply({error:error.status===400?error.message:'No se ha podido consultar la lista.'},error.status||503);}
}
