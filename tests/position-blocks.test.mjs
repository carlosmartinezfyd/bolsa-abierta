import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync,existsSync} from 'node:fs';
import {createGateway} from '../gateway/worker.mjs';
const origin='https://carlosmartinezfyd.github.io',secret='s'.repeat(48);
const version={id:'a'.repeat(64),sha256:'a'.repeat(64),published_at:'2026-07-22',checked_at:'2026-10-12T12:00:00Z',source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208095',row_count:2,scope:'published_list',coverage:'baseline_only',specialties:[{code:'0590001',name:'FILOSOFIA',body:'SECUNDARIA',count:2}]};
const row=(n,name='MARTINEZ MARTINEZ, CARLOS')=>({id:String(n).padStart(32,'0'),specialty:'0590001',block:'68',block_name:'Bloque 1',list_number:`250000${n}0`,name,rank:n,page:2,dni:'EXCLUDED'});
function setup(){
 const db=new DatabaseSync(':memory:');
 for(const file of ['schema.sql','positions.sql','migrations/0002-position-blocks.sql','migrations/0003-search-blocks.sql']){
  const path=new URL('../gateway/'+file,import.meta.url);if(existsSync(path))db.exec(readFileSync(path,'utf8'));
 }
 let queue=Promise.resolve();
 const binding={withSession:()=>binding,prepare:sql=>({args:[],bind(...args){this.args=args;return this;},async first(){return db.prepare(sql).get(...this.args)||null;},async all(){return {results:db.prepare(sql).all(...this.args)};},async run(){return {meta:{changes:db.prepare(sql).run(...this.args).changes,rows_written:/^(INSERT|UPDATE|DELETE)/i.test(sql)?3:0}};}}),async batch(ss){const work=async()=>{db.exec('BEGIN');try{let results=[];for(const s of ss)results.push(await s.run());db.exec('COMMIT');return results;}catch(e){db.exec('ROLLBACK');throw e;}};const result=queue.then(work);queue=result.catch(()=>{});return result;}};
 const env={DB:binding,ALLOWED_ORIGIN:origin,POSITION_INGEST_TOKEN:secret,POSITION_STORAGE:'blocks-v1'};
 const handler=createGateway();
 const call=(path,body,auth=false)=>handler(new Request('https://example.test'+path,{method:body?'POST':'GET',headers:{Origin:origin,'Content-Type':'application/json',...(auth?{Authorization:'Bearer '+secret}:{})},...(body?{body:JSON.stringify(body)}:{})}),env);
 return {db,env,call,ingest:body=>call('/internal/positions',body,true)};
}
test('compact publication is negotiated and stores only whitelisted immutable rows',async()=>{
 const f=setup();try{
  const begin=await f.ingest({action:'begin',version});assert.equal(begin.status,200);assert.equal((await begin.json()).storage,'blocks-v1');
  const block={action:'block',id:version.id,bucket:'00',rows:[row(1),row(2,'LOPEZ, ANA')]};
  assert.equal((await f.ingest(block)).status,200);
  assert.equal((await f.ingest(block)).status,200);
  assert.equal((await f.ingest({...block,rows:[row(1,'CHANGED'),row(2)]})).status,409);
  assert.equal((await f.ingest({action:'activate',id:version.id})).status,200);
  const found=await (await f.call('/api/positions/search',{query:'Carlos Martinez Martinez'})).json();
  assert.equal(found.results.length,1);assert.equal(found.results[0].rank,1);assert.equal('dni' in found.results[0],false);assert.equal('search_name' in found.results[0],false);
  const person=await (await f.call('/api/positions/'+row(2).id)).json();assert.equal(person.person.name,'LOPEZ, ANA');
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_entries').get().n,0);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_rows').get().n,0);
  assert.equal((await f.ingest(block)).status,409);
 }finally{f.db.close();}
});

