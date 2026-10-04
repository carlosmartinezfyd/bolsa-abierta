import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync, existsSync} from 'node:fs';
import {reserveWriteBudget,settleWriteBudget} from '../gateway/write-budget.mjs';
import {createGateway} from '../gateway/worker.mjs';

const origin='https://carlosmartinezfyd.github.io', secret='s'.repeat(48);
const version={id:'a'.repeat(64),sha256:'a'.repeat(64),published_at:'2026-07-22',checked_at:'2026-10-02T12:00:00Z',
  source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208095',row_count:2,scope:'published_list',coverage:'baseline_only',
  specialties:[{code:'0590001',name:'FILOSOFIA',body:'SECUNDARIA',count:2}]};
const row=(n,name='PRUEBA, ANA')=>({id:String(n).padStart(32,'0'),specialty:'0590001',specialty_name:'FILOSOFIA',body_name:'SECUNDARIA',
  block:'68',block_name:'Bloque 1',list_number:`250000${n}0`,name,search_name:name,rank:n,page:2});

const document={content_id:'209126',kind:'award',sha256:'d'.repeat(64),published_at:'2026-09-24',pages:2,row_count:1,
  source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=209126',specialties:[{code:'0590I09',name:'DIBUJO / INGLES',body:'SECUNDARIA',count:1}]};
const multiple={...version,id:'e'.repeat(64),coverage:'multi_source',row_count:3,ranked_specialties:version.specialties,
  specialties:[...version.specialties,...document.specialties],documents:[document]};
const award={...row(1),id:'f'.repeat(32),specialty:'0590I09',source_id:'209126',record_type:'award',rank:null,
  block:'',block_name:'',destination:'IES DE PRUEBA · MURCIA',workload:'10 horas',dni:'SHOULD NOT BE STORED'};

test('complete bilingual award documents become searchable without claiming a rank',async()=>{
  const f=setup();try{
    assert.equal((await f.ingest({action:'begin',version:multiple})).status,200);
    assert.equal((await f.ingest({action:'rows',id:multiple.id,rows:[row(1),row(2),award]})).status,200);
    assert.equal((await f.ingest({action:'activate',id:multiple.id})).status,200);
    const data=await (await f.call('/api/positions/search',{query:'Prueba',specialty:'0590I09'})).json();
    assert.equal(data.results.length,1);assert.equal(data.results[0].rank,null);
    assert.equal(data.results[0].record_type,'award');assert.equal(data.results[0].destination,award.destination);
    assert.equal('dni' in data.results[0],false);
    assert.equal(data.version.documents[0].published_at,'2026-09-24');
    assert.equal((await (await f.call('/api/positions/'+row(1).id)).json()).person.rank,1);
  }finally{f.db.close();}
});

test('missing evidence records cannot activate and fabricated award ranks are rejected',async()=>{
  const f=setup();try{
    assert.equal((await f.ingest({action:'begin',version:multiple})).status,200);
    assert.equal((await f.ingest({action:'rows',id:multiple.id,rows:[{...award,rank:1}]})).status,400);
    assert.equal((await f.ingest({action:'rows',id:multiple.id,rows:[{...award,source_id:'99999'}]})).status,400);
    await f.ingest({action:'rows',id:multiple.id,rows:[row(1),row(2)]});
    assert.equal((await f.ingest({action:'activate',id:multiple.id})).status,409);
    assert.equal((await f.call('/api/positions')).status,503);
  }finally{f.db.close();}
});

test('manifest rejects wrong per-document totals and non-official evidence',async()=>{
  const f=setup();try{
    for(const doc of [{...document,row_count:2},{...document,source_url:'https://example.org/a.pdf'},
      {...document,kind:'provisional'},{...document,content_id:'208095'}]){
      assert.equal((await f.ingest({action:'begin',version:{...multiple,documents:[doc]}})).status,400);
    }
  }finally{f.db.close();}
});

test('accumulated valid source metadata is not limited to a few weekly documents',async()=>{
  const f=setup();try{
    const documents=Array.from({length:30},(_,i)=>({...document,content_id:String(300000+i),
      source_url:'https://www.carm.es/web/descarga?IDCONTENIDO='+String(300000+i),
      specialties:Array.from({length:42},(_,n)=>({code:'0590'+String(n).padStart(3,'0'),name:'ESPECIALIDAD DE PRUEBA '.repeat(5),body:'CUERPO DE PROFESORES DE ENSEÑANZA SECUNDARIA',count:1})),row_count:42}));
    const totals=new Map(version.specialties.map(s=>[s.code,{...s}]));
    for(const d of documents)for(const s of d.specialties){if(!totals.has(s.code))totals.set(s.code,{...s,count:0});totals.get(s.code).count+=s.count;}
    const v={...multiple,documents,row_count:1262,specialties:[...totals.values()]};
    assert.ok(JSON.stringify(v).length>160000);
    assert.equal((await f.ingest({action:'begin',version:v})).status,200);
  }finally{f.db.close();}
});

test('reviewed amendment rows retain their own official document and page',async()=>{
  const f=setup();try{
    const corrected={...version,id:'c'.repeat(64),coverage:'reviewed_amendments',amendments:[{content_id:'208249',sha256:'b'.repeat(64),signed_at:'2026-07-28',pages:2,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208249'}]};
    assert.equal((await f.ingest({action:'begin',version:corrected})).status,200);
    assert.equal((await f.ingest({action:'rows',id:corrected.id,rows:[row(1),{...row(2),page:1,source_id:'208249'}]})).status,200);
    assert.equal((await f.ingest({action:'activate',id:corrected.id})).status,200);
    const result=await (await f.call('/api/positions/'+row(2).id)).json();
    assert.equal(result.person.source_id,'208249');assert.equal(result.person.page,1);
    assert.equal(result.version.amendments[0].sha256,'b'.repeat(64));
  }finally{f.db.close();}
});

function setup(legacy=false){
  const db=new DatabaseSync(':memory:');
  const statements=[];
  db.exec(readFileSync(new URL('../gateway/schema.sql',import.meta.url),'utf8'));
  const schema=new URL('../gateway/positions.sql',import.meta.url);
  if(existsSync(schema)){const sql=readFileSync(schema,'utf8');db.exec(legacy?sql.split('-- Indexed exact')[0]:sql);}
  let batchQueue=Promise.resolve();
  const binding={withSession:()=>binding,prepare:sql=>{statements.push(sql);const statement={args:[],bind(...args){this.args=args;return this;},
    async first(){return db.prepare(sql).get(...this.args)||null;},async all(){return {results:db.prepare(sql).all(...this.args)};},
    async run(){return {meta:{changes:db.prepare(sql).run(...this.args).changes}};}};return statement;},
    async batch(statements){const work=async()=>{db.exec('BEGIN');try{const results=[];for(const s of statements)results.push(await s.run());db.exec('COMMIT');return results;}catch(e){db.exec('ROLLBACK');throw e;}};const result=batchQueue.then(work);batchQueue=result.catch(()=>{});return result;}};
  const handler=createGateway();
  async function call(path,body,auth=false){return handler(new Request('https://gateway.example'+path,{method:body?'POST':'GET',
    headers:{Origin:origin,'Content-Type':'application/json',...(auth?{Authorization:`Bearer ${secret}`}:{})},
    ...(body?{body:JSON.stringify(body)}:{})}),{DB:binding,ALLOWED_ORIGIN:origin,POSITION_INGEST_TOKEN:secret});}
  const ingest=(body)=>call('/internal/positions',body,true);
  return {db,call,ingest,statements,binding};
}

test('name-first search works across specialties, preserves ambiguity and counts repeated surnames',async()=>{
  const f=setup();try{
    const v={...version,row_count:4,specialties:[...version.specialties,{code:'0590009',name:'DIBUJO',body:'SECUNDARIA',count:2}]};
    await f.ingest({action:'begin',version:v});
    await f.ingest({action:'rows',id:v.id,rows:[row(1,'MARTÍNEZ MARTÍNEZ, CARLOS'),row(2,'MARTÍNEZ LÓPEZ, CARLOS'),
      {...row(1,'MARTÍNEZ MARTÍNEZ, CARLOS'),id:'3'.repeat(32),specialty:'0590009'},
      {...row(2,'OTRA, PERSONA'),id:'4'.repeat(32),specialty:'0590009'}]});
    await f.ingest({action:'activate',id:v.id});
    const response=await f.call('/api/positions/search',{query:'Carlos Martínez Martínez'});
    assert.equal(response.status,200);
    const data=await response.json();
    assert.deepEqual(data.results.map(r=>r.specialty),['0590001','0590009']);
    const scoped=await (await f.call('/api/positions/search',{query:'Martinez Martinez Carlos',specialty:'0590009'})).json();
    assert.equal(scoped.results.length,1);
    const numeric=await (await f.call('/api/positions/search',{query:'25000010',specialty:''})).json();
    assert.equal(numeric.results.length,2);
    assert.equal((await f.call('/api/positions/search',{query:'ca'})).status,400);
    assert.equal((await f.call('/api/positions/search',{query:'Carlos',specialty:123})).status,400);
  }finally{f.db.close();}
});

test('global search remains bounded when many specialties match',async()=>{
  const f=setup();try{
    const v={...version,row_count:22,specialties:[{...version.specialties[0],count:22}]};
    await f.ingest({action:'begin',version:v});
    await f.ingest({action:'rows',id:v.id,rows:Array.from({length:22},(_,i)=>({...row(i+1),list_number:String(25000000+i)}))});
    await f.ingest({action:'activate',id:v.id});
    const result=await (await f.call('/api/positions/search',{query:'prueba'})).json();
    assert.equal(result.results.length,20);assert.equal(result.more,true);
    assert.equal(result.next_offset,20);
    const next=await (await f.call('/api/positions/search',{query:'prueba',offset:20,version_id:v.id})).json();
    assert.equal(next.results.length,2);assert.equal(next.more,false);
    assert.equal(new Set([...result.results,...next.results].map(r=>r.id)).size,22);
    assert.equal((await f.call('/api/positions/search',{query:'prueba',offset:20,version_id:'f'.repeat(64)})).status,409);
    assert.equal((await f.call('/api/positions/search',{query:'prueba',offset:-20,version_id:v.id})).status,400);
  }finally{f.db.close();}
});

test('staged or incomplete generations never replace the active ranking',async()=>{
  const f=setup();try{
    assert.equal((await f.ingest({action:'begin',version})).status,200);
    assert.equal((await f.call('/api/positions')).status,503);
    assert.equal((await f.ingest({action:'rows',id:version.id,rows:[row(1)]})).status,200);
    assert.equal((await f.ingest({action:'activate',id:version.id})).status,409);
    await f.ingest({action:'rows',id:version.id,rows:[row(2)]});
    assert.equal((await f.ingest({action:'activate',id:version.id})).status,200);
    const catalog=await (await f.call('/api/positions')).json();
    assert.equal(catalog.version.scope,'published_list');assert.equal(catalog.specialties[0].count,2);
    assert.equal((await f.ingest({action:'rows',id:version.id,rows:[row(1,'ALTERED')]})).status,409);
    const second={...version,id:'b'.repeat(64),sha256:'b'.repeat(64)};
    await f.ingest({action:'begin',version:second});
    assert.equal((await f.ingest({action:'activate',id:second.id})).status,409);
    assert.equal((await (await f.call('/api/positions')).json()).version.id,version.id);
  }finally{f.db.close();}
});

test('search is scoped, bounded and accent insensitive; row read includes dated evidence without DNI',async()=>{
  const f=setup();try{
    await f.ingest({action:'begin',version});
    await f.ingest({action:'rows',id:version.id,rows:[row(1,'PÉREZ, ANA'),row(2,'PEREZ, LUIS')]});
    await f.ingest({action:'activate',id:version.id});
    const response=await f.call('/api/positions/search',{specialty:'0590001',query:'pérez ana'});
    assert.equal(response.status,200);assert.equal(response.headers.get('Cache-Control'),'no-store');
    const result=await response.json();assert.equal(result.results.length,1);assert.equal(result.results[0].rank,1);
    assert.equal('search_name' in result.results[0],false);assert.equal('dni' in result.results[0],false);
    const person=await (await f.call('/api/positions/'+row(1).id)).json();
    assert.equal(person.person.name,'PÉREZ, ANA');assert.equal(person.version.published_at,'2026-07-22');
    assert.equal((await f.call('/api/positions/search',{specialty:'0590001',query:'a'})).status,400);
    assert.equal((await f.call('/api/positions/search',{specialty:'0590001',query:'%%%'})).status,400);
    assert.equal((await f.call('/api/positions/search',{specialty:'0590002',query:'PEREZ'})).status,400);
    assert.equal((await f.call('/api/positions/search',{specialty:'0590001',query:'25000020'})).status,200);
    assert.equal((await f.call('/api/positions?dump=1')).status,400);
  }finally{f.db.close();}
});

test('ingest needs its own secret and rejects malformed evidence, gaps and excessive batches',async()=>{
  const f=setup();try{
    assert.equal((await f.call('/internal/positions',{action:'begin',version})).status,403);
    assert.equal((await f.ingest({action:'begin',version:{...version,source_url:'https://evil.example/a.pdf'}})).status,400);
    await f.ingest({action:'begin',version});
    assert.equal((await f.ingest({action:'rows',id:version.id,rows:Array.from({length:41},()=>row(1))})).status,400);
    await f.ingest({action:'rows',id:version.id,rows:[row(1),row(3)]});
    assert.equal((await f.ingest({action:'activate',id:version.id})).status,409);
    assert.equal((await f.call('/api/positions')).status,503);
  }finally{f.db.close();}
});

test('a concurrent batch cannot add ranks beyond the reviewed specialty total',async()=>{
  const f=setup();try{
    await f.ingest({action:'begin',version});
    await f.ingest({action:'rows',id:version.id,rows:[row(1),row(2)]});
    assert.equal((await f.ingest({action:'rows',id:version.id,rows:[row(3)]})).status,400);
    assert.equal((await f.ingest({action:'activate',id:version.id})).status,200);
    assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM position_rows').get().n,2);
  }finally{f.db.close();}
});

const maestroDoc={content_id:'208253',kind:'maestros_roster',rank_scope:'maestros_unique_list',sha256:'1'.repeat(64),published_at:'2026-07-29',pages:50,row_count:2,
 source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208253',specialties:[{code:'0597',name:'Lista única de Maestros',body:'CUERPO DE MAESTROS',count:2}],
 amendments:[{content_id:'208782',sha256:'2'.repeat(64),signed_at:'2026-08-14',pages:2,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208782'}]};
const maestroVersion={...multiple,id:'3'.repeat(64),row_count:5,specialties:[...multiple.specialties,...maestroDoc.specialties],documents:[document,maestroDoc]};
const maestro=n=>({...row(n),id:(8+n).toString(16).repeat(32),specialty:'0597',block:'I',block_name:'Bloque I',record_type:'list',rank_scope:'maestros_unique_list',roster_id:'208253',source_id:n===1?'208253':'208782',page:n===1?3:1,baseline_page:4,
 habilitations:[{code:'031',name:'EDUCACIÓN PRIMARIA'},{code:'036',name:'PEDAGOGÍA TERAPÉUTICA'}],membership_id:(6+n).toString(16).repeat(32)});

test('Maestros roster and reviewed correction activate independently from baseline and awards',async()=>{
 const f=setup();try{
  assert.equal((await f.ingest({action:'begin',version:maestroVersion})).status,200);
  assert.equal((await f.ingest({action:'rows',id:maestroVersion.id,rows:[row(1),row(2),award,maestro(1)]})).status,200);
  assert.equal((await f.ingest({action:'activate',id:maestroVersion.id})).status,409);
  assert.equal((await f.ingest({action:'rows',id:maestroVersion.id,rows:[maestro(2)]})).status,200);
  assert.equal((await f.ingest({action:'activate',id:maestroVersion.id})).status,200);
  const data=await(await f.call('/api/positions/search',{query:'prueba',specialty:'0597'})).json();
  assert.equal(data.results.length,2);assert.deepEqual(data.results.map(x=>x.rank),[1,2]);
  assert.equal(data.results[1].source_id,'208782');assert.equal(data.results[1].roster_id,'208253');assert.equal(data.results[1].baseline_page,4);
  assert.equal(data.results[1].habilitations[0].code,'031');assert.equal(data.results[1].membership_id,maestro(2).membership_id);
  assert.equal(data.version.documents[1].amendments[0].pages,2);
 }finally{f.db.close();}
});

test('invalid Maestros evidence, fabricated habilitations and rank scopes are rejected',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version:maestroVersion});
  for(const r of [{...maestro(1),roster_id:'9999'},{...maestro(1),source_id:'209126'},{...maestro(1),rank_scope:'specialty'},
   {...maestro(2),page:3},{...maestro(1),habilitations:[{code:'0597999',name:'inventada'}]},
   {...maestro(1),habilitations:[{code:'031',name:'a'},{code:'031',name:'b'}]}])assert.equal((await f.ingest({action:'rows',id:maestroVersion.id,rows:[r]})).status,400);
 }finally{f.db.close();}
});

test('award dates and definitive/provisional facts are whitelisted independently of publication',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version:multiple});
  for(const r of [{...award,incorporation_at:'2026-02-30'},{...award,incorporation_at:'mañana'},
   {...award,appointment_status:'medical'}])assert.equal((await f.ingest({action:'rows',id:multiple.id,rows:[r]})).status,400);
  await f.ingest({action:'rows',id:multiple.id,rows:[row(1),row(2),{...award,incorporation_at:'2026-09-25',appointment_status:'provisional',observations:'private',substituted_person:'private'}]});
  await f.ingest({action:'activate',id:multiple.id});
  const person=(await(await f.call('/api/positions/'+award.id)).json()).person;
  assert.equal(person.incorporation_at,'2026-09-25');assert.equal(person.appointment_status,'provisional');assert.equal(person.rank,null);
  assert.equal('observations' in person,false);assert.equal('substituted_person' in person,false);
 }finally{f.db.close();}
});

