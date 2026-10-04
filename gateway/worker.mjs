// Fixed-destination public gateway. Secrets and dispatch decisions stay in Worker/D1.
import {positionRoute} from './positions.mjs';
const COOLDOWN = 5 * 60_000;
const ACTIVE_LEASE = 20 * 60_000;
const POLL_INTERVAL = 10_000;
const MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024;
const TERMINAL = new Set(['completed', 'partial', 'failed']);

export class D1Repository {
  constructor(database) {
    // Reads following a reservation must not come from an eventual read replica.
    this.db = database.withSession ? database.withSession('first-primary') : database;
  }
  async reserve(id, now, day) {
    const reserved = await this.db.prepare(`UPDATE gateway_gate SET
      job_id = ?, created_at = ?, lease_until = ?, cooldown_until = ?,
      dispatches = CASE WHEN day = ? THEN dispatches + 1 ELSE 1 END, day = ?
      WHERE singleton = 1 AND lease_until <= ? AND cooldown_until <= ?
      AND (day <> ? OR dispatches < 96)
      RETURNING job_id, created_at, lease_until, cooldown_until, day, dispatches`)
      .bind(id, now, now + ACTIVE_LEASE, now + COOLDOWN, day, day, now, now, day).first();
    const gate = reserved || await this.db.prepare('SELECT * FROM gateway_gate WHERE singleton = 1').bind().first();
    if (!gate?.job_id || (!reserved && gate.lease_until <= now && gate.cooldown_until <= now)) {
      return {acquired:false, job:null};
    }
    // Recovery also works if the first request stopped between reservation and INSERT.
    // The gate holds all identity/timing fields. Never dispatch from this recovery path.
    await this.db.prepare(`INSERT OR IGNORE INTO gateway_jobs
      (id, created_at, deadline, status, message, poll_until)
      VALUES (?, ?, ?, 'queued', 'Comprobación en cola.', 0)`)
      .bind(gate.job_id, gate.created_at, gate.created_at + ACTIVE_LEASE).run();
    return {acquired:Boolean(reserved), job:await this.read(gate.job_id)};
  }
  async read(id) {
    return this.db.prepare('SELECT * FROM gateway_jobs WHERE id = ?').bind(id).first();
  }
  async pollLease(id, now) {
    const row = await this.db.prepare(`UPDATE gateway_jobs SET poll_until = ?
      WHERE id = ? AND status = 'queued' AND poll_until <= ? RETURNING id`)
      .bind(now + POLL_INTERVAL, id, now).first();
    return Boolean(row);
  }
  async finish(id, status, message, now) {
    await this.db.prepare(`UPDATE gateway_jobs SET status = ?, message = ?, completed_at = ?
      WHERE id = ? AND status = 'queued'`).bind(status, message, now, id).run();
    await this.db.prepare(`UPDATE gateway_gate SET lease_until = 0 WHERE singleton = 1 AND job_id = ?
      AND EXISTS (SELECT 1 FROM gateway_jobs WHERE id = ? AND status <> 'queued')`).bind(id, id).run();
  }
  async message(id, message) {
    await this.db.prepare(`UPDATE gateway_jobs SET message = ? WHERE id = ? AND status = 'queued'`)
      .bind(message, id).run();
  }
}

function configured(env) {
  try {
    const origin = new URL(env.ALLOWED_ORIGIN);
    snapshotURL(env, 0);
    return Boolean(origin.protocol === 'https:' && origin.origin === env.ALLOWED_ORIGIN
      && env.DB && env.GITHUB_TOKEN && /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(env.GITHUB_REPOSITORY || '')
      && /^[A-Za-z0-9_./-]+$/.test(env.GITHUB_REF || '') && !env.GITHUB_REF.includes('..'));
  } catch { return false; }
}

