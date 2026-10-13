const test=require('node:test'),assert=require('node:assert/strict');
const BA=require('../web/core.js');
test('a historical document without retained evidence never becomes a current verified vacancy',()=>{
 const c=BA.publicationContext({id:'old',published_at:'2026-09-18',evidence_status:'original_unavailable'},'new');
 assert.equal(c.historical,true);assert.equal(c.pdfAvailable,false);assert.equal(c.checkedAt,null);
 assert.match(c.limit,/Disponibilidad actual sin confirmar/);
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