test('opaque cursor preserves infix, accent, any order and repeated-token semantics',async()=>{
 const f=setup();try{
  const v={...version,row_count:25,specialties:[{...version.specialties[0],count:25}]};
  await f.ingest({action:'begin',version:v});
  await f.ingest({action:'rows',id:v.id,rows:Array.from({length:25},(_,i)=>({...row(i+1,'MARTÍNEZ MARTÍNEZ, CARLOS'),list_number:String(25000000+i)}))});
  await f.ingest({action:'activate',id:v.id});
  const first=await(await f.call('/api/positions/search',{query:'los artinez artinez'})).json();
  assert.equal(first.results.length,20);assert.ok(first.next_cursor);
  const next=await(await f.call('/api/positions/search',{query:'los artinez artinez',cursor:first.next_cursor,offset:20,version_id:v.id})).json();
  assert.equal(next.results.length,5);assert.equal(new Set([...first.results,...next.results].map(r=>r.id)).size,25);
  assert.equal((await f.call('/api/positions/search',{query:'other',cursor:first.next_cursor})).status,409);
  assert.equal((await f.call('/api/positions/search',{query:'a na'})).status,400);
 }finally{f.db.close();}
});

test('authenticated recovery metadata and rollback do not expose a public nominal dump',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});await f.ingest({action:'rows',id:version.id,rows:[row(1),row(2)]});await f.ingest({action:'activate',id:version.id});
  const second={...version,id:'b'.repeat(64),sha256:'b'.repeat(64)};await f.ingest({action:'begin',version:second});await f.ingest({action:'rows',id:second.id,rows:[row(1)]});
  const status=await(await f.ingest({action:'status',id:second.id})).json();assert.deepEqual(status.existing_ids,[row(1).id]);assert.equal(JSON.stringify(status).includes('PRUEBA'),false);
  assert.equal((await f.ingest({action:'rollback',id:second.id})).status,409);
  assert.equal((await f.call('/internal/positions',{action:'status',id:second.id})).status,403);
  assert.equal((await f.ingest({action:'recover',id:second.id})).status,200);
  assert.equal((await(await f.ingest({action:'status',id:second.id})).json()).existing_ids.length,0);
  await f.ingest({action:'rows',id:second.id,rows:[row(1),row(2)]});await f.ingest({action:'activate',id:second.id});
  assert.equal((await f.ingest({action:'rollback',id:version.id})).status,200);
  assert.equal((await(await f.call('/api/positions')).json()).version.id,version.id);
  assert.equal((await f.ingest({action:'recover',id:version.id})).status,409);
 }finally{f.db.close();}
});

