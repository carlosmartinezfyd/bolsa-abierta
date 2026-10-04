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
  assert.match(html,/Todas las listas y funciones/);assert.match(html,/Filosofia/);
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
  assert.match(P.render(model.state),/Buscar en todas las listas y funciones/);
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
  let catalogs=0;const model=P.createModel({request:async(path)=>path.endsWith('/search')?{version:fresh,results:[person],more:false}:++catalogs===1?catalog:{...catalog,version:fresh}});
  await model.init();await model.search('','Prueba');
  assert.match(P.render(model.state),/Lista del 4 ago 2026 · con correcciones/);
  assert.doesNotMatch(P.render(model.state),/Lista del 22 jul 2026/);
});

test('Maestros ordinal belongs to its unique list and correction has its own evidence',()=>{
  const correction={content_id:'208782',sha256:'c'.repeat(64),signed_at:'2026-08-18',pages:3,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208782'};
  const d={content_id:'208253',kind:'maestros_roster',rank_scope:'maestros_unique_list',sha256:'d'.repeat(64),published_at:'2026-07-28',pages:80,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208253',amendments:[correction]};
  const v={...version,coverage:'multi_source',documents:[d]};
  const p={...person,record_type:'list',specialty:'0597',specialty_name:'Lista única de Maestros',body_name:'CUERPO DE MAESTROS',rank_scope:'maestros_unique_list',roster_id:'208253',source_id:'208782',page:2,habilitations:[{code:'031',name:'EDUCACIÓN INFANTIL'}]};
  assert.doesNotThrow(()=>P.validateResponse({version:v,person:p}));
  assert.throws(()=>P.validateResponse({version:v,person:{...p,rank_scope:'specialty'}}));
  assert.throws(()=>P.validateResponse({version:v,person:{...p,page:4}}));
  const html=P.render({catalog:{...catalog,version:v},version:v,person:p,results:[],busy:false});
  assert.match(html,/Ordinal en la lista única de Maestros/);assert.match(html,/Educación Infantil/);assert.match(html,/031/);
  assert.match(html,/IDCONTENIDO=208782.*#page=2/);assert.match(html,/28 jul 2026/);assert.match(html,/18 ago 2026/);
  assert.doesNotMatch(html,/antes en esta especialidad|puesto actual|especialidad oficial/);
});
test('provisional award reservation and incorporation remain separate dated facts',()=>{
  const d={content_id:'209126',kind:'award',sha256:'d'.repeat(64),published_at:'2026-09-24',pages:25,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=209126',title:'Adjudicación definitiva'};
  const v={...version,coverage:'multi_source',documents:[d]},p={...person,record_type:'award',source_id:'209126',rank:null,destination:'IES PRUEBA · MURCIA',workload:'Completa',appointment_status:'provisional',incorporation_at:'2026-09-28'};
  const html=P.render({catalog:{...catalog,version:v},version:v,person:p,results:[],busy:false});
  assert.match(html,/Reserva provisional/);assert.match(html,/Incorporación.*28 sept 2026/);assert.match(html,/24 sept 2026/);assert.doesNotMatch(html,/puesto.*no.*disponible|médic/i);
  assert.throws(()=>P.validateResponse({version:v,person:{...p,appointment_status:'final'}}));
  assert.throws(()=>P.validateResponse({version:v,person:{...p,incorporation_at:'2026-13-32'}}));
});
test('explicit confirmation explains browser storage and selected ficha offers deletion',async()=>{
  const f=setup();await f.model.init();await f.model.search('','Prueba');f.model.choose(person.id);
  assert.match(P.render(f.model.state),/Al confirmar.*este navegador/);assert.match(P.render(f.model.state),/Confirmar y recordar/);
  await f.model.confirm();assert.match(P.render(f.model.state),/Borrar ficha guardada/);f.model.clear();assert.equal(f.saved.size,0);
});

test('source coverage counts records instead of unique people and escapes verified habilitation labels',()=>{
  const html=P.render({catalog:{...catalog,version:{...version,row_count:13045}},query:'',results:[],busy:false});
  assert.match(html,/13\.045 registros incorporados/);assert.match(html,/una persona puede tener varios registros/);assert.match(html,/códigos del filtro incluyen listas y funciones/);
  const d={content_id:'208253',kind:'maestros_roster',rank_scope:'maestros_unique_list',sha256:'d'.repeat(64),published_at:'2026-07-28',pages:80,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208253'};
  const v={...version,coverage:'multi_source',documents:[d]},p={...person,specialty:'0597',rank_scope:'maestros_unique_list',roster_id:'208253',source_id:'208253',habilitations:[{code:'031',name:'<img src=x onerror=alert(1)>'}]};
  const shown=P.render({catalog:{...catalog,version:v},version:v,person:p,busy:false});assert.doesNotMatch(shown,/<img src=x/);assert.match(shown,/&lt;img/i);
});
test('unknown award appointment status is never inferred from definitive publication metadata',()=>{
  const d={content_id:'209126',kind:'award',sha256:'d'.repeat(64),published_at:'2026-09-24',pages:25,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=209126',title:'Adjudicación definitiva'},v={...version,coverage:'multi_source',documents:[d]},p={...person,record_type:'award',source_id:'209126',rank:null,destination:'IES PRUEBA · MURCIA',workload:'Completa'};
  const html=P.render({catalog:{...catalog,version:v},version:v,person:p,busy:false});assert.match(html,/no acredita aquí el carácter definitivo o provisional/);assert.doesNotMatch(html,/Nombramiento definitivo acreditado|Reserva provisional|Incorporación:/);
});

test('pending search index guides complete numeric lookup without retrying names or masking other failures',async()=>{
  assert.equal(typeof P.readResponse,'function');let calls=0;
  const model=P.createModel({request:async(path,body)=>{
    if(!path.endsWith('/search'))return catalog;calls++;
    if(body.query==='25000010')return {version,results:[person],more:false};
    return P.readResponse({ok:false,status:503,json:async()=>({index_pending:true,error:'<img src=x onerror=alert(1)>'})});
  }});
  await model.init();await model.search('','Prueba');assert.equal(calls,1);assert.match(model.state.error,/índice de búsqueda se está preparando/);assert.match(P.render(model.state),/número completo de lista/);assert.doesNotMatch(P.render(model.state),/<img src=x/);assert.equal(model.state.searched,false);
  await model.search('','25000010');assert.equal(calls,2);assert.equal(model.state.error,'');assert.equal(model.state.results.length,1);
  const other=P.createModel({request:async(path)=>path.endsWith('/search')?P.readResponse({ok:false,status:503,json:async()=>({error:'offline'})}):catalog});await other.init();await other.search('','Prueba');assert.doesNotMatch(other.state.error,/índice|número completo/);assert.match(other.state.error,/No se ha podido consultar/);
});

test('a null conservative origin-check date preserves published evidence without inventing freshness',()=>{
  const v={...version,checked_at:null};assert.doesNotThrow(()=>P.validateResponse({version:v,person}));
  const html=P.render({catalog:{...catalog,version:v},version:v,person,busy:false});assert.match(html,/Última comprobación de la generación.*Sin fecha acreditada/s);assert.match(html,/22 jul 2026/);assert.doesNotMatch(html,/1970|4 oct 2026/);
  assert.throws(()=>P.validateResponse({version:{...v,checked_at:'invalid'},person}));
});

function maestroGeneration(){
  const d={content_id:'208253',kind:'maestros_roster',rank_scope:'maestros_unique_list',sha256:'d'.repeat(64),published_at:'2026-07-28',pages:80,source_url:'https://www.carm.es/web/descarga?IDCONTENIDO=208253'};
  const fresh={...version,id:'b'.repeat(64),coverage:'multi_source',documents:[d]};
  const row={...person,record_type:'list',specialty:'0597',specialty_name:'Lista única de Maestros',body_name:'CUERPO DE MAESTROS',rank_scope:'maestros_unique_list',roster_id:'208253',source_id:'208253',habilitations:[{code:'031',name:'EDUCACIÓN INFANTIL'}]};
  const fullCatalog={...catalog,version:fresh,specialties:[...catalog.specialties,{code:'0597',name:'Lista única de Maestros',body:'CUERPO DE MAESTROS',count:10},{code:'0595508',name:'DIBUJO TÉCNICO',body:'ARTES PLÁSTICAS',count:4}]};
  return {fresh,row,fullCatalog};
}
test('a new Maestros generation refreshes the full catalog before accepting a newly added scope',async()=>{
  const {fresh,row,fullCatalog}=maestroGeneration();let catalogs=0;
  const model=P.createModel({request:async path=>path.endsWith('/search')?{version:fresh,results:[row],more:false}:++catalogs===1?catalog:fullCatalog});
  await model.init();await model.search('','Prueba');assert.equal(model.state.error,'');assert.equal(catalogs,2);assert.equal(model.state.results[0].specialty,'0597');assert.equal(model.state.catalog.version.id,fresh.id);assert.equal(model.state.searchVersion.id,fresh.id);assert.equal(model.state.catalog.specialties.length,3);assert.match(P.render(model.state),/Dibujo Técnico|Dibujo TÉcnico/);
});
test('editing a query during generation catalog refresh cancels both the results and catalog application',async()=>{
  const {fresh,row,fullCatalog}=maestroGeneration();let catalogs=0,finish,started;const refreshing=new Promise(resolve=>started=resolve);
  const model=P.createModel({request:async path=>path.endsWith('/search')?{version:fresh,results:[row],more:false}:++catalogs===1?catalog:new Promise(resolve=>{finish=resolve;started();})});
  await model.init();const pending=model.search('','Prueba');await refreshing;model.editQuery('Otra');finish(fullCatalog);await pending;
  assert.equal(model.state.query,'Otra');assert.equal(model.state.catalog.version.id,version.id);assert.deepEqual(model.state.results,[]);assert.equal(model.state.searched,false);assert.equal(model.state.busy,false);assert.equal(model.state.error,'');
});
test('a catalog from a different generation cannot be applied to a valid search response',async()=>{
  const {fresh,row,fullCatalog}=maestroGeneration();let catalogs=0;
  const model=P.createModel({request:async path=>path.endsWith('/search')?{version:fresh,results:[row],more:false}:++catalogs===1?catalog:{...fullCatalog,version:{...fresh,id:'c'.repeat(64)}}});
  await model.init();await model.search('','Prueba');assert.match(model.state.error,/publicaciones han cambiado.*Buscar/);assert.equal(model.state.catalog.version.id,version.id);assert.deepEqual(model.state.results,[]);assert.equal(model.state.searched,false);
});
