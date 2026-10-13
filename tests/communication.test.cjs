const test=require('node:test'),assert=require('node:assert/strict');
const BA=require('../web/core.js');
const fs=require('node:fs'),vm=require('node:vm');
const context={BA,URL,window:{}};vm.createContext(context);
vm.runInContext(fs.readFileSync(require.resolve('../web/ui.js'),'utf8'),context);
context.BAUI=context.window.BAUI;
vm.runInContext(fs.readFileSync(require.resolve('../web/views.js'),'utf8'),context);
const U=context.window.BAUI,V=context.window.BAV;
function model(){const state=JSON.parse(fs.readFileSync(require.resolve('../data/state.json'),'utf8'));return {state,prefs:{favorites:[],functions:[]},filters:{},page:1,changePage:1,view:'vacancies'};}
const row=(id,quantity=1)=>({id,center_code:'30000001',function_code:'0590001',cupo:'VP',itinerant:'N',jornada:'Completa',quantity});
const doc=(id,date,rows)=>({id,status:'approved',title:'Vacantes sin cubrir de Secundaria',published_at:date,act_date:date,rows});
test('a historical document without retained evidence never becomes a current verified vacancy',()=>{
 const c=BA.publicationContext({id:'old',published_at:'2026-09-18',evidence_status:'original_unavailable'},'new');
 assert.equal(c.historical,true);assert.equal(c.pdfAvailable,false);assert.equal(c.checkedAt,null);
 assert.match(c.limit,/Disponibilidad actual sin confirmar/);
});
test('comparison preserves duplicate quantities and evidence from both publications',()=>{
 const before=doc('a','2026-09-01',[row('a1'),row('a2')]),after=doc('b','2026-09-08',[row('b1',3)]);
 const changes=BA.comparison(before,after);assert.equal(changes.length,1);assert.equal(changes[0].before,2);assert.equal(changes[0].after,3);
 assert.deepEqual(changes[0].beforeRows.map(x=>x.id),['a1','a2']);assert.deepEqual(changes[0].afterRows.map(x=>x.id),['b1']);
 assert.deepEqual(BA.comparison(before,doc('c','2026-09-09',[row('c1',2)])),[]);
 assert.throws(()=>BA.comparison(after,before));assert.throws(()=>BA.comparison(before,{...after,title:'Lista de Maestros'}));
});
test('empty vacancy results do not expose export, ordering or empty pagination',()=>{
 const m=model();m.filters.q='no-existe-xyz';const html=V.shell(m);
 assert.doesNotMatch(html,/data-action="export-csv"|id="sort-by"|Página 1 de 1/);
});
test('selected legacy document warns beside results and inside detail',()=>{
 const m=model(),d=m.state.documents.find(x=>x.evidence_status==='original_unavailable');m.selectedDoc=d.id;
 assert.match(V.shell(m),/Publicación histórica/);assert.match(V.shell(m),/PDF no conservado/);
 assert.match(U.detail(d.rows[0],d,m.prefs),/PDF no conservado/);
});
test('loading home does not claim that no valid publication exists',()=>{
 const html=V.shell({...model(),view:'home',state:null});assert.match(html,/Cargando publicaciones/);assert.doesNotMatch(html,/no hay un listado validado/);
});
test('duration distinguishes unextracted, absent and explicit source values',()=>{
 assert.equal(BA.durationLabel({}),'No extraída; consulta el documento');
 assert.equal(BA.durationLabel({duration_status:'absent'}),'No indicada en el documento');
 assert.equal(BA.durationLabel({duration:'Hasta el 30 de junio'}),'Hasta el 30 de junio');
});
test('display casing preserves published roman numerals and acronyms without completing truncated names',()=>{
 assert.equal(BA.title('IES CARLOS III'),'IES Carlos III');
 assert.equal(BA.title('CEIP PRUEBA'),'CEIP Prueba');
 assert.equal(BA.title('POLITÉCN'),'Politécn');
});