test('40-row ingest stays below 50 statements and daily cap preserves active generations',async()=>{
 const f=setup();try{
  const v={...version,row_count:40,specialties:[{...version.specialties[0],count:40}]};
  await f.ingest({action:'begin',version:v});f.statements.length=0;
  assert.equal((await f.ingest({action:'rows',id:v.id,rows:Array.from({length:40},(_,i)=>({...row(i+1),list_number:String(25000000+i)}))})).status,200);
  assert.ok(f.statements.length<50,String(f.statements.length));
  await f.ingest({action:'activate',id:v.id});
  const next={...v,id:'b'.repeat(64),sha256:'b'.repeat(64)};await f.ingest({action:'begin',version:next});
  f.db.prepare('UPDATE position_write_budget SET day=?,writes=70000').run(new Date().toISOString().slice(0,10));
  const blocked=await f.ingest({action:'rows',id:next.id,rows:[row(1)]});assert.equal(blocked.status,429);assert.equal((await blocked.json()).pending_budget,true);
  assert.equal((await(await f.call('/api/positions')).json()).version.id,v.id);
  assert.equal(f.db.prepare('SELECT phase FROM position_ingest_metrics WHERE version_id=?').get(next.id).phase,'pending_budget');
 }finally{f.db.close();}
});

test('FTS and numeric plans use indexes on 12000 synthetic rows and migration reruns are idempotent',async()=>{
 for(const table of ['position_rows','position_entries']){
 const f=setup();try{
  const v=table==='position_rows'?version:{...version,coverage:'multi_source'};
  f.db.prepare('INSERT INTO position_versions(id,metadata,ready) VALUES(?,?,1)').run(v.id,JSON.stringify(v));
  const insert=f.db.prepare(`INSERT INTO ${table}(version_id,id,specialty,list_number,search_name,rank,payload) VALUES(?,?,?,?,?,?,?)`);
  f.db.exec('BEGIN');for(let i=1;i<=12000;i++)insert.run(version.id,String(i).padStart(32,'0'),'0590001',String(25000000+i),i===8123?'MARTINEZ MARTINEZ CARLOS':'SYNTHETIC PERSON '+i,i,'{}');f.db.exec('COMMIT');
  const numberPlan=f.db.prepare(`EXPLAIN QUERY PLAN SELECT payload FROM ${table} WHERE version_id=? AND list_number=? LIMIT 21`).all(version.id,'25008123').map(r=>r.detail).join('\n');
  f.db.prepare('INSERT INTO position_active(singleton,version_id) VALUES(1,?)').run(version.id);
  f.db.prepare('INSERT INTO position_search_status(version_id,ready) VALUES(?,1)').run(version.id);
  assert.equal((await f.call('/api/positions/search',{query:'synthetic'})).status,422);
  for(const scoped of [false,true]){
   const partial=await(await f.call('/api/positions/search',{query:'artinez',...(scoped?{specialty:'0590001'}:{})})).json();assert.equal(partial.results.length,1);
   const actualSQL=f.statements.findLast(sql=>sql.startsWith('WITH candidates AS MATERIALIZED'));
   const plan=f.db.prepare('EXPLAIN QUERY PLAN '+actualSQL).all('version_id : "'+version.id.slice(0,16)+'" AND search_name : "ARTINEZ"',version.id,...(scoped?['0590001']:[]),'%ARTINEZ%',0).map(r=>r.detail);
   const ftsIndex=plan.findIndex(detail=>detail.includes(table+'_fts')&&/VIRTUAL TABLE INDEX.*M/.test(detail));
   const rowLookup=plan.findIndex(detail=>/SEARCH p USING INTEGER PRIMARY KEY \(rowid=\?\)/.test(detail));
   assert.ok(ftsIndex>=0,plan.join('\n'));assert.ok(rowLookup>ftsIndex,plan.join('\n'));
   assert.equal(plan.filter(detail=>/\b(?:SEARCH|SCAN) p\b/.test(detail)).length,1,plan.join('\n'));
   assert.match(actualSQL,/p\.version_id=\?/);assert.equal(actualSQL.includes('AND p.specialty=?'),scoped);assert.match(actualSQL,/LIMIT 5001/);
  }
  assert.ok(numberPlan.includes(table+'_number'),numberPlan);
  assert.equal(f.db.prepare(`SELECT COUNT(*) AS n FROM ${table}_fts WHERE ${table}_fts MATCH ?`).get('search_name : "ARTINEZ"').n,1);
  const migration=readFileSync(new URL('../gateway/migrations/0001-search-and-evidence.sql',import.meta.url),'utf8');f.db.exec(migration);const before=f.db.prepare('SELECT total_changes() AS n').get().n;f.db.exec(migration);
  assert.equal(f.db.prepare('SELECT total_changes() AS n').get().n,before);
 }finally{f.db.close();}
 }
});