test('server-derived search blocks can be resumed on ready data and preserve infix semantics',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});
  await f.ingest({action:'block',id:version.id,bucket:'00',rows:[row(1),row(2,'ÁLVAREZ, ANA')]});
  await f.ingest({action:'activate',id:version.id});
  const progress=await (await f.ingest({action:'begin',version})).json();
  assert.deepEqual(progress.search_pending,['00']);
  assert.equal((await f.ingest({action:'search-block',id:version.id,bucket:'00'})).status,200);
  assert.equal((await f.ingest({action:'search-block',id:version.id,bucket:'00'})).status,200);
  assert.deepEqual((await (await f.ingest({action:'begin',version})).json()).search_pending,[]);
  f.db.exec('DELETE FROM position_search_complete');
  await f.ingest({action:'begin',version});
  assert.ok(f.db.prepare('SELECT 1 FROM position_search_complete WHERE version_id=?').get(version.id),'repairs lost completion acknowledgement');
  for(const [query,count] of [['TINEZ CARLOS',1],['MARTINEZ MARTINEZ',1],['ALV',1],['25000020',1],['ZZZZZZ',0]]){
   const response=await f.call('/api/positions/search',{query});assert.equal(response.status,200,query);
   assert.equal((await response.json()).results.length,count);
  }
  assert.equal((await f.ingest({action:'activate',id:version.id})).status,200,'activation retry after lost response');
 }finally{f.db.close();}
});
test('incomplete or duplicate ranks cannot replace the active generation',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});
  assert.equal((await f.ingest({action:'block',id:version.id,bucket:'00',rows:[row(1)]})).status,200);
  assert.equal((await f.ingest({action:'activate',id:version.id})).status,409);
  assert.equal((await f.call('/api/positions')).status,503);
  const v={...version,id:'b'.repeat(64),parser_revision:'test',course:'2026-2027'};
  await f.ingest({action:'begin',version:v});
  assert.equal((await f.ingest({action:'block',id:v.id,bucket:'00',rows:[row(1),{...row(2),rank:1}]})).status,200);
  assert.equal((await f.ingest({action:'activate',id:v.id})).status,409);
 }finally{f.db.close();}
});
test('unauthenticated, mismatched bucket and duplicate IDs are rejected',async()=>{
 const f=setup();try{
  assert.equal((await f.call('/internal/positions',{action:'begin',version})).status,403);
  await f.ingest({action:'begin',version});
  for(const body of [{bucket:'ff',rows:[row(1)]},{bucket:'00',rows:[row(1),row(1)]}])assert.equal((await f.ingest({action:'block',id:version.id,...body})).status,400);
 }finally{f.db.close();}
});

test('validation does not activate, paging and empty/numeric searches remain bounded',async()=>{
 const f=setup();try{
  const v={...version,row_count:25,specialties:[{...version.specialties[0],count:25}]};
  await f.ingest({action:'begin',version:v});
  const rows=Array.from({length:25},(_,i)=>({...row(i+1),list_number:String(25000000+i)}));
  assert.equal((await f.ingest({action:'block',id:v.id,bucket:'00',rows})).status,200);
  assert.equal((await f.ingest({action:'validate',id:v.id})).status,200);
  assert.equal((await f.call('/api/positions')).status,503);
  assert.equal((await f.ingest({action:'activate',id:v.id})).status,200);
  const a=await (await f.call('/api/positions/search',{query:'MARTINEZ',specialty:'0590001'})).json();
  assert.equal(a.results.length,20);assert.equal(a.more,true);
  const b=await (await f.call('/api/positions/search',{query:'MARTINEZ',specialty:'0590001',cursor:a.next_cursor})).json();
  assert.equal(b.results.length,5);assert.equal(b.more,false);assert.equal(b.results[0].rank,21);
  for(const [query,count] of [['25000024',1],['NONEXISTENT',0],['CARLOS MARTINEZ MARTINEZ',20]]){
   const r=await f.call('/api/positions/search',{query});assert.equal(r.status,200);assert.equal((await r.json()).results.length,count);
  }
  f.db.prepare("UPDATE position_read_budget SET used=3000000 WHERE day=date('now')").run();
  assert.equal((await f.call('/api/positions/search',{query:'MARTINEZ'})).status,429);
  assert.equal((await f.call('/api/positions/'+rows[0].id)).status,429);
  assert.equal((await f.call('/api/positions')).status,200);
 }finally{f.db.close();}
});