function snapshotURL(env, now) {
  const url = new URL(env.SNAPSHOT_URL);
  if (url.protocol !== 'https:' || url.username || url.password || url.hash || url.search
      || !url.hostname.endsWith('.github.io') || !url.pathname.endsWith('/data/state.json')) {
    throw new Error('Invalid snapshot configuration');
  }
  // This query is generated solely by the Worker; callers cannot change its path.
  url.searchParams.set('ba_check', String(now));
  return url;
}

async function boundedText(response, limit) {
  const declared = response.headers.get('Content-Length');
  if (declared && Number(declared) > limit) throw new Error('Body exceeds limit');
  if (!response.body) return '';
  const reader = response.body.getReader();
  let total = 0;
  const chunks = [];
  try {
    while (true) {
      const {done, value} = await reader.read();
      if (done) break;
      total += value.byteLength;
      if (total > limit) {
        await reader.cancel();
        throw new Error('Body exceeds limit');
      }
      chunks.push(value);
    }
  } finally { reader.releaseLock(); }
  const bytes = new Uint8Array(total);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  return new TextDecoder().decode(bytes);
}

function jobData(job) {
  return { id:job.id, status:job.status, message:job.message,
    created_at:new Date(job.created_at).toISOString(),
    ...(job.completed_at ? {completed_at:new Date(job.completed_at).toISOString()} : {}) };
}

function terminalSnapshot(state, job) {
  const freshness = state.freshness;
  if (!freshness || freshness.request_id !== job.id || !TERMINAL.has(freshness.status)) return null;
  if (freshness.last_attempt_at) {
    const attempt = Date.parse(freshness.last_attempt_at);
    if (!Number.isFinite(attempt) || attempt + 1000 < job.created_at) return null;
  }
  return freshness.status;
}

// Only the finalized all-source workflow artifact can confirm a source check.
// The larger vacancy snapshot remains the public state endpoint's data source.
async function publishedStatus(fetch, env, timestamp, job, observedAt=job.created_at) {
  const url=snapshotURL(env,timestamp);url.pathname=url.pathname.replace(/state\.json$/,'gateway-status.json');
  const response=await fetch(url.href,{cache:'no-store',redirect:'manual',
    headers:{Accept:'application/json','Cache-Control':'no-cache'},signal:AbortSignal.timeout(8000)});
  if(!response.ok)throw new Error('Status unavailable');
  const report=JSON.parse(await boundedText(response,8192)),attempt=Date.parse(report?.freshness?.last_attempt_at);
  if(!Number.isFinite(attempt)||attempt+1000<observedAt)return null;
  return terminalSnapshot(report,job);
}