test('late concurrent evidence insertion cannot slip between validation and atomic activation',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});await f.ingest({action:'rows',id:version.id,rows:[row(1),row(2)]});await f.ingest({action:'activate',id:version.id});
  await f.ingest({action:'begin',version:multiple});await f.ingest({action:'rows',id:multiple.id,rows:[row(1),row(2),award]});
  const original=f.binding.batch;
  f.binding.batch=async statements=>{
   f.db.prepare('INSERT INTO position_entries(version_id,id,specialty,list_number,search_name,rank,payload) VALUES(?,?,?,?,?,?,?)')
    .run(multiple.id,'b'.repeat(32),award.specialty,award.list_number,'PRUEBA ANA',null,JSON.stringify({...award,id:'b'.repeat(32)}));
   return original(statements);
  };
  assert.equal((await f.ingest({action:'activate',id:multiple.id})).status,409);
  assert.equal(f.db.prepare('SELECT ready FROM position_versions WHERE id=?').get(multiple.id).ready,0);
  assert.equal((await(await f.call('/api/positions')).json()).version.id,version.id);
 }finally{f.db.close();}
});

test('legacy FTS migration backfills in resumable budgeted batches with no full-generation rebuild',async()=>{
 const f=setup(true);try{
  const v={...version,row_count:42,specialties:[{...version.specialties[0],count:42}]};
  f.db.prepare('INSERT INTO position_versions(id,metadata,ready) VALUES(?,?,1)').run(v.id,JSON.stringify(v));
  const insert=f.db.prepare('INSERT INTO position_rows(version_id,id,specialty,list_number,search_name,rank,payload)VALUES(?,?,?,?,?,?,?)');
  for(let i=1;i<=42;i++){const r={...row(i),list_number:String(25000000+i)};insert.run(v.id,r.id,r.specialty,r.list_number,'PRUEBA ANA',i,JSON.stringify(r));}
  f.db.prepare('INSERT INTO position_active(singleton,version_id)VALUES(1,?)').run(v.id);
  f.db.exec(readFileSync(new URL('../gateway/migrations/0001-search-and-evidence.sql',import.meta.url),'utf8'));
  assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM position_rows_search_indexed').get().n,0);
  assert.equal((await f.call('/api/positions')).status,200);assert.equal((await f.call('/api/positions/'+row(1).id)).status,200);
  assert.equal((await f.call('/api/positions/search',{query:'prueba'})).status,503);assert.equal((await f.call('/api/positions/search',{query:'25000001'})).status,200);
  const first=await(await f.ingest({action:'index',id:v.id})).json();assert.equal(first.indexed,40);assert.equal(first.index_ready,false);
  assert.equal(f.db.prepare('SELECT COUNT(*) AS n FROM position_rows_search_indexed').get().n,40);
  f.db.prepare("UPDATE position_write_budget SET day=date('now'),writes=70000").run();
  assert.equal((await f.ingest({action:'index',id:v.id})).status,429);
  f.db.prepare("UPDATE position_write_budget SET day='',writes=0").run();f.db.prepare("DELETE FROM position_write_allocations WHERE reservation_id LIKE 'legacy:%'").run();
  const second=await(await f.ingest({action:'index',id:v.id})).json();assert.equal(second.indexed,2);
  assert.equal((await(await f.ingest({action:'index',id:v.id})).json()).index_ready,true);
  assert.equal((await f.call('/api/positions/search',{query:'prueba'})).status,200);
  const before=f.db.prepare('SELECT total_changes() AS n').get().n;
  assert.equal((await(await f.ingest({action:'index',id:v.id})).json()).indexed,0);
  assert.equal(f.db.prepare('SELECT total_changes() AS n').get().n,before);
 }finally{f.db.close();}
});

