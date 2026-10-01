const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const BA = require('../web/core.js');
const context = {BA, window: {}, URL};
vm.createContext(context);
vm.runInContext(fs.readFileSync(require.resolve('../web/ui.js'), 'utf8'), context);
const U = context.window.BAUI;
context.BAUI = U;
vm.runInContext(fs.readFileSync(require.resolve('../web/views.js'), 'utf8'), context);
const doc = (id, date, rows) => ({id, sha256:id, status:'approved', published_at:date, rows, warnings:[]});
const row = (id, code='A') => ({id, function_code:code, body_code:'0590', municipality:'Murcia', workload:'full', language:'No', cupo:'VP', itinerant:'N', quantity:1});

test('changing copy clears only categorical filters missing in the new copy', () => {
  assert.deepEqual(BA.normalizeFilters({q:'matemáticas',function_code:'old',cupo:'VS',workload:'full'}, [row('x')]), {q:'matemáticas',workload:'full'});
});
test('saved groups retain matching rows from every document with its own date', () => {
  const docs=[doc('a','2026-09-01',[row('a:1:1')]),doc('b','2026-09-30',[row('b:1:1')])];
  const groups=BA.savedGroups(docs, ['a:1:1','b:1:1']);
  assert.deepEqual(groups.map(g=>[g.document.id,g.document.published_at,g.rows.length]),[['a','2026-09-01',1],['b','2026-09-30',1]]);
});
test('a reused official URL cannot mark a new revision incorporated', () => {
  assert.equal(BA.isPendingNotice({kind:'vacancies',pdf_url:'https://www.carm.es/a.pdf',document_id:'new'}, [{id:'old',status:'approved',source_url:'https://www.carm.es/a.pdf'}]),true);
  assert.equal(BA.isPendingNotice({kind:'vacancies',document_id:'old'}, [{id:'old',status:'approved'}]),false);
  assert.equal(BA.isPendingNotice({kind:'vacancies',pdf_url:'https://www.carm.es/a.pdf'}, [{id:'old',status:'approved',source_url:'https://www.carm.es/a.pdf'}]),true);
});
test('PDF download uses archived bytes and separate origin when archive missing', () => {
  assert.equal(U.pdfUrl({source_url:'https://www.carm.es/latest.pdf'}),'');
  assert.match(U.pdfLink({source_url:'https://www.carm.es/latest.pdf'}),/Copia no conservada/);
  assert.equal(U.pdfUrl({artifact_url:'documents/a.pdf'},3),'documents/a.pdf#page=3');
  assert.equal(U.pdfUrl({artifact_url:'/api/documents/a.pdf'},2),'/api/documents/a.pdf#page=2');
});
test('unsafe link schemes, credentials and path traversal are rejected', () => {
  for(const url of ['javascript:alert(1)','data:a','//evil.test/a','../a.pdf','documents/../secret','documents/%2e%2e/a','https://user:pass@example.com/a','documents/a\\b']) assert.equal(BA.safeURL(url),'',url);
  assert.equal(BA.safeURL('https://www.carm.es/a.pdf'),'https://www.carm.es/a.pdf');
  assert.equal(U.pdfUrl({artifact_url:'javascript:alert(1)'}),'');
});
test('API composition supports relative hosting and configured HTTPS gateway', () => {
  assert.equal(BA.composeAPIURL('state',{}),'api/state');
  assert.equal(BA.composeAPIURL('state',{apiBase:'https://gateway.example/base/'}),'https://gateway.example/base/api/state');
  for(const apiBase of ['http://gateway.example','https://user:pass@example.com','//evil.test','https://gateway.example/?x=1']) assert.throws(()=>BA.composeAPIURL('state',{apiBase}));
});
test('load state falls back to a static snapshot with honest capabilities', async () => {
  const paths=[];
  const result=await BA.loadState(async url=>{paths.push(url);return url==='api/state'?{ok:false}:{ok:true,json:async()=>({documents:[],catalog:{},events:[],changes:[],mode:'server',capabilities:{source_check:'available'}})};},{});
  assert.deepEqual(paths,['api/state','data/state.json']);
  assert.equal(result.mode,'static');
  assert.equal(result.capabilities.source_check,'snapshot_only');
});
test('refresh uses bounded job protocol and returns terminal partial status', async () => {
  const calls=[],jobs=[{id:'job',status:'queued'},{id:'job',status:'running'},{id:'job',status:'partial'}];
  const result=await BA.refreshSource(async (url,options)=>{calls.push([url,options]);return {ok:true,json:async()=>jobs.shift()};},{},()=>{},async()=>{});
  assert.equal(result.status,'partial');
  assert.equal(calls[0][0],'api/refresh');
  assert.equal(calls[0][1].body,'{}');
  assert.equal(calls[0][1].headers['X-BA-Refresh'],'1');
  assert.equal(calls[1][0],'api/refresh/job');
});
const seed=JSON.parse(fs.readFileSync(require.resolve('../data/seed-state.json'),'utf8'));
const model=()=>({state:BA.validateState({...seed,mode:'static',capabilities:{source_check:'snapshot_only'},freshness:{status:'partial',last_attempt_at:'2026-10-01T08:00:00Z',last_success_at:'2026-09-30T08:00:00Z'}}),selectedDoc:seed.current_id,prefs:{favorites:[],functions:[],lastSeen:null},filters:{},page:1,view:'sources'});
test('static sources only offers snapshot refresh and separates successful and attempted checks',()=>{
 const html=context.window.BAV.shell(model());
 assert.match(html,/Buscar copia actualizada/);
 assert.match(html,/Último intento/);
 assert.match(html,/Última comprobación completa/);
 assert.doesNotMatch(html,/Importar PDF|servidor local|ZIP|Revisar e incorporar/);
});
test('saved search displays each document group without combining vacancy totals',()=>{
 const m=model();m.view='vacancies';m.onlySaved=true;m.prefs.favorites=seed.documents.map(d=>d.rows[0].id);
 const html=context.window.BAV.results(m);
 for(const d of seed.documents) assert.match(html,new RegExp(BA.escape(BA.date(d.published_at))));
 assert.match(html,/Registros guardados por copia/);
 assert.doesNotMatch(html,/plazas<\/strong> en/);
});
async function controller(fetcher){
 const listeners={},app={innerHTML:''},toast={textContent:'',classList:{add(){},remove(){}}},dialog={addEventListener(){},close(){},open:false};
 const document={getElementById:id=>({app,toast,'detail-dialog':dialog})[id]||null,addEventListener:(kind,handler)=>{listeners[kind]=handler;}};
 const sandbox={BA,BAUI:U,BAV:context.window.BAV,document,fetch:fetcher,localStorage:{getItem:()=>null,setItem(){}},location:{hash:''},history:{replaceState(){}},setTimeout:()=>1,clearTimeout(){},window:{BA_CONFIG:{},BOOTSTRAP:{documents:[]},addEventListener(){},scrollTo(){}}};
 vm.createContext(sandbox);vm.runInContext(fs.readFileSync(require.resolve('../web/app.js'),'utf8'),sandbox);
 await new Promise(resolve=>setImmediate(resolve));
 return {app,toast,listeners,click:async()=>{const button={disabled:false,dataset:{action:'sync'},innerHTML:''};await listeners.click({target:{closest:selector=>selector==='[data-action]'?button:null}});await new Promise(resolve=>setImmediate(resolve));}};
}
test('controller loads static snapshot and reloads snapshot without origin POST',async()=>{
 const calls=[];const c=await controller(async(url,options)=>{calls.push([url,options]);return url==='api/state'?{ok:false,status:404,json:async()=>({})}:{ok:true,json:async()=>seed};});
 assert.match(c.app.innerHTML,/Vacantes sin cubrir/);
 await c.click();
 assert.deepEqual(calls.map(c=>c[0]),['api/state','data/state.json','data/state.json']);
 assert.match(c.toast.textContent,/no se han comprobado/i);
});
test('controller keeps prior visible data after refresh transport failure',async()=>{
 const state={...seed,mode:'server',capabilities:{source_check:'available'}};
 const c=await controller(async url=>{if(url==='api/state')return {ok:true,json:async()=>state};throw Error('Fallo de conexión');});
 const before=c.app.innerHTML;
 await c.click();
 assert.equal(c.app.innerHTML,before);
 assert.match(c.toast.textContent,/Fallo de conexión/);
});
test('CSV preserves the document date, hash, origin and archived link',()=>{
 const text=BA.csv([{...row('a:1:1'),document_id:'a',document_published_at:'2026-09-30',document_sha256:'a',source_url:'https://www.carm.es/source.pdf',artifact_url:'documents/a.pdf'}]);
 assert.match(text,/Fecha del documento/);assert.match(text,/2026-09-30/);assert.match(text,/documents\/a.pdf/);
});
test('saved copies do not show merged headline vacancy statistics',()=>{
 const m=model();m.view='vacancies';m.onlySaved=true;
 assert.doesNotMatch(context.window.BAV.shell(m),/class="stats"/);
});
test('a completed refresh advances the currently viewed latest copy',async()=>{
 const initial={...seed,mode:'server',capabilities:{source_check:'available'}};
 const id='c'.repeat(64),added={...seed.documents[0],id,sha256:id,published_at:'2026-10-01T12:00:00Z',rows:[{...seed.documents[0].rows[0],id:id+':1:1',center:'NUEVO CENTRO VALIDADO'}]};
 const updated={...initial,current_id:id,documents:[added,...initial.documents]};let loads=0;
 const c=await controller(async url=>({ok:true,json:async()=>url==='api/refresh'?{id:'job',status:'completed'}:++loads===1?initial:updated}));
 await c.click();assert.match(c.app.innerHTML,/Nuevo Centro Validado/);
});
test('published relative archives remain on the web host with an external API gateway',()=>{
 context.window.BA_CONFIG={apiBase:'https://gateway.example'};
 assert.equal(U.pdfUrl({artifact_url:'documents/a.pdf'}),'documents/a.pdf#page=1');
 assert.equal(U.pdfUrl({artifact_url:'/api/documents/a.pdf'}),'https://gateway.example/api/documents/a.pdf#page=1');
 context.window.BA_CONFIG={};
});
test('failed same-URL revision remains pending even with an older incorporated document',()=>{
 for(const status of ['fetch_failed','extraction_failed','detected_not_read','pending'])assert.equal(BA.isPendingNotice({kind:'vacancies',status,document_id:'old'},[{id:'old',status:'approved'}]),true,status);
});
test('announcements outside the vacancy parser scope are informational',()=>{
 assert.equal(BA.isPendingNotice({kind:'announcement',status:'detected_not_read'},[]),false);
 const m=model();m.view='acts';m.state.catalog.notices=[{id:'info',kind:'announcement',title:'Aviso oficial',status:'detected_not_read'}];
 assert.match(context.window.BAV.shell(m),/Aviso informativo/);
});
test('refresh continues through a nineteen minute deployment queue',async()=>{
 let clock=0;const waits=[];
 const result=await BA.refreshSource(async()=>({ok:true,json:async()=>({id:'job',status:clock>=19*60*1000?'completed':'running'})}),{},()=>{},async ms=>{waits.push(ms);clock+=ms;},{now:()=>clock});
 assert.equal(result.status,'completed');assert.equal(clock,19*60*1000);assert.ok(waits.every(ms=>ms===10000));
});
test('refresh twenty minute deadline reports pending without marking the job failed',async()=>{
 let clock=0,lastStatus;
 await assert.rejects(BA.refreshSource(async()=>({ok:true,json:async()=>({id:'job',status:'queued'})}),{},job=>{lastStatus=job.status;},async ms=>{clock+=ms;},{now:()=>clock}),error=>error.code==='refresh_pending'&&/sigue pendiente.*vuelve a cargar/i.test(error.message));
 assert.equal(clock,20*60*1000);assert.equal(lastStatus,'queued');
});
test('refresh deadline includes the time spent fetching job status',async()=>{
 let clock=0,calls=0;
 await assert.rejects(BA.refreshSource(async()=>{calls++;clock+=1000;return {ok:true,json:async()=>({id:'job',status:'running'})};},{},()=>{},async ms=>{clock+=ms;},{now:()=>clock}),error=>error.code==='refresh_pending');
 assert.equal(clock,20*60*1000);assert.ok(calls<=110);
});
test('sources and favorites explain a bounded public history window',()=>{
 const m=model();m.state.history_window={omitted_documents:4,note:'El historial completo se conserva en el almacén privado.'};
 for(const view of ['sources','profile']){m.view=view;assert.match(context.window.BAV.shell(m),/Historial publicado limitado/);assert.match(context.window.BAV.shell(m),/historial completo se conserva/);}
 m.onlySaved=true;assert.match(context.window.BAV.results(m),/favoritos.*copias.*no incluidas/i);
});
test('approved historical metadata keeps an omitted copy incorporated',()=>{
 const notice={kind:'vacancies',document_id:'old',status:'approved'},history=[{id:'old',status:'approved'}];
 assert.equal(BA.isPendingNotice(notice,[],history),false);
 assert.equal(BA.isPendingNotice({...notice,status:'fetch_failed'},[],history),true);
 assert.equal(BA.isPendingNotice({...notice,status:'extraction_failed'},[],history),true);
 const m=model();m.state.documents=[];m.state.history_documents=history;m.state.catalog.notices=[notice];m.view='acts';
 assert.match(context.window.BAV.shell(m),/Documento incorporado/);
 assert.doesNotMatch(context.window.BAV.shell(m),/Documento sin incorporar/);
 m.view='sources';assert.match(context.window.BAV.shell(m),/0 publicación\(es\) sin incorporar/);
});
test('official source status matches reordered and encoded equivalent PDF query parameters',()=>{
 const m=model();m.view='sources';
 m.state.catalog.sources=[{id:'carm-pdf',name:'PDF oficial',url:'https://www.carm.es/web/descarga?ALIAS=ARCH&IDCONTENIDO=209318&RASTRO=c77%24m22725%2C22759'}];
 m.state.catalog.checks=[{id:'bytes-hash',url:'https://www.carm.es/web/descarga?RASTRO=c77$m22725,22759&IDCONTENIDO=209318&ALIAS=ARCH',checked_at:'2026-10-01T09:03:17Z',status:'read',success:true}];
 assert.doesNotMatch(context.window.BAV.shell(m),/Sin comprobación reciente registrada para esta referencia/);
 m.state.catalog.checks[0].url=m.state.catalog.checks[0].url.replace('209318','209319');
 assert.match(context.window.BAV.shell(m),/Sin comprobación reciente registrada para esta referencia/);
});
