const test=require('node:test'),assert=require('node:assert/strict');
const P=require('../web/position.js');
const version={id:'a'.repeat(64),sha256:'a'.repeat(64),scope:'published_list',coverage:'baseline_only',published_at:'2026-07-22',checked_at:'2026-10-02T12:00:00Z',source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208095'};
const person={id:'1'.repeat(32),name:'PRUEBA, ANA',specialty:'0590001',specialty_name:'FILOSOFIA',body_name:'SECUNDARIA',block:'68',block_name:'Bloque 1',list_number:'25000010',rank:7,page:2};
const catalog={version,specialties:[{code:'0590001',name:'FILOSOFIA',body:'SECUNDARIA',count:10}],refresh_available:false};

test('exact-name results can continue across publications and changing query cancels paging',async()=>{
  let finish;
  const model=P.createModel({request:async(path,body)=>path.endsWith('/search')?
    body.offset?new Promise(resolve=>{finish=resolve;}):{version,results:[person],more:true,next_offset:20}:catalog});
  await model.init();await model.search('','Prueba');
  assert.match(P.render(model.state),/Ver más coincidencias/);
  assert.equal(typeof model.loadMore,'function');
  const request=model.loadMore();
  finish({version,results:[{...person,id:'2'.repeat(32)}],more:false,next_offset:null});await request;
  assert.equal(model.state.results.length,2);
  await model.search('','Prueba');const pending=model.loadMore();model.editQuery('Otra');
  finish({version,results:[person],more:false,next_offset:null});await pending;
  assert.equal(model.state.results.length,0);assert.equal(model.state.query,'Otra');
});

test('bilingual award shows its own dated destination without a fabricated ordinal',async()=>{
  const doc={content_id:'209126',kind:'award',sha256:'d'.repeat(64),published_at:'2026-09-24',pages:25,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=209126'};
  const v={...version,id:'e'.repeat(64),coverage:'multi_source',documents:[doc]};
  const p={...person,record_type:'award',specialty:'0590I09',specialty_name:'DIBUJO / INGLES',source_id:'209126',rank:null,block:'',block_name:'',destination:'IES DE PRUEBA · MURCIA',workload:'10 horas'};
  assert.doesNotThrow(()=>P.validateResponse({version:v,person:p}));
  assert.throws(()=>P.validateResponse({version:v,person:{...p,rank:97}}));
  assert.throws(()=>P.validateResponse({version:v,person:{...p,source_id:'99999'}}));
  const model=P.createModel({request:async path=>path.endsWith('/search')?{version:v,results:[p]}:{...catalog,version:v,specialties:[{code:p.specialty,name:p.specialty_name,body:'SECUNDARIA',count:1}]}});
  await model.init();await model.search('','Prueba');assert.equal(model.state.error,'');
  const search=P.render(model.state);assert.match(search,/Adjudicación/);assert.match(search,/24 sept 2026/);
  const html=P.render({...model.state,person:p,version:v});
  assert.match(html,/IES De Prueba/);assert.match(html,/10 horas/);assert.match(html,/24 sept 2026/);
  assert.match(html,/IDCONTENIDO=209126.*#page=2/);
  assert.doesNotMatch(html,/Puesto en la lista|<small>º|22 jul 2026/);
});

test('destination display separates municipality and does not repeat its source suffix',()=>{
  assert.equal(typeof P.awardDestination,'function');
  assert.deepEqual(P.awardDestination('IES LA FLORIDA (TORRES DE COTILLAS (LAS)) · TORRES DE COTILLAS (LAS)'),
    {center:'IES La Florida',municipality:'Torres De Cotillas (Las)'});
});
test('amended position points to its actual PDF and explains consolidated coverage only in detail',()=>{
  const corrected={...version,id:'b'.repeat(64),coverage:'reviewed_amendments',amendments:[{content_id:'208249',sha256:'c'.repeat(64),signed_at:'2026-07-28',pages:2,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208249'}]};
  const p={...person,page:1,source_id:'208249'};
  assert.doesNotThrow(()=>P.validateResponse({version:corrected,person:p}));
  const html=P.render({catalog:{...catalog,version:corrected},version:corrected,person:p,results:[],busy:false});
  assert.match(html,/IDCONTENIDO=208249.*#page=1/);
  assert.doesNotMatch(html,/correcciones posteriores.*no están incorporados/);
  assert.match(html,/No es la posición actual entre disponibles/);
  assert.throws(()=>P.validateResponse({version:corrected,person:{...p,source_id:'999999'}}));
});
function setup(){
  assert.equal(typeof P.createModel,'function','Missing personal-position controller');
  const saved=new Map(),calls=[];let fail=false,missing=false;
  const model=P.createModel({storage:{getItem:k=>saved.get(k),setItem:(k,v)=>saved.set(k,v),removeItem:k=>saved.delete(k)},
    request:async(path,body)=>{calls.push({path,body});if(fail)throw Error('offline');if(path.endsWith(person.id)&&missing)throw Object.assign(Error('missing'),{status:404});
      return path.endsWith('/search')?{version,results:[person],more:false}:path.endsWith(person.id)?{version,person}:catalog;}});
  return {model,saved,calls,setFail:()=>fail=true,setMissing:()=>missing=true};
}
test('one matching person still requires confirmation before saving or showing a rank',async()=>{
  const {model,saved}=setup();await model.init();await model.search('0590001','PRUEBA');
  assert.equal(model.state.person,null);assert.equal(saved.size,0);
  model.choose(person.id);assert.equal(model.state.person,null);
  await model.confirm();assert.equal(model.state.person.rank,7);assert.equal(saved.size,1);
  const html=P.render(model.state);assert.match(html,/7/);assert.match(html,/lista publicada/);assert.doesNotMatch(html,/disponibles: 7/);
});

test('a name can be searched without choosing a specialty and each match identifies its specialty',async()=>{
  const f=setup();await f.model.init();await f.model.search('','Prueba Ana');
  assert.equal(f.model.state.results.length,1);assert.equal(f.model.state.error,'');
  assert.equal(f.saved.size,0);
  const html=P.render(f.model.state);
  assert.match(html,/Todas las especialidades/);assert.match(html,/Filosofia/);
  assert.doesNotMatch(html,/<select[^>]+required/);
});

test('editing a name invalidates a pending result before the next search is sent',async()=>{
  let resolve;const pending=new Promise(r=>resolve=r);
  const model=P.createModel({request:async(path)=>path.endsWith('/search')?pending:catalog});
  await model.init();const search=model.search('','old');model.editQuery('new');
  resolve({version,results:[person],more:false});await search;
  assert.equal(model.state.query,'new');assert.equal(model.state.results.length,0);assert.equal(model.state.busy,false);
  assert.equal(model.state.searched,false);
});

test('specialty picker is searchable without accents and distinguishes teaching bodies',()=>{
  const options=[{code:'0590009',name:'DIBUJO',body:'SECUNDARIA'},{code:'0595508',name:'DIBUJO TÉCNICO',body:'ARTES PLÁSTICAS'}];
  assert.deepEqual(P.filterSpecialties(options,'dibujo plasticas').map(s=>s.code),['0595508']);
  assert.deepEqual(P.filterSpecialties(options,'0590009').map(s=>s.code),['0590009']);
});

test('empty results offer recovery and never claim that the person is excluded',async()=>{
  const model=P.createModel({request:async(path)=>path.endsWith('/search')?{version,results:[],more:false}:catalog});
  await model.init();await model.search('0590001','Prueba');
  assert.match(P.render(model.state),/Buscar en todas las especialidades/);
  await model.search('','Prueba');
  assert.match(P.render(model.state),/No hay coincidencias en esta publicación/);
  assert.match(P.render(model.state),/Consultar en Educarm/);
  assert.doesNotMatch(P.render(model.state),/excluid[oa]/i);
});
test('failed reload retains the dated result with an error, but a missing row hides its old rank',async()=>{
  const f=setup();await f.model.init();await f.model.search('0590001','PRUEBA');f.model.choose(person.id);await f.model.confirm();
  f.setFail();await f.model.refresh();assert.equal(f.model.state.person.rank,7);assert.ok(f.model.state.error);
  const g=setup();await g.model.init();await g.model.search('0590001','PRUEBA');g.model.choose(person.id);await g.model.confirm();
  g.setMissing();await g.model.refresh();assert.equal(g.model.state.person,null);assert.ok(g.model.state.error);
});
test('an older search response cannot overwrite a more recent search',async()=>{
  assert.equal(typeof P.createModel,'function');
  let resolve;const old=new Promise(r=>resolve=r);
  const model=P.createModel({storage:null,request:async(path,body)=>body?.query==='OLD'?old:body?{version,results:[],more:false}:catalog});
  await model.init();const first=model.search('0590001','OLD');await model.search('0590001','NEW');
  resolve({version,results:[person],more:false});await first;assert.equal(model.state.results.length,0);
});
test('HTML escapes names and rejects a response claiming a different kind of rank',()=>{
  assert.equal(typeof P.render,'function');
  const html=P.render({catalog,version,person:{...person,name:'<img src=x onerror=alert(1)>'},results:[],busy:false});
  assert.doesNotMatch(html,/<img src=x/);
  assert.equal(typeof P.validateResponse,'function');
  assert.throws(()=>P.validateResponse({version:{...version,scope:'available'},person}));
  assert.throws(()=>P.validateResponse({version,person:{...person,rank:-1}}));
});
test('failed or partial source checks cannot be presented as successful reloads',async()=>{
  for(const status of ['failed','partial']){
    const model=P.createModel({storage:null,requestRefresh:async()=>({status}),request:async()=>({...catalog,refresh_available:true})});
    await model.init();await model.refresh();assert.ok(model.state.error);assert.equal(model.state.message,'');
  }
});
test('a completed vacancy job does not certify an unchanged personal-list check',async()=>{
  const model=P.createModel({storage:null,requestRefresh:async()=>({status:'completed'}),request:async(path)=>path.endsWith(person.id)?{version,person}:{...catalog,refresh_available:true}});
  await model.init();model.state.person=person;model.state.version=version;
  await model.refresh();assert.ok(model.state.error);assert.equal(model.state.message,'');
});
test('only a personal-list check made after the requested job can confirm that job',async()=>{
  for(const checked of ['2026-10-02T12:10:00Z','2026-10-02T12:30:00Z']){
    const fresh={...version,checked_at:checked};
    const model=P.createModel({storage:null,requestRefresh:async()=>({status:'completed',created_at:'2026-10-02T12:20:00Z'}),
      request:async path=>path.endsWith(person.id)?{version:fresh,person}:{...catalog,refresh_available:true}});
    await model.init();model.state.person=person;model.state.version=version;await model.refresh();
    assert.equal(Boolean(model.state.error),checked==='2026-10-02T12:10:00Z');
  }
});


test('result dates come from the returned generation when it changes after loading the catalog',async()=>{
  const fresh={...version,id:'f'.repeat(64),published_at:'2026-08-04',coverage:'reviewed_amendments',amendments:[{content_id:'208249',sha256:'c'.repeat(64),signed_at:'2026-07-28',pages:2,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208249'}]};
  const model=P.createModel({request:async(path)=>path.endsWith('/search')?{version:fresh,results:[person],more:false}:catalog});
  await model.init();await model.search('','Prueba');
  assert.match(P.render(model.state),/Lista del 4 ago 2026 · con correcciones/);
  assert.doesNotMatch(P.render(model.state),/Lista del 22 jul 2026/);
});