export function createGateway(dependencies = {}) {
  const fetch = dependencies.fetch || globalThis.fetch;
  const now = dependencies.now || Date.now;
  const newId = dependencies.newId || (() => crypto.randomUUID().replaceAll('-', ''));

  async function snapshot(env, timestamp) {
    const response = await fetch(snapshotURL(env, timestamp).href, {cache:'no-store', redirect:'manual',
      headers:{'Accept':'application/json','Cache-Control':'no-cache'}, signal:AbortSignal.timeout(12_000)});
    if (!response.ok) throw new Error('Snapshot unavailable');
    const state = JSON.parse(await boundedText(response, MAX_SNAPSHOT_BYTES));
    if (!state || typeof state !== 'object' || Array.isArray(state)) throw new Error('Invalid snapshot');
    return state;
  }

  return async function handle(request, env,dispatchContext={}) {
    const origin = request.headers.get('Origin');
    const headers = {'Content-Type':'application/json; charset=utf-8','Cache-Control':'no-store','Vary':'Origin'};
    // Public GETs can be inspected without Origin; mutations require the actual site Origin.
    if (origin === env.ALLOWED_ORIGIN && origin) {
      headers['Access-Control-Allow-Origin'] = origin;
      headers['Access-Control-Allow-Methods'] = 'GET, POST, OPTIONS';
      headers['Access-Control-Allow-Headers'] = 'Content-Type, X-BA-Refresh';
      headers['Access-Control-Max-Age'] = '600';
    }
    const reply = (data, status = 200, extra = {}) => new Response(data === null ? null : JSON.stringify(data),
      {status,headers:{...headers,...extra}});
    const failure = (message, status) => reply({error:message}, status);
    const url = new URL(request.url);
    if (origin && origin !== env.ALLOWED_ORIGIN) return failure('Origen no permitido.', 403);
    if (url.pathname === '/internal/positions' || url.pathname === '/api/positions' || url.pathname.startsWith('/api/positions/')) {
      headers['X-Robots-Tag'] = 'noindex, nofollow, nosnippet';
      if (request.method === 'OPTIONS' && !origin) return failure('Origen no permitido.',403);
      return positionRoute(request,env,reply);
    }
    if (url.search) return failure('La petición no admite parámetros.', 400);
    if (!['/api/state','/api/refresh'].includes(url.pathname) && !/^\/api\/refresh\/[a-f0-9]{32}$/.test(url.pathname)) {
      return failure('Recurso no encontrado.',404);
    }
    if (request.method === 'OPTIONS') {
      return origin === env.ALLOWED_ORIGIN && origin ? reply(null,204) : failure('Origen no permitido.',403);
    }
    if (url.pathname === '/api/state' && request.method === 'GET') {
      try {
        const state = await snapshot(env, now());
        state.mode = 'server';
        state.capabilities = {...state.capabilities, source_check:configured(env) ? 'available' : 'snapshot_only'};
        return reply(state);
      } catch {
        try { snapshotURL(env, now()); } catch { return failure('Pasarela sin configurar.',503); }
        return failure('No se ha podido leer la última copia publicada.',502);
      }
    }
    if (!configured(env)) return failure('La comprobación pública aún no está configurada.',503);
    const repository = dependencies.repository || new D1Repository(env.DB);
    try {
      if (url.pathname === '/api/refresh' && request.method === 'POST') {
        if (!origin || origin !== env.ALLOWED_ORIGIN || request.headers.get('X-BA-Refresh') !== '1') {
          return failure('Falta la cabecera de comprobación u origen autorizado.',403);
        }
        if (request.headers.get('Content-Type')?.split(';')[0].trim().toLowerCase() !== 'application/json') {
          return failure('Se requiere JSON vacío.',415);
        }
        let body;
        try { body = JSON.parse(await boundedText(request,1024)); } catch { return failure('JSON vacío inválido.',400); }
        if (!body || Array.isArray(body) || typeof body !== 'object' || Object.keys(body).length) {
          return failure('Se requiere el objeto JSON vacío {}.',400);
        }
        const timestamp = now();
        const id = newId();
        if (!/^[a-f0-9]{32}$/.test(id)) throw new Error('Invalid generated identifier');
        const reservation = await repository.reserve(id, timestamp, new Date(timestamp).toISOString().slice(0,10));
        if (!reservation.job) return reply({error:'Se ha alcanzado el límite diario de comprobaciones.'},429,{'Retry-After':'300'});
        if (!reservation.acquired) return reply(jobData(reservation.job),200);
        const job = reservation.job;
        try {
          const response = await fetch(`https://api.github.com/repos/${env.GITHUB_REPOSITORY}/actions/workflows/refresh.yml/dispatches`,
            {method:'POST', redirect:'manual', headers:{'Accept':'application/vnd.github+json',
              'Authorization':`Bearer ${env.GITHUB_TOKEN}`, 'Content-Type':'application/json',
              'X-GitHub-Api-Version':'2022-11-28', 'User-Agent':'BolsaAbierta-Gateway'},
              body:JSON.stringify({ref:env.GITHUB_REF,inputs:{request_id:job.id,...(dispatchContext.trigger==='worker_cron'?{scheduled_time:dispatchContext.scheduled_time,clock_received_at:dispatchContext.clock_received_at,dispatch_at:dispatchContext.dispatch_at,trigger:'worker_cron'}:{})}}), signal:AbortSignal.timeout(12_000)});
          if ([400,401,403,404,422].includes(response.status)) {
            await repository.finish(job.id,'failed','GitHub ha rechazado la comprobación. Revisa la configuración del servicio.',now());
          } else if (response.status === 204) {
            await repository.message(job.id,'Comprobación solicitada. Esperando la publicación de GitHub Actions.');
          } else {
            await repository.message(job.id,'Respuesta de GitHub incierta. Esperando confirmación sin repetir la solicitud.');
          }
        } catch {
          await repository.message(job.id,'Envío a GitHub incierto. Esperando confirmación sin repetir la solicitud.');
        }
        return reply(jobData(await repository.read(job.id)),202);
      }
      if (/^\/api\/refresh\/[a-f0-9]{32}$/.test(url.pathname) && request.method === 'GET') {
        const id = url.pathname.split('/').at(-1);
        let job = await repository.read(id);
        if (!job) return failure('Comprobación no encontrada.',404);
        if (job.status !== 'queued') return reply(jobData(job));
        const timestamp = now();
        if (await repository.pollLease(id,timestamp)) {
          try {
            const status = await publishedStatus(fetch,env,timestamp,job);
            if (status) await repository.finish(id,status,
              status === 'completed' ? 'Comprobación publicada.' : status === 'partial' ? 'Comprobación parcial publicada. Se conservan los datos válidos.' : 'Comprobación fallida publicada. Se conserva la copia anterior.',now());
          } catch {
            await repository.message(id,'Aún no se puede confirmar la publicación. Se conserva la copia anterior.');
          }
        }
        job = await repository.read(id);
        if(job.status==='queued'&&timestamp>=job.deadline){
          await repository.finish(id,'failed','No se recibió una publicación confirmada dentro de 20 minutos. Se conserva la copia anterior.',timestamp);
          job=await repository.read(id);
        }
        return reply(jobData(job));
      }
      return failure('Método no permitido.',405);
    } catch { return failure('No se ha podido guardar o consultar la comprobación.',503); }
  };
}

