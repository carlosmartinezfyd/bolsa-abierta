(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.BAPosition=factory();})(typeof window==='object'?window:globalThis,function(){
  'use strict';
  const KEY='bolsa-abierta:position:v1';
  const E=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date=value=>value&&Number.isFinite(Date.parse(value))?new Intl.DateTimeFormat('es',{day:'numeric',month:'short',year:'numeric',timeZone:'Europe/Madrid'}).format(new Date(value)):'Sin fecha acreditada';
  const name=value=>String(value).toLocaleLowerCase('es').replace(/(^|[\s,(/-])\p{L}/gu,c=>c.toLocaleUpperCase('es'));
  const fold=value=>String(value).normalize('NFKD').replace(/\p{M}/gu,'').toLocaleLowerCase('es');
  const canSearch=query=>String(query).replace(/[^\p{L}\p{N}]/gu,'').length>=3;
  const habilitationCode=value=>/^(?:\d{3}|597\d{3}|0597\d{3})$/.test(value);
  const functionCode=value=>/^\d{4}[\dA-Z]\d{2}$/.test(value);
  function filterSpecialties(items,query){const tokens=fold(query).split(/\s+/).filter(Boolean);return items.filter(s=>tokens.every(t=>fold(`${s.name} ${s.body} ${s.code}`).includes(t)));}
  function officialURL(value){try{const u=new URL(value);return u.protocol==='https:'&&u.hostname==='www.carm.es'&&!u.username&&!u.password&&!u.port&&u.pathname==='/web/descarga'?u.href:null;}catch{return null;}}
  const isoDate=value=>typeof value==='string'&&/^\d{4}-\d{2}-\d{2}$/.test(value)&&Number.isFinite(Date.parse(value))&&new Date(value).toISOString().slice(0,10)===value;
  function validEvidence(d,amendment=false){return d&&/^\d{1,10}$/.test(d.content_id)&&officialURL(d.source_url)&&new URL(d.source_url).searchParams.get('IDCONTENIDO')===d.content_id&&/^[a-f0-9]{64}$/.test(d.sha256)&&(amendment?Number.isFinite(Date.parse(d.signed_at)):isoDate(d.published_at))&&Number.isInteger(d.pages)&&d.pages>=1&&d.pages<=1200;}
  function rowEvidence(p,v){
    const document=v.documents?.find(d=>d.content_id===(p.roster_id||p.source_id));
    const amendment=(document?.amendments||v.amendments)?.find(a=>a.content_id===p.source_id);
    return {document,amendment,source:amendment||document||v,published_at:document?.published_at||v.published_at};
  }
  function validateResponse(data){
    const v=data?.version;
    if(!v||!/^[a-f0-9]{64}$/.test(v.id)||v.scope!=='published_list'||!['baseline_only','reviewed_amendments','multi_source'].includes(v.coverage)||!isoDate(v.published_at)||(v.checked_at!==null&&!Number.isFinite(Date.parse(v.checked_at)))||!officialURL(v.source_url))throw Error('Respuesta no válida.');
    if((v.coverage==='reviewed_amendments'||v.amendments?.length)&&(!Array.isArray(v.amendments)||!v.amendments.length||v.amendments.length>10||v.amendments.some(a=>!validEvidence(a,true))))throw Error('Correcciones no válidas.');
    if(v.coverage==='multi_source'&&(!Array.isArray(v.documents)||!v.documents.length||v.documents.length>100||v.documents.some(d=>!['award','maestros_roster'].includes(d.kind)||!validEvidence(d)||(d.kind==='maestros_roster'&&d.rank_scope!=='maestros_unique_list')||(d.amendments!==undefined&&(!Array.isArray(d.amendments)||d.amendments.length>10||d.amendments.some(a=>!validEvidence(a,true)))))))throw Error('Documentos no válidos.');
    for(const p of data.person?[data.person]:data.results||[]){
      if(!p||!/^[a-f0-9]{32}$/.test(p.id)||typeof p.name!=='string'||!p.name||p.name.length>180||!Number.isInteger(p.page)||p.page<1)throw Error('Ficha no válida.');
      const {document,amendment,source}=rowEvidence(p,v);
      if(p.source_id&&p.source_id!=='208095'&&!amendment&&(!document||document.content_id!==p.source_id))throw Error('Origen no válido.');
      if(p.roster_id&&(!document||document.kind!=='maestros_roster'))throw Error('Lista de origen no válida.');
      if(document?.kind==='award'){
        if(p.record_type!=='award'||p.rank!==null||!functionCode(p.specialty)||typeof p.destination!=='string'||!p.destination||typeof p.workload!=='string'||!p.workload||p.page>document.pages||(p.incorporation_at!=null&&!isoDate(p.incorporation_at))||(p.appointment_status!=null&&!['definitive','provisional'].includes(p.appointment_status)))throw Error('Adjudicación no válida.');
        continue;
      }
      const maestros=document?.kind==='maestros_roster';
      if((p.record_type&&p.record_type!=='list')||!Number.isInteger(p.rank)||p.rank<1||p.page>(source.pages||1200)||(!document&&!amendment&&p.page<2)||(maestros?(p.specialty!=='0597'||p.record_type!=='list'||!p.source_id||p.rank_scope!=='maestros_unique_list'||!Array.isArray(p.habilitations)||p.habilitations.length>100||p.habilitations.some(h=>!habilitationCode(h.code)||typeof h.name!=='string'||!h.name||h.name.length>180)):!functionCode(p.specialty)))throw Error('Posición no válida.');
    }return data;
  }
  async function readResponse(response){
    if(response.ok)return response.json();
    let data;try{data=await response.json();}catch{}
    throw Object.assign(Error('Consulta fallida.'),{status:response.status,...(response.status===503&&(data?.index_pending===true||data?.code==='index_pending')?{code:'index_pending'}:{})});
  }
  const searchFailure=error=>error.status===503&&error.code==='index_pending'?'El índice de búsqueda se está preparando. Puedes consultar por número completo de lista.':null;
  function createModel({request,storage,requestRefresh}={}){
    const state={catalog:null,version:null,person:null,draft:null,results:[],searched:false,busy:false,error:'',message:'',specialty:'',query:'',more:false};
    let notify=()=>{},sequence=0;const emit=()=>notify(state);
    async function readCatalog(){
      const data=validateResponse(await request('/api/positions'));
      if(!Array.isArray(data.specialties)||!data.specialties.length||data.specialties.some(s=>!(functionCode(s.code)||s.code==='0597')||typeof s.name!=='string'||typeof s.body!=='string'))throw Error('Catálogo no válido.');
      return data;
    }
    async function catalog(){const data=await readCatalog();state.catalog=data;return data;}
    async function loadPerson(id){const data=validateResponse(await request('/api/positions/'+id));if(!data.person||data.person.id!==id)throw Error('Persona no válida.');state.person=data.person;state.version=data.version;}
    async function init(){
      state.busy=true;state.error='';emit();
      try{await catalog();let id;try{id=storage?.getItem(KEY);}catch{}if(/^[a-f0-9]{32}$/.test(id||''))await loadPerson(id);}
      catch(e){state.error=e.status===404?'Esta ficha no se ha encontrado en la generación consultada. Vuelve a buscarla; esto no acredita una exclusión.':'No se ha podido cargar la lista. Inténtalo de nuevo.';}
      finally{state.busy=false;emit();}
    }
    async function search(specialty,query){
      query=query.trim();specialty=specialty||'';
      const ticket=++sequence;Object.assign(state,{specialty,query,results:[],draft:null,error:'',message:'',searched:false,busy:true});emit();
      if(!canSearch(query)){state.busy=false;state.error='Escribe al menos tres letras o tu número de lista.';emit();return;}
      try{const data=validateResponse(await request('/api/positions/search',{specialty,query}));if(ticket!==sequence)return;
        let currentCatalog=state.catalog;
        if(data.version.id!==currentCatalog.version.id){
          currentCatalog=await readCatalog();if(ticket!==sequence)return;
          if(currentCatalog.version.id!==data.version.id)throw Object.assign(Error('generation'),{status:409});
        }
        if(!Array.isArray(data.results)||data.results.some(p=>(specialty&&p.specialty!==specialty)||!currentCatalog.specialties.some(s=>s.code===p.specialty)))throw Error('Coincidencias no válidas.');
        state.catalog=currentCatalog;state.results=data.results;state.more=!!data.more;state.nextOffset=data.next_offset;state.searched=true;state.searchVersion=data.version;
      }catch(e){if(ticket===sequence)state.error=searchFailure(e)||(e.status===409?'Las publicaciones han cambiado. Vuelve a pulsar Buscar.':'No se ha podido consultar la lista. Vuelve a intentarlo.');}
      finally{if(ticket===sequence){state.busy=false;emit();}}
    }
    function editQuery(query){++sequence;Object.assign(state,{query,results:[],draft:null,error:'',message:'',searched:false,busy:false,more:false});emit();}
    async function loadMore(){
      if(state.busy||!state.more||!Number.isInteger(state.nextOffset))return;
      const ticket=++sequence;state.busy=true;state.error='';emit();
      try{
        const data=validateResponse(await request('/api/positions/search',{specialty:state.specialty,query:state.query,offset:state.nextOffset,version_id:state.searchVersion.id}));
        if(ticket!==sequence)return;
        if(data.version.id!==state.searchVersion.id||!Array.isArray(data.results)||data.results.some(p=>state.specialty&&p.specialty!==state.specialty))throw Error('generation');
        const seen=new Set(state.results.map(p=>p.id));
        state.results.push(...data.results.filter(p=>!seen.has(p.id)));state.more=!!data.more;state.nextOffset=data.next_offset;
      }catch(e){if(ticket===sequence)state.error=searchFailure(e)||(e.status===409?'Las publicaciones han cambiado. Vuelve a pulsar Buscar.':'No se han podido cargar más coincidencias. Inténtalo de nuevo.');}
      finally{if(ticket===sequence){state.busy=false;emit();}}
    }
    function choose(id){state.draft=state.results.find(p=>p.id===id)||null;state.error='';emit();}
    async function confirm(){
      if(!state.draft)return;state.busy=true;state.error='';emit();
      try{await loadPerson(state.draft.id);state.draft=null;try{storage?.setItem(KEY,state.person.id);}catch{state.message='La selección no se podrá recordar al cerrar el navegador.';}}
      catch{state.error='No se ha podido confirmar la persona. Vuelve a intentarlo.';}
      finally{state.busy=false;emit();}
    }
    function clear(){++sequence;Object.assign(state,{person:null,version:null,draft:null,results:[],searched:false,error:'',message:''});try{storage?.removeItem(KEY);}catch{}emit();}
    async function refresh(){
      if(state.busy)return;state.busy=true;state.error='';state.message='';emit();const id=state.person?.id,previous=state.version?.checked_at;let jobStarted=NaN;
      try{if(state.catalog?.refresh_available&&requestRefresh){state.message='Consultando las fuentes…';emit();const job=await requestRefresh();jobStarted=Date.parse(job.created_at);if(job.status!=='completed'||!Number.isFinite(jobStarted))throw Error('Comprobación incompleta.');}
        await catalog();if(id)await loadPerson(id);
        const checked=Date.parse(state.version?.checked_at || state.catalog.version.checked_at);
        if(state.catalog.refresh_available && !(checked>=jobStarted && checked>Date.parse(previous || state.catalog.version.checked_at)))throw Error('No se ha confirmado una nueva comprobación de esta lista.');
        state.message=state.catalog.refresh_available&&state.version?.checked_at!==previous?'Comprobación recibida.':'Consulta recargada. La fecha de la publicación no ha cambiado.';
      }catch(e){state.message='';if(e.status===404){state.person=null;state.version=null;try{storage?.removeItem(KEY);}catch{}}
        state.error=e.status===404?'Esta ficha no se ha encontrado en la generación consultada. Vuelve a buscarla; esto no acredita una exclusión.':e.message==='No se ha confirmado una nueva comprobación de esta lista.'?e.message:'No se ha podido completar la consulta. Se conserva el resultado anterior.';
      }finally{state.busy=false;emit();}
    }
    return {state,init,search,loadMore,editQuery,choose,confirm,clear,refresh,subscribe(fn){notify=fn;}};
  }
  function specialtyLabel(s){const selected=s.catalog.specialties.find(x=>x.code===s.specialty);return selected?name(selected.name):'Todas las listas y funciones';}
  function awardDestination(value){
    let [center,municipality='']=String(value).split(' · ');
    const suffix=` (${municipality})`;
    if(municipality&&center.endsWith(suffix))center=center.slice(0,-suffix.length);
    return {center:name(center).replace(/^(Ies|Cifp|Ceip|Cee|Eoi)\b/,s=>s.toUpperCase()),municipality:name(municipality)};
  }
  function searchDate(s){const v=s.searched&&s.searchVersion||s.catalog.version;return v.coverage==='multi_source'?'Listas y adjudicaciones incorporadas · cobertura parcial':`Lista del ${date(v.published_at)}${v.coverage==='reviewed_amendments'?' · con correcciones':''}`;}
  function matchEvidence(p,v){
    const {document,amendment,published_at}=rowEvidence(p,v);
    const label=document?.kind==='award'?`Adjudicación${p.appointment_status==='provisional'?' · reserva provisional':''}`:document?.kind==='maestros_roster'?`Lista única de Maestros · ordinal ${p.rank.toLocaleString('es')}`:`N.º ${p.list_number} · ${p.block_name}`;
    return `${label} · ${date(published_at)}${amendment?` · corrección ${date(amendment.signed_at)}`:''} · pág. ${p.page}`;
  }
  function sourceInformation(s){
    const v=s.searched&&s.searchVersion||s.catalog.version;
    const records=Number.isInteger(v.row_count)?v.row_count:s.catalog.specialties.reduce((n,x)=>n+(Number.isInteger(x.count)?x.count:0),0);
    const docs=v.documents||[],courses=[...new Set([v.course,...docs.map(d=>d.course)].filter(Boolean))];
    return `<details class="position-details position-source-information"><summary>Fuentes y alcance de la consulta</summary><div><p>${records.toLocaleString('es')} registros incorporados; una persona puede tener varios registros. Los códigos del filtro incluyen listas y funciones de adjudicación.</p><p>Cursos: ${E(courses.length?courses.join(' · '):'no consignados en metadatos')}. No se acredita la cobertura completa de listas ordinarias, urgentes, extraordinarias, abiertas, habilitaciones y sus correcciones.</p><dl><dt>Comprobación de la generación</dt><dd>${E(date(v.checked_at))}</dd></dl><ul><li>Lista de referencia · ${E(date(v.published_at))} · <a href="${E(officialURL(v.source_url))}" target="_blank" rel="noopener noreferrer">PDF oficial ↗</a></li>${docs.map(d=>`<li>${d.kind==='maestros_roster'?'Lista única de Maestros':'Adjudicaciones'} · ${E(date(d.published_at))}${Number.isInteger(d.row_count)?` · ${d.row_count.toLocaleString('es')} registros`:''} · <a href="${E(officialURL(d.source_url))}" target="_blank" rel="noopener noreferrer">PDF oficial ↗</a></li>`).join('')}</ul><p>Los documentos incorporados son una parte del corpus. Consulta <a href="#sources" data-view="sources">Fuentes</a> para el recorrido por fuente, familia y curso y el trabajo pendiente.</p></div></details>`;
  }
  function specialtyOptions(s,query=''){
    const items=filterSpecialties(s.catalog.specialties,query);
    return `<button type="button" data-position="select-specialty" data-specialty="" aria-pressed="${!s.specialty}">Todas las listas y funciones</button>${items.map(x=>`<button type="button" data-position="select-specialty" data-specialty="${x.code}" aria-pressed="${s.specialty===x.code}"><strong>${E(name(x.name))}</strong><span>${E(name(x.body))} · ${x.code}</span></button>`).join('')}${items.length?'':'<p>No hay listas o funciones con ese nombre.</p>'}`;
  }
  function searchFeedback(s){
    const message=s.error||(s.busy?'Buscando…':s.searched?(s.results.length?`${s.more?`${s.results.length}+`:s.results.length} ${s.results.length===1?'coincidencia':'coincidencias'}`:(s.specialty?`No hay coincidencias en ${specialtyLabel(s)}`:(s.catalog.version.coverage==='multi_source'?'No hay coincidencias en las publicaciones incorporadas':'No hay coincidencias en esta publicación'))):'');
    const status=`<p class="position-status" role="status" aria-live="polite">${E(message)}</p>`;
    if(!s.searched)return status;
    if(!s.results.length)return `${status}<div class="position-empty"><p>La búsqueda solo cubre las publicaciones incorporadas. No encontrar una ficha no acredita ausencia ni exclusión de una lista.</p>${s.specialty?'':'<p>Prueba con un apellido o con tu número de lista.</p>'}<div class="buttons">${s.specialty?'<button class="button" data-position="all-specialties">Buscar en todas las listas y funciones</button>':'<button class="button" data-position="edit">Editar búsqueda</button>'}<a href="https://www.educarm.es/consultalistainterinos" target="_blank" rel="noopener noreferrer">Consultar en Educarm ↗</a></div></div>`;
    return `${status}<section class="position-matches" aria-label="Coincidencias"><ul>${s.results.map(p=>`<li><button data-position="choose" data-person="${p.id}"><span class="position-match-main"><strong>${E(name(p.name))}</strong><span>${E(name(p.specialty_name))} · ${E(name(p.body_name))}</span><small>${E(matchEvidence(p,s.searchVersion||s.catalog.version))}</small></span><span class="position-select-label" aria-hidden="true">→</span></button></li>`).join('')}</ul>${s.more?`<button class="button position-refine" data-position="more" ${s.busy?'disabled':''}>Ver más coincidencias</button>`:''}</section>`;
  }
  function render(s){
    const disabled=s.busy?'disabled':'';
    const status=`<div class="position-status" role="status" aria-live="polite">${E(s.error||s.message||(s.busy?'Consultando…':''))}</div>`;
    if(!s.catalog)return `<div class="position-loading"><p>${s.error?E(s.error):'Cargando lista…'}</p>${s.error?'<button class="button" data-position="retry">Reintentar</button>':''}</div>`;
    if(s.person){
      const p=s.person,v=s.version,{document:d,amendment,source,published_at}=rowEvidence(p,v),maestros=d?.kind==='maestros_roster';
      const heading=`<div class="position-person"><div><p class="position-eyebrow">${E(name(p.specialty_name))}</p><h2 id="position-person" tabindex="-1">${E(name(p.name))}</h2></div><button class="position-text-button" data-position="change" ${disabled}>Borrar ficha guardada</button></div>`;
      const footer=`<div class="position-card-footer"><span>N.º de lista ${E(p.list_number)}</span><button class="button primary" data-position="refresh" ${disabled}>${s.busy?'Consultando…':s.catalog.refresh_available?'Actualizar':'Volver a consultar'}</button></div>`;
      const evidence=`<dl><dt>Fecha de publicación</dt><dd>${E(date(published_at))}</dd>${amendment?`<dt>Corrección firmada</dt><dd>${E(date(amendment.signed_at))}</dd>`:''}<dt>Página del PDF de evidencia</dt><dd>${p.page}</dd><dt>Última comprobación de la generación</dt><dd>${E(date(v.checked_at))}</dd></dl><a href="${E(officialURL(source.source_url))}#page=${p.page}" target="_blank" rel="noopener noreferrer">Abrir documento oficial ↗</a>`;
      if(p.record_type==='award'){
        const destination=awardDestination(p.destination);
        return `<section class="position-card" aria-labelledby="position-person">${heading}<div class="position-award"><p>Adjudicación publicada · <time datetime="${E(published_at)}">${E(date(published_at))}</time></p>${p.appointment_status==='provisional'?'<p><strong>Reserva provisional</strong></p>':p.appointment_status==='definitive'?'<p>Nombramiento definitivo acreditado</p>':''}<h3>${E(destination.center)}</h3><p>${E(destination.municipality)}</p><p>${E(p.workload)}</p>${p.incorporation_at?`<p>Incorporación: <time datetime="${E(p.incorporation_at)}">${E(date(p.incorporation_at))}</time></p>`:''}</div>${footer}</section>${status}<details class="position-details"><summary>Ver detalle</summary><div><p>El destino corresponde a esta publicación. La adjudicación no se resta del ordinal de una lista ni confirma la disponibilidad de hoy.</p>${p.appointment_status?'':'<p>El documento no acredita aquí el carácter definitivo o provisional del nombramiento. El título de una publicación definitiva no resuelve por sí solo ese estado.</p>'}${evidence}</div></details>`;
      }
      const amendments=d?.amendments||v.amendments||[];
      return `<section class="position-card" aria-labelledby="position-person">${heading}<div class="position-rank"><span>${maestros?'Ordinal en la lista única de Maestros':'Puesto en la lista publicada'}</span><strong>${p.rank.toLocaleString('es')}<small>º</small></strong><time datetime="${E(published_at)}">${E(date(published_at))}${amendments.length?' · con correcciones':''}</time></div>${maestros?`<div class="position-qualifiers"><h3>Habilitaciones acreditadas</h3>${p.habilitations.length?`<ul>${p.habilitations.map(h=>`<li>${E(name(h.name))} · ${E(h.code)}</li>`).join('')}</ul>`:'<p>Sin habilitaciones consignadas en esta ficha.</p>'}</div>`:''}${footer}</section>${status}<details class="position-details"><summary>Ver detalle</summary><div><p>${maestros?'El ordinal pertenece a la lista única del cuerpo de Maestros (0597). Las habilitaciones son cualificaciones separadas y no definen listas con un ordinal propio.':'El puesto cuenta los registros que aparecen antes en esta especialidad, siguiendo el orden y los bloques del documento.'} No es la posición actual entre disponibles.</p><dl><dt>Curso de la lista</dt><dd>${E(d?.course||v.course||'No consignado en metadatos')}</dd><dt>Bloque</dt><dd>${E(p.block_name)}</dd></dl>${evidence}${amendments.length?`<p>Correcciones incorporadas:</p><ul>${amendments.map(a=>`<li><a href="${E(officialURL(a.source_url))}" target="_blank" rel="noopener noreferrer">Orden firmada el ${E(date(a.signed_at))} ↗</a></li>`).join('')}</ul>`:'<p>Esta ficha solo refleja la publicación incorporada. No se acredita la cobertura de todas las correcciones ni de los cambios de disponibilidad.</p>'}</div></details>`;
    }
    if(s.draft){const p=s.draft;return `<section class="position-card position-confirm"><p class="position-eyebrow">Confirma tu selección</p><h2 tabindex="-1" id="position-person">${E(name(p.name))}</h2><p>${E(name(p.specialty_name))}</p><p class="muted">${E(matchEvidence(p,s.searchVersion||s.catalog.version))}</p><p class="muted">Al confirmar, recuerdas el identificador de esta ficha en este navegador. Puedes borrarlo con «Borrar ficha guardada».</p><div class="buttons"><button class="button primary" data-position="confirm" ${disabled}>Confirmar y recordar</button><button class="button" data-position="back" ${disabled}>Volver</button></div></section>${status}`;}
    return `<section class="position-search" aria-label="Buscar mi ficha"><form id="position-form" role="search"><label for="position-query">Tu nombre o número de lista</label><div class="position-query-row"><div class="position-query-wrap"><input id="position-query" name="query" type="search" required minlength="3" maxlength="100" autocomplete="off" spellcheck="false" enterkeyhint="search" value="${E(s.query)}" placeholder="Nombre y apellidos"/><button type="button" class="position-clear" data-position="clear-query" aria-label="Borrar búsqueda" ${s.query?'':'hidden'}>×</button></div><button class="button primary" type="submit">Buscar</button></div><div class="position-filter-row"><button type="button" class="position-specialty-button" data-position="specialties" aria-haspopup="dialog"><span>Lista o función</span><strong id="position-specialty-label">${E(specialtyLabel(s))}</strong><span aria-hidden="true">⌄</span></button></div></form><p class="position-search-date">${E(searchDate(s))}</p><div id="position-feedback">${searchFeedback(s)}</div><div id="position-source-information">${sourceInformation(s)}</div></section><dialog id="position-specialty-dialog" class="position-picker" aria-labelledby="position-picker-title"><div class="position-picker-head"><h2 id="position-picker-title">Lista o función</h2><button type="button" data-position="close-specialties" aria-label="Cerrar listas y funciones">×</button></div><label for="position-specialty-query" class="sr-only">Buscar lista o función</label><input id="position-specialty-query" type="search" placeholder="Buscar lista o función…" autocomplete="off"/><div id="position-specialty-options" class="position-specialty-options">${specialtyOptions(s)}</div></dialog>`;
  }
  let browserModel,searchTimer,started=false;
  function mount(){
    const target=document.getElementById('position-root');if(!target)return;
    function paint(){
      const root=document.getElementById('position-root');if(!root)return;const s=browserModel.state;
      // Preserve the live input node, caret and mobile keyboard while suggestions arrive.
      if(root.querySelector('#position-form')&&s.catalog&&!s.person&&!s.draft){
        root.querySelector('#position-feedback').innerHTML=searchFeedback(s);
        root.querySelector('#position-specialty-label').textContent=specialtyLabel(s);
        root.querySelector('.position-search-date').textContent=searchDate(s);
        root.querySelector('#position-source-information').innerHTML=sourceInformation(s);
        root.querySelector('[data-position="clear-query"]').hidden=!s.query;
      }else root.innerHTML=render(s);
    }
    if(!browserModel){let storage;try{storage=window.localStorage;}catch{}
      browserModel=createModel({storage,request:async(path,body)=>{
        const base=window.BA_CONFIG?.apiBase||'';
        if(base){const u=new URL(base);if(u.protocol!=='https:'||u.username||u.password||u.search||u.hash)throw Error('Servicio no configurado.');}
        const response=await fetch(base.replace(/\/+$/,'')+(base?path:'.'+path),{method:body?'POST':'GET',cache:'no-store',credentials:'omit',headers:{'Accept':'application/json',...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(20000)});
        return readResponse(response);
      },requestRefresh:()=>BA.refreshSource(fetch,window.BA_CONFIG||{},()=>{})});browserModel.subscribe(paint);
    }
    const cancelSearch=()=>{clearTimeout(searchTimer);searchTimer=null;};
    cancelSearch();
    function scheduleSearch(event){
      if(event.target.id==='position-specialty-query'){document.getElementById('position-specialty-options').innerHTML=specialtyOptions(browserModel.state,event.target.value);return;}
      if(event.target.id!=='position-query')return;
      cancelSearch();browserModel.editQuery(event.target.value);
      if(!event.isComposing&&canSearch(event.target.value))searchTimer=setTimeout(()=>{if(document.getElementById('position-form'))void browserModel.search(browserModel.state.specialty,browserModel.state.query);},450);
    }
    function closePicker(){document.getElementById('position-specialty-dialog')?.close();document.querySelector('[data-position="specialties"]')?.focus({preventScroll:true});}
    paint();target.oninput=scheduleSearch;target.oncompositionend=scheduleSearch;
    target.onclick=async event=>{
      const button=event.target.closest('[data-position]');if(!button||button.disabled)return;const action=button.dataset.position;
      cancelSearch();
      if(action==='specialties'){const picker=document.getElementById('position-specialty-dialog');picker.querySelector('#position-specialty-query').value='';picker.querySelector('#position-specialty-options').innerHTML=specialtyOptions(browserModel.state);picker.showModal();document.getElementById('position-specialty-query').focus();}
      if(action==='close-specialties')closePicker();
      if(action==='select-specialty'||action==='all-specialties'){
        closePicker();browserModel.state.specialty=button.dataset.specialty||'';browserModel.editQuery(browserModel.state.query);
        if(canSearch(browserModel.state.query))await browserModel.search(browserModel.state.specialty,browserModel.state.query);
      }
      if(action==='edit'){const input=document.getElementById('position-query');input.focus({preventScroll:true});input.select();}
      if(action==='more'){await browserModel.loadMore();document.querySelector('[data-position="more"]')?.focus({preventScroll:true});}
      if(action==='clear-query'){const input=document.getElementById('position-query');input.value='';browserModel.editQuery('');input.focus({preventScroll:true});}
      if(action==='choose'){browserModel.choose(button.dataset.person);document.getElementById('position-person')?.focus({preventScroll:true});}
      if(action==='confirm'){await browserModel.confirm();document.getElementById('position-person')?.focus();}
      if(action==='change'){browserModel.clear();document.getElementById('position-query')?.focus({preventScroll:true});}
      if(action==='back'){browserModel.choose(null);document.getElementById('position-query')?.focus();}
      if(action==='retry')await browserModel.init();if(action==='refresh'){await browserModel.refresh();document.querySelector('[data-position="refresh"]')?.focus();}
    };
    target.onsubmit=async event=>{if(event.target.id!=='position-form')return;event.preventDefault();cancelSearch();const form=new FormData(event.target);await browserModel.search(browserModel.state.specialty,form.get('query'));};
    if(!started){started=true;void browserModel.init();}
  }
  return {createModel,validateResponse,readResponse,render,filterSpecialties,awardDestination,mount};
});