test('legacy unindexed generation stays searchable and can be restored after block activation',async()=>{
 const f=setup();try{
  const old={...version,id:'f'.repeat(64),sha256:'f'.repeat(64)};
  f.db.prepare('INSERT INTO position_versions(id,metadata,ready) VALUES(?,?,1)').run(old.id,JSON.stringify(old));
  f.db.prepare('INSERT INTO position_search_status(version_id,ready) VALUES(?,0)').run(old.id);
  for(const r of [row(1),row(2)])f.db.prepare('INSERT INTO position_rows(version_id,id,specialty,list_number,search_name,rank,payload) VALUES(?,?,?,?,?,?,?)').run(old.id,r.id,r.specialty,r.list_number,r.name,r.rank,JSON.stringify(r));
  f.db.prepare('INSERT INTO position_active(singleton,version_id) VALUES(1,?)').run(old.id);
  assert.equal((await f.call('/api/positions/search',{query:'MARTINEZ'})).status,200);
  f.db.prepare('DELETE FROM position_search_status WHERE version_id=?').run(old.id);
  assert.equal((await f.ingest({action:'begin',version:old})).status,200);
  assert.equal(f.db.prepare('SELECT ready FROM position_search_status WHERE version_id=?').get(old.id).ready,0);
  assert.equal((await f.call('/api/positions/search',{query:'MARTINEZ'})).status,200);
  await f.ingest({action:'begin',version});
  await f.ingest({action:'block',id:version.id,bucket:'00',rows:[row(1),row(2)]});
  assert.equal((await f.ingest({action:'activate',id:version.id})).status,200);
  assert.equal((await f.ingest({action:'rollback',id:old.id})).status,200);
  assert.equal((await (await f.call('/api/positions')).json()).version.id,old.id);
 }finally{f.db.close();}
});

test('a late bucket invalidates the validation snapshot and never activates',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});
  await f.ingest({action:'block',id:version.id,bucket:'00',rows:[row(1),row(2)]});
  const batch=f.env.DB.batch;
  f.env.DB.batch=async ss=>{
   f.env.DB.batch=batch;
   const late={...row(1),id:'ff'+'1'.repeat(30),search_name:'MARTINEZ'};
   f.db.prepare('INSERT INTO position_blocks(version_id,bucket,payload) VALUES(?,?,?)').run(version.id,'ff',JSON.stringify([late]));
   return batch(ss);
  };
  assert.equal((await f.ingest({action:'activate',id:version.id})).status,409);
  assert.equal((await f.call('/api/positions')).status,503);
 }finally{f.db.close();}
});

test('a single client cannot consume the shared daily search quota',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});await f.ingest({action:'block',id:version.id,bucket:'00',rows:[row(1),row(2)]});
  await f.ingest({action:'activate',id:version.id});
  const handler=createGateway();
  const search=()=>handler(new Request('https://example.test/api/positions/search',{method:'POST',headers:{Origin:origin,'Content-Type':'application/json','CF-Connecting-IP':'192.0.2.1'},body:JSON.stringify({query:'MARTINEZ'})}),f.env);
  assert.equal((await search()).status,200);
  f.db.exec('UPDATE position_client_budget SET requests=120');
  assert.equal((await search()).status,429);
  const stored=f.db.prepare('SELECT client FROM position_client_budget').get().client;
  assert.match(stored,/^[a-f0-9]{64}$/);assert.ok(!stored.includes('192.0.2.1'));
  f.db.exec("DELETE FROM position_client_budget; UPDATE position_read_budget SET used=3000000 WHERE day=date('now')");
  assert.equal((await search()).status,429);
  assert.equal(f.db.prepare('SELECT COUNT(*) n FROM position_client_budget').get().n,0,'no public writes after global admission closes');
 }finally{f.db.close();}
});

test('a delayed activation retry cannot replace a newer active generation',async()=>{
 const f=setup();try{
  await f.ingest({action:'begin',version});
  await f.ingest({action:'block',id:version.id,bucket:'00',rows:[row(1),row(2)]});
  const newer={...version,id:'b'.repeat(64),sha256:'b'.repeat(64)};
  const batch=f.env.DB.batch;
  f.env.DB.batch=async statements=>{
   f.env.DB.batch=batch;
   assert.equal((await f.ingest({action:'activate',id:version.id})).status,200);
   await f.ingest({action:'begin',version:newer});
   await f.ingest({action:'block',id:newer.id,bucket:'00',rows:[row(1),row(2)]});
   assert.equal((await f.ingest({action:'activate',id:newer.id})).status,200);
   return batch(statements);
  };
  assert.equal((await f.ingest({action:'activate',id:version.id})).status,409);
  assert.equal((await (await f.call('/api/positions')).json()).version.id,newer.id);
 }finally{f.db.close();}
});