test('actual reviewed Maestros manifest shape accepts hyphen course, Roman blocks and unspecified habilitations',async()=>{
 const f=setup();try{
  const doc=JSON.parse(readFileSync(new URL('../data/position-maestros.json',import.meta.url),'utf8'));
  const v={...multiple,id:'4'.repeat(64),course:'2026-2027',row_count:multiple.row_count+doc.row_count,specialties:[...multiple.specialties,...doc.specialties],documents:[document,doc]};
  assert.equal((await f.ingest({action:'begin',version:v})).status,200);
  const correction={...maestro(2),source_id:doc.amendments[0].content_id,page:3,habilitations:[],habilitations_status:'not_stated',amendment_relation:{kind:'inclusion',previous_id:null,previous_list_number:null}};
  assert.equal((await f.ingest({action:'rows',id:v.id,rows:[correction]})).status,200);
  const saved=JSON.parse(f.db.prepare('SELECT payload FROM position_entries WHERE version_id=? AND id=?').get(v.id,correction.id).payload);
  assert.equal(saved.block,'I');assert.equal(saved.habilitations_status,'not_stated');assert.deepEqual(saved.habilitations,[]);assert.equal(saved.source_id,'208782');assert.equal(saved.amendment_relation.kind,'inclusion');
  const metadata=(await(await f.ingest({action:'metadata',id:v.id})).json()).version;
  assert.equal(metadata.course,'2026-2027');assert.equal(metadata.documents[1].course,'2026-2027');assert.equal(metadata.documents[1].row_count,9211);assert.equal(metadata.documents[1].pages,651);
  assert.equal((await f.ingest({action:'rows',id:v.id,rows:[{...correction,block:'1'}]})).status,400);
  assert.equal((await f.ingest({action:'rows',id:v.id,rows:[{...correction,habilitations_status:'none'}]})).status,400);
  assert.equal((await f.ingest({action:'rows',id:v.id,rows:[{...correction,habilitations:maestro(1).habilitations}]})).status,400);
  assert.equal((await f.ingest({action:'begin',version:{...v,id:'5'.repeat(64),course:'2026/2027'}})).status,200);
 }finally{f.db.close();}
});

