/* Bolsa Abierta Pages loader · AGPL-3.0-only */
(async()=>{
  const app=document.getElementById('app');
  try{
    if(!('DecompressionStream' in window)) throw new Error('Este navegador no admite la descompresión necesaria para esta demo.');
    const names=["payload-00.bin","payload-01.bin","payload-02.bin","payload-03.bin","payload-04.bin","payload-05.bin","payload-06.bin"];
    const parts=await Promise.all(names.map(async n=>{
      const r=await fetch('./'+n,{cache:'no-store'});
      if(!r.ok) throw new Error('No se pudo cargar '+n+' ('+r.status+')');
      return new Uint8Array(await r.arrayBuffer());
    }));
    const total=parts.reduce((n,p)=>n+p.length,0), all=new Uint8Array(total);
    let off=0; for(const p of parts){all.set(p,off);off+=p.length;}
    const stream=new Blob([all]).stream().pipeThrough(new DecompressionStream('gzip'));
    const payload=JSON.parse(await new Response(stream).text());
    const files=payload.files||{};
    const style=document.createElement('style'); style.textContent=files['styles.css']||''; document.head.appendChild(style);
    for(const name of payload.order||[]){
      if(name==='styles.css') continue;
      if(!files[name]) throw new Error('Falta '+name+' en el paquete.');
      const s=document.createElement('script');
      s.textContent=files[name]+'\n//# sourceURL='+name;
      document.body.appendChild(s);
    }
  }catch(err){
    console.error(err);
    app.innerHTML='<main style="max-width:760px;margin:64px auto;padding:24px;font:16px/1.5 system-ui"><h1>Bolsa Abierta</h1><p>No se ha podido cargar el prototipo.</p><pre style="white-space:pre-wrap">'+String(err.message||err).replace(/[&<>]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]))+'</pre><p><a href="https://github.com/carlosmartinezfyd/bolsa-abierta">Abrir el código en GitHub</a></p></main>';
  }
})();