// Opt-in HEAD probe. Never fetch/parse PDFs or nominal HTML in a scheduled invocation.
function officialFeed(env){
  const url=new URL(env.OFFICIAL_FEED_URL);
  if(url.protocol!=='https:'||url.hostname!=='www.carm.es'||url.port||url.username||url.password||url.hash||url.pathname!=='/web/pagina'||!/^\d{1,10}$/.test(url.searchParams.get('IDCONTENIDO')||'')||[...url.searchParams.keys()].some(k=>!['IDCONTENIDO','IDTIPO','RASTRO'].includes(k)))throw new Error('Invalid official feed');
  return url;
}
export function createScheduledGateway(dependencies={}){
  const fetch=dependencies.fetch||globalThis.fetch,now=dependencies.now||Date.now;
  const handler=createGateway(dependencies);
  return async function scheduled(controller,env){
    if(env.CRON_ENABLED!=='true'||!configured(env))return {status:'disabled'};
    let url;try{url=officialFeed(env);}catch{return {status:'invalid_config'};}
    const db=env.DB.withSession('first-primary'),start=now(),id=crypto.randomUUID().replaceAll('-','');
    const lease=await db.prepare('UPDATE gateway_probe SET lease_until=? WHERE singleton=1 AND lease_until<=? RETURNING validator,source_id').bind(start+30*60000,start).first();
    if(!lease)return {status:'shared_probe'};
    const source=url.searchParams.get('IDCONTENIDO');
    await db.prepare('INSERT INTO gateway_pilot_metrics(id,scheduled_at,started_at,source_id,phase,status) VALUES(?,?,?,?,?,?)').bind(id,controller.scheduledTime||start,start,source,'official_head','started').run();
    let status='failed',phase='official_head',generation=null;
    try{
      const response=await fetch(url.href,{method:'HEAD',redirect:'manual',headers:{Accept:'text/html'},signal:AbortSignal.timeout(8000)});
      if(!response.ok)status=response.status===429?'source_cap':response.status===403?'source_forbidden':'source_failed';
      else{
        const etag=response.headers.get('ETag'),modified=response.headers.get('Last-Modified');
        if((!etag&&!modified)||(etag?.length||0)>256||(modified?.length||0)>80)status='no_validator';
        else{
          const validator=JSON.stringify([etag,modified]);
          if(lease.validator===validator&&lease.source_id===source){
            await db.prepare('DELETE FROM gateway_probe_pending WHERE singleton=1').bind().run();status='unchanged';
          }else if(!lease.validator||lease.source_id!==source){
            await db.prepare('UPDATE gateway_probe SET validator=?,source_id=? WHERE singleton=1').bind(validator,source).run();status='baseline_recorded';
          }else{
            let pending=await db.prepare('SELECT * FROM gateway_probe_pending WHERE singleton=1').bind().first();
            if(!pending||pending.validator!==validator||pending.source_id!==source){
              pending={validator,source_id:source,observed_at:now(),request_id:null};
              await db.prepare(`INSERT INTO gateway_probe_pending(singleton,validator,source_id,observed_at,request_id) VALUES(1,?,?,?,NULL)
                ON CONFLICT(singleton) DO UPDATE SET validator=excluded.validator,source_id=excluded.source_id,observed_at=excluded.observed_at,request_id=NULL`).bind(validator,source,pending.observed_at).run();
            }
            let checked=pending.request_id?await db.prepare('SELECT * FROM gateway_jobs WHERE id=?').bind(pending.request_id).first():null;
            let confirmed=null;
            if(checked&&checked.created_at>=pending.observed_at){
              const repository=new D1Repository(env.DB),timestamp=now();
              // The half-hour clock exceeds the job's twenty-minute lease. Read
              // publication first, including late results of timed-out jobs.
              // Stored terminal flags alone never acknowledge the observation.
              try{confirmed=await publishedStatus(fetch,env,timestamp,checked,pending.observed_at);
                if(confirmed)await repository.finish(checked.id,confirmed,'Publicación correlacionada con la comprobación programada.',now());
              }catch{ /* Retain observation until bounded retry confirms it. */ }
              if(!confirmed&&checked.status==='queued'&&timestamp>=checked.deadline)
                await repository.finish(checked.id,'failed','No se recibió una publicación confirmada dentro del plazo.',timestamp);
              checked=await repository.read(checked.id);
            }
            // Only a newer, correlated, confirmed complete publication handles this observation.
            if(confirmed==='completed'){
              await db.batch([
                db.prepare('UPDATE gateway_probe SET validator=?,source_id=? WHERE singleton=1').bind(validator,source),
                db.prepare('DELETE FROM gateway_probe_pending WHERE singleton=1 AND validator=? AND source_id=? AND request_id=?').bind(validator,source,pending.request_id)
              ]);generation=pending.request_id;status='checked';
            }else{
              phase='shared_dispatch';
              const result=await handler(new Request('https://gateway.internal/api/refresh',{method:'POST',headers:{Origin:env.ALLOWED_ORIGIN,'Content-Type':'application/json','X-BA-Refresh':'1'},body:'{}'}),env,{trigger:'worker_cron',scheduled_time:new Date(controller.scheduledTime||start).toISOString(),clock_received_at:new Date(start).toISOString(),dispatch_at:new Date(now()).toISOString()});
              const job=await result.json();generation=job.id||null;
              status=result.status===429?'dispatch_cap':result.ok?(job.status==='failed'?'dispatch_failed':'shared_job'):'dispatch_failed';
              // Queued, uncertain, failed and reused older jobs never acknowledge the validator.
              if(job.id)await db.prepare('UPDATE gateway_probe_pending SET request_id=? WHERE singleton=1 AND validator=? AND source_id=?').bind(job.id,validator,source).run();
            }
          }
        }
      }
    }catch{status='probe_failed';}
    await db.prepare('UPDATE gateway_pilot_metrics SET ended_at=?,request_id=?,phase=?,status=? WHERE id=?').bind(now(),generation,phase,status,id).run();
    return {status};
  };
}
export default {fetch:createGateway(),scheduled:createScheduledGateway()};