test('multi-source recovery removes only its own FTS markers and allows an idempotent restart',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});await f.ingest({action:'rows',id:version.id,rows:[row(1),row(2)]});await f.ingest({action:'activate',id:version.id});
  await f.ingest({action:'begin',version:multiple});await f.ingest({action:'rows',id:multiple.id,rows:[row(1)]});
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_rows_search_indexed').get().n,2);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_entries_search_indexed').get().n,1);
  await f.ingest({action:'recover',id:multiple.id});
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_rows_search_indexed').get().n,2);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_entries_search_indexed').get().n,0);
  assert.equal((await(await f.call('/api/positions/search',{query:'prueba'})).json()).results.length,2);
  assert.equal((await f.ingest({action:'rows',id:multiple.id,rows:[row(1),row(2),award]})).status,200);
  assert.equal((await f.ingest({action:'activate',id:multiple.id})).status,200);
  assert.equal((await(await f.call('/api/positions/search',{query:'prueba'})).json()).results.length,3);
 }finally{f.db.close();}
});

test('reviewed habilitation additions retain explicit parent relation without creating another membership',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version:maestroVersion});
  const r={...maestro(2),amendment_relation:{kind:'habilitation_added',previous_id:maestro(2).id,previous_list_number:maestro(2).list_number,baseline_source_id:'208253',baseline_page:4,code:'036',published_code:'597036',raw_observations:'private'}};
  assert.equal((await f.ingest({action:'rows',id:maestroVersion.id,rows:[r]})).status,200);
  const data=JSON.parse(f.db.prepare('SELECT payload FROM position_entries WHERE version_id=? AND id=?').get(maestroVersion.id,r.id).payload);
  assert.equal(data.amendment_relation.published_code,'597036');assert.equal(data.amendment_relation.baseline_source_id,'208253');assert.equal('raw_observations' in data.amendment_relation,false);
  assert.equal((await f.ingest({action:'rows',id:maestroVersion.id,rows:[{...r,amendment_relation:{...r.amendment_relation,previous_id:'f'.repeat(32)}}]})).status,400);
 }finally{f.db.close();}
});

