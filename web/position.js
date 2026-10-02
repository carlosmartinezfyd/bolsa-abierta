(function(root,factory){if(typeof module==='object'&&module.exports)module.exports=factory();else root.BAPosition=factory();})(typeof window==='object'?window:globalThis,function(){
  'use strict';
  const KEY='bolsa-abierta:position:v1';
  const E=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const date=value=>new Intl.DateTimeFormat('es',{day:'numeric',month:'short',year:'numeric',timeZone:'Europe/Madrid'}).format(new Date(value));
  const name=value=>String(value).toLocaleLowerCase('es').replace(/(^|[\s,/-])\p{L}/gu,c=>c.toLocaleUpperCase('es'));
  function officialURL(value){try{const u=new URL(value);return u.protocol==='https:'&&u.hostname==='www.carm.es'&&!u.username&&!u.password&&!u.port&&u.pathname==='/web/descarga'?u.href:null;}catch{return null;}}
  function validateResponse(data){
    const v=data?.version;
    if(!v || !/^[a-f0-9]{64}$/.test(v.id) || v.scope!=='published_list' || !['baseline_only','reviewed_amendments'].includes(v.coverage) ||
       !/^\d{4}-\d{2}-\d{2}$/.test(v.published_at) || !Number.isFinite(Date.parse(v.checked_at)) || !officialURL(v.source_url))throw Error('Respuesta no válida.');
    if(v.coverage==='reviewed_amendments'&&(!Array.isArray(v.amendments)||!v.amendments.length||v.amendments.length>10||v.amendments.some(a=>
      !/^\d{1,10}$/.test(a.content_id)||!officialURL(a.source_url)||new URL(a.source_url).searchParams.get('IDCONTENIDO')!==a.content_id||
      !/^[a-f0-9]{64}$/.test(a.sha256)||!Number.isFinite(Date.parse(a.signed_at))||!Number.isInteger(a.pages)||a.pages<1||a.pages>1200)))throw Error('Correcciones no válidas.');
    for(const p of data.person?[data.person]:data.results||[]){
      const amendment=v.amendments?.find(a=>a.content_id===p?.source_id);
      if(p?.source_id&&p.source_id!=='208095'&&!amendment)throw Error('Origen no válido.');
      if(!p || !/^[a-f0-9]{32}$/.test(p.id) || !/^\d{7}$/.test(p.specialty) || typeof p.name!=='string' || !p.name || p.name.length>180 ||
         !Number.isInteger(p.rank) || p.rank<1 || !Number.isInteger(p.page) || p.page<(amendment?1:2) || p.page>(amendment?amendment.pages:1200))throw Error('Posición no válida.');
    }return data;
  }
  function createModel({request,storage,requestRefresh}={}){
    const state={catalog:null,version:null,person:null,draft:null,results:[],searched:false,busy:false,error:'',message:'',specialty:'',query:'',more:false};
    let notify=()=>{},sequence=0;const emit=()=>notify(state);
    async function catalog(){
      const data=validateResponse(await request('/api/positions'));
      if(!Array.isArray(data.specialties)||!data.specialties.length||data.specialties.some(s=>!/^\d{7}$/.test(s.code)||typeof s.name!=='string'||typeof s.body!=='string'))throw Error('Catálogo no válido.');
      state.catalog=data;return data;
    }
    async function loadPerson(id){const data=validateResponse(await request('/api/positions/'+id));if(!data.person||data.person.id!==id)throw Error('Persona no válida.');state.person=data.person;state.version=data.version;}
    async function init(){
      state.busy=true;state.error='';emit();
      try{await catalog();let id;try{id=storage?.getItem(KEY);}catch{}if(/^[a-f0-9]{32}$/.test(id||''))await loadPerson(id);}
      catch(e){state.error=e.status===404?'Tu selección ya no aparece en esta publicación. Vuelve a buscarla.':'No se ha podido cargar la lista. Inténtalo de nuevo.';}
      finally{state.busy=false;emit();}
    }
    async function search(specialty,query){
      const ticket=++sequence;Object.assign(state,{specialty,query,results:[],draft:null,error:'',message:'',searched:false,busy:true});emit();
      try{const data=validateResponse(await request('/api/positions/search',{specialty,query}));if(ticket!==sequence)return;
        if(!Array.isArray(data.results)||data.results.some(p=>p.specialty!==specialty))throw Error('Coincidencias no válidas.');
        state.results=data.results;state.more=!!data.more;state.searched=true;state.searchVersion=data.version;
      }catch{if(ticket===sequence)state.error='No se ha podido buscar. Escribe al menos tres letras o tu número de lista.';}
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
        state.error=e.status===404?'Tu selección ya no aparece en esta publicación. Vuelve a buscarla.':e.message==='No se ha confirmado una nueva comprobación de esta lista.'?e.message:'No se ha podido completar la consulta. Se conserva el resultado anterior.';
      }finally{state.busy=false;emit();}
    }
    return {state,init,search,choose,confirm,clear,refresh,subscribe(fn){notify=fn;}};
  }
  function render(s){
    const disabled=s.busy?'disabled':'';
    const status=`<div class="position-status" role="status" aria-live="polite">${E(s.error||s.message||(s.busy?'Consultando…':''))}</div>`;
    if(!s.catalog)return `<div class="position-loading"><p>${s.error?E(s.error):'Cargando lista…'}</p>${s.error?'<button class="button" data-position="retry">Reintentar</button>':''}</div>`;
    if(s.person){const p=s.person,v=s.version,amendment=v.amendments?.find(a=>a.content_id===p.source_id);return `<section class="position-card" aria-labelledby="position-person"><div class="position-person"><div><p class="position-eyebrow">${E(name(p.specialty_name))}</p><h2 id="position-person" tabindex="-1">${E(name(p.name))}</h2></div><button class="position-text-button" data-position="change" ${disabled}>Cambiar</button></div>
      <div class="position-rank"><span>Puesto en la lista publicada</span><strong>${p.rank.toLocaleString('es')}<small>º</small></strong><time datetime="${E(v.published_at)}">${E(date(v.published_at))}${v.coverage==='reviewed_amendments'?' · con correcciones':''}</time></div>
      <div class="position-card-footer"><span>N.º de lista ${E(p.list_number)}</span><button class="button primary" data-position="refresh" ${disabled}>${s.busy?'Consultando…':s.catalog.refresh_available?'Actualizar':'Volver a consultar'}</button></div></section>${status}
      <details class="position-details"><summary>Ver detalle</summary><div><p>El puesto cuenta las personas que aparecen antes en esta especialidad, siguiendo el orden y los bloques del documento. No es la posición actual entre disponibles.</p><dl><dt>Publicación</dt><dd>Lista definitiva · curso 2026/2027</dd><dt>Bloque</dt><dd>${E(p.block_name)}</dd><dt>Página del PDF</dt><dd>${p.page}</dd><dt>Documentos comprobados</dt><dd>${E(date(v.checked_at))}</dd></dl>${v.coverage==='reviewed_amendments'?`<p>Correcciones incorporadas:</p><ul>${v.amendments.map(a=>`<li><a href="${E(officialURL(a.source_url))}" target="_blank" rel="noopener noreferrer">Orden firmada el ${E(date(a.signed_at))} ↗</a></li>`).join('')}</ul>`:`<p>Referencia del ${E(date(v.published_at))}. Las correcciones posteriores y los cambios de disponibilidad aún no están incorporados.</p>`}<a href="${E(officialURL(amendment?.source_url||v.source_url))}#page=${p.page}" target="_blank" rel="noopener noreferrer">Abrir documento oficial ↗</a></div></details>`;}
    if(s.draft){const p=s.draft;return `<section class="position-card position-confirm"><p class="position-eyebrow">Confirma tu selección</p><h2 tabindex="-1" id="position-person">${E(name(p.name))}</h2><p>${E(name(p.specialty_name))}</p><p class="muted">N.º ${E(p.list_number)} · ${E(p.block_name)}</p><div class="buttons"><button class="button primary" data-position="confirm" ${disabled}>Esta es mi ficha</button><button class="button" data-position="back" ${disabled}>Volver</button></div></section>${status}`;}
    const groups=new Map();for(const x of s.catalog.specialties){if(!groups.has(x.body))groups.set(x.body,[]);groups.get(x.body).push(x);}
    return `<section class="position-search"><h2>Encuentra tu ficha</h2><form id="position-form"><label class="field" for="position-specialty">Especialidad<select id="position-specialty" name="specialty" required><option value="">Selecciona tu especialidad</option>${[...groups].map(([body,items])=>`<optgroup label="${E(name(body))}">${items.map(x=>`<option value="${x.code}" ${s.specialty===x.code?'selected':''}>${E(name(x.name))} · ${x.code}</option>`).join('')}</optgroup>`).join('')}</select></label><label class="field" for="position-query">Nombre y apellidos o número de lista<input id="position-query" name="query" required minlength="3" maxlength="100" autocomplete="off" value="${E(s.query)}" placeholder="Escribe tus apellidos" /></label><button class="button primary" type="submit" ${disabled}>${s.busy?'Buscando…':'Buscar mi ficha'}</button></form><p class="position-search-date">Lista publicada el ${E(date((s.searched?s.searchVersion:s.catalog.version).published_at))}</p></section>${status}
      ${s.searched?`<section class="position-matches" aria-labelledby="position-matches-title"><h2 id="position-matches-title" tabindex="-1">${s.results.length?'Selecciona tu nombre':'Sin coincidencias'}</h2>${!s.results.length?'<p>Prueba con ambos apellidos o comprueba la especialidad.</p>':`<ul>${s.results.map(p=>`<li><button data-position="choose" data-person="${p.id}"><strong>${E(name(p.name))}</strong><span>N.º ${E(p.list_number)} · ${E(p.block_name)}</span><span class="position-select-label">Seleccionar →</span></button></li>`).join('')}</ul>`}${s.more?'<p>Hay más coincidencias. Añade tu nombre o el segundo apellido.</p>':''}</section>`:''}`;
  }
  let browserModel,started=false;
  function mount(){
    const target=document.getElementById('position-root');if(!target)return;
    function paint(){const root=document.getElementById('position-root');if(root)root.innerHTML=render(browserModel.state);}
    if(!browserModel){let storage;try{storage=window.localStorage;}catch{}
      browserModel=createModel({storage,request:async(path,body)=>{
        const base=window.BA_CONFIG?.apiBase||'';
        if(base){const u=new URL(base);if(u.protocol!=='https:'||u.username||u.password||u.search||u.hash)throw Error('Servicio no configurado.');}
        const response=await fetch(base.replace(/\/+$/,'')+(base?path:'.'+path),{method:body?'POST':'GET',cache:'no-store',credentials:'omit',headers:{'Accept':'application/json',...(body?{'Content-Type':'application/json'}:{})},...(body?{body:JSON.stringify(body)}:{}),signal:AbortSignal.timeout(20000)});
        if(!response.ok)throw Object.assign(Error('Consulta fallida.'),{status:response.status});return response.json();
      },requestRefresh:()=>BA.refreshSource(fetch,window.BA_CONFIG||{},()=>{})});browserModel.subscribe(paint);
    }
    paint();target.oninput=event=>{if(event.target.id==='position-query')browserModel.state.query=event.target.value;};
    target.onchange=event=>{if(event.target.id==='position-specialty')browserModel.state.specialty=event.target.value;};
    target.onclick=async event=>{
      const button=event.target.closest('[data-position]');if(!button||button.disabled)return;const action=button.dataset.position;
      if(action==='choose'){browserModel.choose(button.dataset.person);document.getElementById('position-person')?.focus();}
      if(action==='confirm'){await browserModel.confirm();document.getElementById('position-person')?.focus();}
      if(action==='change'){browserModel.clear();document.getElementById('position-specialty')?.focus();}
      if(action==='back'){browserModel.choose(null);document.getElementById('position-query')?.focus();}
      if(action==='retry')await browserModel.init();if(action==='refresh'){await browserModel.refresh();document.querySelector('[data-position="refresh"]')?.focus();}
    };
    target.onsubmit=async event=>{if(event.target.id!=='position-form')return;event.preventDefault();const form=new FormData(event.target);await browserModel.search(form.get('specialty'),form.get('query'));document.getElementById('position-matches-title')?.focus();};
    if(!started){started=true;void browserModel.init();}
  }
  return {createModel,validateResponse,render,mount};
});
