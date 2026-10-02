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