test('same-total recovered award redistribution invalidates the validated staging revision',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});await f.ingest({action:'rows',id:version.id,rows:[row(1),row(2)]});await f.ingest({action:'activate',id:version.id});
  const secondDoc={...document,content_id:'209314',source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=209314'};
  const v={...multiple,id:'6'.repeat(64),row_count:4,specialties:[...version.specialties,{...document.specialties[0],count:2}],documents:[document,secondDoc]};
  const secondAward={...award,id:'b'.repeat(32),source_id:'209314'};
  await f.ingest({action:'begin',version:v});await f.ingest({action:'rows',id:v.id,rows:[row(1),row(2),award,secondAward]});
  const before=f.db.prepare('SELECT revision FROM position_staging_revisions WHERE version_id=?').get(v.id).revision;
  const original=f.binding.batch;let replaced=false;
  f.binding.batch=async statements=>{
   // Activation is the only two-statement batch whose first statement has one version ID.
   if(!replaced&&statements.length===2&&statements[0].args.length===6){
    replaced=true;assert.equal((await f.ingest({action:'recover',id:v.id})).status,200);
    assert.equal((await f.ingest({action:'rows',id:v.id,rows:[row(1),row(2),{...award,id:'c'.repeat(32)},{...award,id:'d'.repeat(32)}]})).status,200);
   }
   return original(statements);
  };
  assert.equal((await f.ingest({action:'activate',id:v.id})).status,409);assert.equal(replaced,true);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_entries WHERE version_id=?').get(v.id).n,4);
  assert.ok(f.db.prepare('SELECT revision FROM position_staging_revisions WHERE version_id=?').get(v.id).revision>before);
  assert.equal(f.db.prepare('SELECT ready FROM position_versions WHERE id=?').get(v.id).ready,0);
  assert.equal((await(await f.call('/api/positions')).json()).version.id,version.id);
 }finally{f.db.close();}
});

test('legacy staged activation and unindexed rollback retain the searchable active pointer',async()=>{
 const f=setup(true);try{
  const second={...version,id:'b'.repeat(64),sha256:'b'.repeat(64)};
  for(const [v,ready] of [[version,1],[second,0]]){
   f.db.prepare('INSERT INTO position_versions(id,metadata,ready)VALUES(?,?,?)').run(v.id,JSON.stringify(v),ready);
   for(const r of [row(1),row(2)])f.db.prepare('INSERT INTO position_rows(version_id,id,specialty,list_number,search_name,rank,payload)VALUES(?,?,?,?,?,?,?)').run(v.id,r.id,r.specialty,r.list_number,'PRUEBA ANA',r.rank,JSON.stringify(r));
  }
  f.db.prepare('INSERT INTO position_active(singleton,version_id)VALUES(1,?)').run(version.id);
  f.db.exec(readFileSync(new URL('../gateway/migrations/0001-search-and-evidence.sql',import.meta.url),'utf8'));
  await f.ingest({action:'index',id:version.id});await f.ingest({action:'index',id:version.id});
  const blocked=await f.ingest({action:'activate',id:second.id});assert.equal(blocked.status,409);assert.equal((await blocked.json()).index_pending,true);
  assert.equal((await(await f.call('/api/positions')).json()).version.id,version.id);
  f.db.prepare('UPDATE position_versions SET ready=1 WHERE id=?').run(second.id);
  assert.equal((await f.ingest({action:'rollback',id:second.id})).status,409);
  assert.equal((await(await f.call('/api/positions')).json()).version.id,version.id);
  assert.equal((await f.call('/api/positions/search',{query:'prueba'})).status,200);
 }finally{f.db.close();}
});

test('database UTC budget rejects delayed old callers and retains concurrent actual allocations across midnight',async()=>{
 const f=setup();let day='2026-10-04',time='23:59:30';
 f.db.function('date',{varargs:true},(...args)=>typeof args[0]==='number'?new Date(args[0]*1000).toISOString().slice(0,10):args.length>1?new Date(Date.parse(day+'T00:00:00Z')+86400000).toISOString().slice(0,10):day);
 f.db.function('unixepoch',{varargs:true},()=>Math.floor(Date.parse(day+'T'+time+'Z')/1000));
 try{
  const original=f.binding.batch;let release,paused=true;
  const unblock=new Promise(r=>{release=r;});
  f.binding.batch=async statements=>{if(paused&&statements.length===3){paused=false;await unblock;}return original(statements);};
  const delayed=reserveWriteBudget(f.binding,{},1);
  day='2026-10-05';time='23:59:30';f.db.prepare('INSERT INTO position_write_allocations(reservation_id,day,charged)VALUES(?,?,?)').run('already','2026-10-05',69900);
  assert.equal(await reserveWriteBudget(f.binding,{},40),null);
  release();const old=await delayed;assert.ok(old);assert.equal(old.day,'2026-10-05');
  assert.equal(f.db.prepare('SELECT writes FROM position_write_usage').get().writes,69940);
  assert.equal(await reserveWriteBudget(f.binding,{},40),null);
  assert.equal(f.db.prepare('SELECT charged FROM position_write_allocations WHERE reservation_id=?').get('already').charged,69900);
  // Two real counter settlements cross UTC independently without erasing either day.
  day='2026-10-06';time='00:00:30';await settleWriteBudget(f.binding,old,[{meta:{rows_written:10}}]);
  assert.equal(f.db.prepare('SELECT charged FROM position_write_allocations WHERE reservation_id=? AND day=?').get(old.id,'2026-10-05').charged,18);
  assert.equal(f.db.prepare('SELECT charged FROM position_write_allocations WHERE reservation_id=? AND day=?').get(old.id,'2026-10-06').charged,18);
  time='23:59:30';const [a,b]=await Promise.all([reserveWriteBudget(f.binding,{},2),reserveWriteBudget(f.binding,{},3)]);
  day='2026-10-07';time='00:00:30';assert.equal(f.db.prepare('SELECT writes FROM position_write_usage').get().writes,a.reserved+b.reserved);
  await Promise.all([settleWriteBudget(f.binding,a,[{meta:{rows_written:60}}]),settleWriteBudget(f.binding,b,[{meta:{rows_written:90}}])]);
  assert.equal(f.db.prepare('SELECT writes FROM position_write_usage').get().writes,166);
  assert.equal(f.db.prepare('SELECT SUM(charged) n FROM position_write_allocations WHERE day=?').get('2026-10-06').n,184);
  const missing=await reserveWriteBudget(f.binding,{},1);await settleWriteBudget(f.binding,missing,[{meta:{changes:1}}]);
  assert.equal(f.db.prepare('SELECT charged FROM position_write_allocations WHERE reservation_id=?').get(missing.id).charged,missing.reserved);
  time='23:59:30';const failed=await reserveWriteBudget(f.binding,{},1);day='2026-10-08';time='00:00:30';
  assert.equal(f.db.prepare('SELECT writes FROM position_write_usage').get().writes,failed.reserved);
  assert.equal(f.db.prepare('SELECT settled FROM position_write_reservations WHERE id=?').get(failed.id).settled,0);
 }finally{f.db.close();}
});

