import test from 'node:test';
import assert from 'node:assert/strict';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync, existsSync} from 'node:fs';
import {createGateway} from '../gateway/worker.mjs';

const origin='https://carlosmartinezfyd.github.io', secret='s'.repeat(48);
const version={id:'a'.repeat(64),sha256:'a'.repeat(64),published_at:'2026-07-22',checked_at:'2026-10-02T12:00:00Z',
  source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208095',row_count:2,scope:'published_list',coverage:'baseline_only',
  specialties:[{code:'0590001',name:'FILOSOFIA',body:'SECUNDARIA',count:2}]};
const row=(n,name='PRUEBA, ANA')=>({id:String(n).padStart(32,'0'),specialty:'0590001',specialty_name:'FILOSOFIA',body_name:'SECUNDARIA',
  block:'68',block_name:'Bloque 1',list_number:`250000${n}0`,name,search_name:name,rank:n,page:2});

function setup(){
  const db=new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../gateway/schema.sql',import.meta.url),'utf8'));
  const schema=new URL('../gateway/positions.sql',import.meta.url);
  if(existsSync(schema))db.exec(readFileSync(schema,'utf8'));
  const binding={withSession:()=>binding,prepare:sql=>{const statement={args:[],bind(...args){this.args=args;return this;},
    async first(){return db.prepare(sql).get(...this.args)||null;},async all(){return {results:db.prepare(sql).all(...this.args)};},
    async run(){return {meta:{changes:db.prepare(sql).run(...this.args).changes}};}};return statement;},
    async batch(statements){db.exec('BEGIN');try{const results=[];for(const s of statements)results.push(await s.run());db.exec('COMMIT');return results;}catch(e){db.exec('ROLLBACK');throw e;}}};
  const handler=createGateway();
  async function call(path,body,auth=false){return handler(new Request('https://gateway.example'+path,{method:body?'POST':'GET',
    headers:{Origin:origin,'Content-Type':'application/json',...(auth?{Authorization:`Bearer ${secret}`}:{})},
    ...(body?{body:JSON.stringify(body)}:{})}),{DB:binding,ALLOWED_ORIGIN:origin,POSITION_INGEST_TOKEN:secret});}
  const ingest=(body)=>call('/internal/positions',body,true);
  return {db,call,ingest};
}

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