test('cache publication may explicitly have no official checked timestamp until actual verification',async()=>{
 const f=setup();try{
  const v={...version,checked_at:null,parser_revision:'secondary-reviewed-v2'};
  assert.equal((await f.ingest({action:'begin',version:v})).status,200);
  await f.ingest({action:'rows',id:v.id,rows:[row(1),row(2)]});await f.ingest({action:'activate',id:v.id});
  assert.equal((await(await f.call('/api/positions')).json()).version.checked_at,null);
  assert.equal((await(await f.call('/api/positions')).json()).version.parser_revision,'secondary-reviewed-v2');
  assert.equal((await f.ingest({action:'checked',id:v.id,checked_at:null})).status,400);
  assert.equal((await f.ingest({action:'checked',id:v.id,checked_at:'2026-10-04T12:00:00Z'})).status,200);
  assert.equal((await(await f.call('/api/positions')).json()).version.checked_at,'2026-10-04T12:00:00Z');
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_rows').get().n,2);
 }finally{f.db.close();}
});

test('crashed budget leases expire without permanent future-day carry and expired mutations cannot write',async()=>{
 const f=setup();let clock=Date.parse('2026-10-04T12:00:00Z');
 f.db.function('date',{varargs:true},(...args)=>typeof args[0]==='number'?new Date(args[0]*1000).toISOString().slice(0,10):new Date(clock+(args.length>1?86400000:0)).toISOString().slice(0,10));
 f.db.function('unixepoch',{varargs:true},()=>Math.floor(clock/1000));
 try{
  for(let i=0;i<54;i++)assert.ok(await reserveWriteBudget(f.binding,{},40));
  assert.equal(await reserveWriteBudget(f.binding,{},40),null);
  assert.equal(f.db.prepare('SELECT writes FROM position_write_usage').get().writes,69552);
  for(const delta of [86400000,14*86400000,365*86400000]){
   clock=Date.parse('2026-10-04T12:00:00Z')+delta;
   assert.equal(f.db.prepare('SELECT writes FROM position_write_usage').get().writes,0);
   assert.ok(await reserveWriteBudget(f.binding,{},40));
  }
  assert.equal(f.db.prepare('SELECT SUM(charged) n FROM position_write_allocations WHERE day=?').get('2026-10-04').n,69552);
  const late=await reserveWriteBudget(f.binding,{},1);clock+=3*60000;
  const settlement=await settleWriteBudget(f.binding,late,[{meta:{rows_written:100}}]);
  assert.equal(settlement.expired,true);assert.equal(settlement.batch_writes,108);
  assert.equal(f.db.prepare('SELECT charged FROM position_write_allocations WHERE reservation_id=?').get(late.id).charged,108);
  const v={...version,row_count:40,specialties:[{...version.specialties[0],count:40}]};await f.ingest({action:'begin',version:v});
  const original=f.binding.batch;let delayed=false;
  f.binding.batch=async statements=>{if(!delayed&&statements.length===40){delayed=true;clock+=3*60000;}return original(statements);};
  const result=await f.ingest({action:'rows',id:v.id,rows:Array.from({length:40},(_,i)=>({...row(i+1),list_number:String(25000000+i)}))});
  assert.equal(result.status,409);assert.equal((await result.json()).reservation_expired,true);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_rows WHERE version_id=?').get(v.id).n,0);
 }finally{f.db.close();}
});

test('versioned baseline interpretation is accepted while legacy PDF-only identity remains readable',async()=>{
 const f=setup();try{
  const v={...version,id:'9'.repeat(64),course:'2026-2027',parser_revision:'secondary-ranked-list-v2'};
  assert.equal((await f.ingest({action:'begin',version:v})).status,200);
  await f.ingest({action:'rows',id:v.id,rows:[row(1),row(2)]});assert.equal((await f.ingest({action:'activate',id:v.id})).status,200);
  const catalog=await(await f.call('/api/positions')).json();assert.equal(catalog.version.id,v.id);assert.equal(catalog.version.sha256,version.sha256);assert.equal(catalog.version.parser_revision,v.parser_revision);
  assert.equal((await f.ingest({action:'begin',version})).status,200);
  assert.equal((await f.ingest({action:'begin',version:{...version,id:'8'.repeat(64)}})).status,400);
 }finally{f.db.close();}
});
