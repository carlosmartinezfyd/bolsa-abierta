import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { createGateway, D1Repository, createScheduledGateway } from '../gateway/worker.mjs';

const START = Date.parse('2026-10-01T12:00:00Z');
const ORIGIN = 'https://carlosmartinezfyd.github.io';
const env = { ALLOWED_ORIGIN: ORIGIN, SNAPSHOT_URL: `${ORIGIN}/bolsa-abierta/data/state.json`,
  GITHUB_REPOSITORY: 'carlosmartinezfyd/bolsa-abierta', GITHUB_REF: 'main', GITHUB_TOKEN: 'test-secret', DB: {} };

class MemoryRepository {
  constructor() { this.jobs = new Map(); this.gate = { cooldown_until: 0, lease_until: 0, day: '', dispatches: 0 }; }
  async reserve(id, now, day) {
    const gate = this.gate;
    if (gate.lease_until > now || gate.cooldown_until > now) return { acquired: false, job: this.jobs.get(gate.job_id) };
    if (gate.day === day && gate.dispatches >= 96) return { acquired: false, job: null };
    const job = { id, created_at: now, deadline: now + 20 * 60_000, status: 'queued', message: 'Comprobación en cola.', poll_until: 0 };
    this.jobs.set(id, job);
    this.gate = { job_id: id, cooldown_until: now + 5 * 60_000, lease_until: job.deadline, day,
      dispatches: gate.day === day ? gate.dispatches + 1 : 1 };
    return { acquired: true, job: {...job} };
  }
  async read(id) { return this.jobs.has(id) ? {...this.jobs.get(id)} : null; }
  async pollLease(id, now) {
    const job = this.jobs.get(id);
    if (job.status !== 'queued' || job.poll_until > now) return false;
    job.poll_until = now + 10_000;
    return true;
  }
  async finish(id, status, message, now) {
    const job = this.jobs.get(id);
    if (job.status !== 'queued') return;
    Object.assign(job, {status, message, completed_at: now});
    if (this.gate.job_id === id) this.gate.lease_until = 0;
  }
  async message(id, message) { const job = this.jobs.get(id); if (job.status === 'queued') job.message = message; }
}

function fixture(fetchOverride) {
  const repository = new MemoryRepository();
  let now = START, counter = 0;
  const calls = [];
  const fetch = async (url, options) => {
    calls.push({url: String(url), options});
    if (fetchOverride) return fetchOverride(url, options);
    return options.method === 'POST' ? new Response(null, {status: 204}) : Response.json({freshness:{status:'completed'}});
  };
  const handler = createGateway({ repository, fetch, now: () => now, newId: () => (++counter).toString(16).padStart(32, '0') });
  return { handler, repository, calls, advance: value => { now += value; } };
}

function request(path = '/api/refresh', options = {}) {
  return new Request('https://gateway.example' + path, { method: 'POST', headers: {'Origin': ORIGIN,
    'Content-Type':'application/json', 'X-BA-Refresh':'1'}, body: '{}', ...options });
}
function get(id) { return new Request(`https://gateway.example/api/refresh/${id}`, {headers:{Origin:ORIGIN}}); }

test('100 concurrent requests reserve one shared job and one exact GitHub dispatch', async () => {
  const f = fixture();
  const replies = await Promise.all(Array.from({length:100}, () => f.handler(request(), env)));
  const data = await Promise.all(replies.map(r => r.json()));
  assert.equal(new Set(data.map(d => d.id)).size, 1);
  assert.match(data[0].id, /^[a-f0-9]{32}$/);
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].url, 'https://api.github.com/repos/carlosmartinezfyd/bolsa-abierta/actions/workflows/refresh.yml/dispatches');
  assert.deepEqual(JSON.parse(f.calls[0].options.body), {ref:'main', inputs:{request_id:data[0].id}});
  assert.equal(f.calls[0].options.headers.Authorization, 'Bearer test-secret');
  assert.equal(f.repository.gate.dispatches, 1);
});

test('unknown Origin, URL params, body values and missing anti-CSRF header do not dispatch', async () => {
  const f = fixture();
  for (const req of [request('/api/refresh', {headers:{Origin:'https://evil.example'}}),
    request('/api/refresh?url=https://evil.example'), request('/api/refresh', {body:'{"ref":"evil"}'}),
    request('/api/refresh', {body:'[]'}), request('/api/refresh', {headers:{Origin:ORIGIN,'Content-Type':'application/json'}}),
    request('/api/refresh', {body:'x'.repeat(2048)})]) {
    const response = await f.handler(req, env);
    assert.ok(response.status >= 400);
  }
  assert.equal(f.calls.length, 0);
});

test('CORS preflight exposes only configured origin and headers', async () => {
  const f = fixture();
  const response = await f.handler(request('/api/refresh', {method:'OPTIONS', body:undefined}), env);
  assert.equal(response.status, 204);
  assert.equal(response.headers.get('Access-Control-Allow-Origin'), ORIGIN);
  assert.match(response.headers.get('Access-Control-Allow-Headers'), /X-BA-Refresh/);
  const denied = await f.handler(request('/api/refresh', {method:'OPTIONS', body:undefined, headers:{Origin:'https://evil.example'}}), env);
  assert.equal(denied.status, 403);
  assert.equal(denied.headers.get('Access-Control-Allow-Origin'), null);
});

test('state uses fixed snapshot, exposes capabilities and retains relative artifact URLs', async () => {
  const f = fixture(() => Response.json({mode:'static', documents:[{artifact_url:'documents/hash.pdf'}], freshness:{status:'partial'}}));
  const response = await f.handler(new Request('https://gateway.example/api/state'), env);
  const state = await response.json();
  assert.equal(state.mode, 'server');
  assert.equal(state.capabilities.source_check, 'available');
  assert.equal(state.documents[0].artifact_url, 'documents/hash.pdf');
  assert.equal(f.calls[0].url.split('?')[0], env.SNAPSHOT_URL);
  assert.equal(f.calls[0].options.cache, 'no-store');
  assert.equal(f.calls[0].options.redirect, 'manual');
  const disabled = await f.handler(new Request('https://gateway.example/api/state'), {...env, GITHUB_TOKEN:''});
  assert.equal((await disabled.json()).capabilities.source_check, 'snapshot_only');
  const missingOrigin = await f.handler(new Request('https://gateway.example/api/state'), {...env, ALLOWED_ORIGIN:''});
  assert.equal((await missingOrigin.json()).capabilities.source_check, 'snapshot_only');
});

test('redirects are rejected without following the snapshot or sending credentials to another host', async () => {
  const f = fixture((_url, options) => {
    assert.equal(options.redirect, 'manual');
    return new Response(null, {status:302, headers:{Location:'https://other.example/'}});
  });
  const state = await f.handler(new Request('https://gateway.example/api/state'), env);
  assert.equal(state.status,502);
  const dispatch = await f.handler(request(), env);
  const job = await dispatch.json();
  assert.equal(job.status,'queued');
  assert.match(job.message,/incierta/);
  assert.equal(f.calls.length,2);
  assert.ok(f.calls.every(call=>!call.url.includes('other.example')));
});

test('poll CAS permits one snapshot fetch per ten seconds and completes only matching id', async () => {
  let snapshot = {freshness:{request_id:'0'.repeat(32), status:'completed'}};
  const f = fixture((_url, options) => options.method === 'POST' ? new Response(null, {status:204}) : Response.json(snapshot));
  const job = await (await f.handler(request(), env)).json();
  const first = await Promise.all(Array.from({length:20}, async () => (await f.handler(get(job.id), env)).json()));
  assert.ok(first.every(j => j.status === 'queued'));
  assert.equal(f.calls.length, 2);
  snapshot = {freshness:{request_id:job.id, status:'partial', last_attempt_at:new Date(START).toISOString()}};
  await f.handler(get(job.id), env);
  assert.equal(f.calls.length, 2);
  f.advance(10_000);
  const completed = await (await f.handler(get(job.id), env)).json();
  assert.equal(completed.status, 'partial');
  assert.equal(f.calls.length, 3);
  await f.handler(get(job.id), env);
  assert.equal(f.calls.length, 3);
});

test('stale snapshot with same id and old last_attempt_at cannot complete job', async () => {
  let id;
  const f = fixture((_url, options) => options.method === 'POST' ? new Response(null, {status:204}) : Response.json({freshness:{request_id:id,status:'completed',last_attempt_at:'2026-09-30T00:00:00Z'}}));
  id = (await (await f.handler(request(), env)).json()).id;
  assert.equal((await (await f.handler(get(id), env)).json()).status, 'queued');
});

test('retained snapshots above two MB remain readable while sixteen MiB guard rejects excess', async () => {
  const f = fixture(() => Response.json({freshness:{status:'completed'},history:'x'.repeat(2_100_000)}));
  assert.equal((await f.handler(new Request('https://gateway.example/api/state'),env)).status,200);
  const oversized = fixture(() => new Response('{}',{headers:{'Content-Length':String(16*1024*1024+1)}}));
  assert.equal((await oversized.handler(new Request('https://gateway.example/api/state'),env)).status,502);
});

test('uncertain dispatch does not re-dispatch and job expires after lease', async () => {
  const f = fixture(() => { throw new Error('network reset, acceptance unknown'); });
  const first = await (await f.handler(request(), env)).json();
  assert.equal(first.status, 'queued');
  const second = await (await f.handler(request(), env)).json();
  assert.equal(second.id, first.id);
  assert.equal(f.calls.length, 1);
  f.advance(20 * 60_000);
  const expired = await (await f.handler(get(first.id), env)).json();
  assert.equal(expired.status, 'failed');
});

test('daily quota and cooldown are durable and reset only on UTC day change', async () => {
  const f = fixture();
  f.repository.gate = {day:'2026-10-01', dispatches:96, cooldown_until:0, lease_until:0};
  const quota = await f.handler(request(), env);
  assert.equal(quota.status, 429);
  assert.equal(f.calls.length, 0);
  f.advance(24 * 60 * 60_000);
  const job = await (await f.handler(request(), env)).json();
  await f.repository.finish(job.id, 'completed', '', START + 24 * 60 * 60_000);
  assert.equal((await (await f.handler(request(), env)).json()).id, job.id);
  assert.equal(f.calls.length, 1);
  f.advance(5 * 60_000);
  const fresh = await (await f.handler(request(), env)).json();
  assert.notEqual(fresh.id, job.id);
  assert.equal(f.calls.length, 2);
});

test('old job result cannot release a newer job gate', async () => {
  const f = fixture();
  const old = await (await f.handler(request(), env)).json();
  f.advance(20 * 60_000);
  const newer = await (await f.handler(request(), env)).json();
  await f.handler(get(old.id), env);
  assert.equal(f.repository.gate.job_id, newer.id);
  assert.equal((await (await f.handler(request(), env)).json()).id, newer.id);
  assert.equal(f.calls.filter(c=>c.options.method==='POST').length, 2);
});

test('unknown jobs, unsafe config, upstream failure and malformed snapshot fail closed', async () => {
  const f = fixture(() => Response.json([], {status:200}));
  assert.equal((await f.handler(get('f'.repeat(32)), env)).status, 404);
  assert.equal((await f.handler(get('../secrets'), env)).status, 404);
  assert.equal((await f.handler(request(), {...env,GITHUB_REPOSITORY:'owner/repo/../evil'})).status, 503);
  assert.equal((await f.handler(new Request('https://gateway.example/api/state'), {...env,SNAPSHOT_URL:'http://localhost/state.json'})).status, 503);
  assert.equal((await f.handler(new Request('https://gateway.example/api/state'), env)).status, 502);
});

test('D1 adapter uses one CAS quota reservation with bound values and primary session', async () => {
  const statements = [];
  const database = { withSession: mode => { assert.equal(mode,'first-primary'); return database; },
    prepare: sql => ({ bind: (...args) => ({ first: async () => { statements.push({sql,args}); return null; }, run: async () => { statements.push({sql,args}); return {}; } }) }) };
  const repository = new D1Repository(database);
  assert.deepEqual(await repository.reserve('1'.repeat(32), START, '2026-10-01'), {acquired:false,job:null});
  const cas = statements[0];
  assert.match(cas.sql, /UPDATE gateway_gate/);
  assert.match(cas.sql, /dispatches < 96/);
  assert.match(cas.sql, /RETURNING/);
  assert.ok(cas.args.includes('1'.repeat(32)));
  assert.ok(!cas.sql.includes('1'.repeat(32)));
});

function sqliteD1() {
  const db = new DatabaseSync(':memory:');
  db.exec(readFileSync(new URL('../gateway/schema.sql', import.meta.url), 'utf8'));
  const binding = { withSession: () => binding, prepare: sql => ({bind: (...args) => ({
    first: async () => db.prepare(sql).get(...args) || null,
    run: async () => db.prepare(sql).run(...args),
  })}),async batch(statements){db.exec('BEGIN');try{const result=[];for(const s of statements)result.push(await s.run());db.exec('COMMIT');return result;}catch(error){db.exec('ROLLBACK');throw error;}} };
  return {db,binding};
}

test('real SQLite schema and production D1 CAS share dispatch under concurrency and persist across handlers', async () => {
  const {db,binding} = sqliteD1();
  let dispatches = 0, snapshotReads = 0, now = START, id;
  const fetch = async (_url, options) => {
    if (options.method === 'POST') { dispatches++; return new Response(null,{status:204}); }
    snapshotReads++;
    return Response.json({freshness:{request_id:id,status:'completed',last_attempt_at:new Date(now).toISOString()}});
  };
  let sequence = 0;
  const deps = {fetch,now:()=>now,newId:()=>(++sequence).toString(16).padStart(32,'0')};
  const handler = createGateway(deps), configuredEnv = {...env,DB:binding};
  try {
    const results = await Promise.all(Array.from({length:100},async () => (await handler(request(),configuredEnv)).json()));
    id = results[0].id;
    assert.equal(new Set(results.map(r=>r.id)).size,1);
    assert.equal(dispatches,1);
    assert.equal(db.prepare('SELECT dispatches FROM gateway_gate').get().dispatches,1);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM gateway_jobs').get().n,1);
    const restarted = createGateway(deps);
    assert.equal((await (await restarted(request(),configuredEnv)).json()).id,id);
    await Promise.all(Array.from({length:20},()=>restarted(get(id),configuredEnv)));
    assert.equal(snapshotReads,1);
    assert.equal(db.prepare('SELECT status FROM gateway_jobs WHERE id=?').get(id).status,'completed');
    assert.equal(db.prepare('SELECT lease_until FROM gateway_gate').get().lease_until,0);
    now += 5 * 60_000;
    assert.notEqual((await (await restarted(request(),configuredEnv)).json()).id,id);
    assert.equal(dispatches,2);
  } finally { db.close(); }
});

test('production D1 recovery does not dispatch a quota reservation left by an interrupted request', async () => {
  const {db,binding} = sqliteD1();
  const id = 'a'.repeat(32);
  db.prepare('UPDATE gateway_gate SET job_id=?,created_at=?,lease_until=?,cooldown_until=?,day=?,dispatches=1').run(id,START,START+20*60_000,START+5*60_000,'2026-10-01');
  let dispatches=0;
  const handler=createGateway({now:()=>START,newId:()=> 'b'.repeat(32),fetch:async()=>{dispatches++;return new Response(null,{status:204});}});
  try {
    const result=await (await handler(request(),{...env,DB:binding})).json();
    assert.equal(result.id,id);
    assert.equal(dispatches,0);
    assert.equal(db.prepare('SELECT COUNT(*) AS n FROM gateway_jobs').get().n,1);
  } finally {db.close();}
});

test('bounded cron uses official HEAD validators, one durable probe lease and shared visitor dispatch gate',async()=>{
 const {db,binding}=sqliteD1();let now=START,heads=0,dispatches=0,validator='"v1"',sequence=0;
 const configuredEnv={...env,DB:binding,CRON_ENABLED:'true',OFFICIAL_FEED_URL:'https://www.carm.es/web/pagina?IDCONTENIDO=3985&IDTIPO=100'};
 const fetch=async(url,options)=>{
  assert.equal(options.redirect,'manual');
  if(options.method==='HEAD'){heads++;assert.ok(String(url).startsWith('https://www.carm.es/web/pagina?'));return new Response(null,{headers:{ETag:validator}});}
  assert.equal(options.method,'POST');dispatches++;return new Response(null,{status:204});
 };
 const deps={fetch,now:()=>now,newId:()=>(++sequence).toString(16).padStart(32,'0')};
 const scheduled=createScheduledGateway(deps),visitor=createGateway(deps);
 try{
  const baseline=await Promise.all(Array.from({length:100},()=>scheduled({scheduledTime:now},configuredEnv)));
  assert.equal(heads,1);assert.equal(dispatches,0);assert.equal(baseline.filter(r=>r.status==='baseline_recorded').length,1);
  now+=3600000;assert.equal((await scheduled({scheduledTime:now},configuredEnv)).status,'unchanged');assert.equal(dispatches,0);
  now+=3600000;validator='"v2"';
  const [cron,publicReply]=await Promise.all([scheduled({scheduledTime:now},configuredEnv),visitor(request(),configuredEnv)]);
  assert.equal(cron.status,'shared_job');assert.equal(publicReply.status,202);assert.equal(dispatches,1);
  assert.equal(db.prepare('SELECT dispatches FROM gateway_gate').get().dispatches,1);
  const metrics=db.prepare('SELECT * FROM gateway_pilot_metrics ORDER BY started_at').all();
  assert.equal(metrics.length,3);assert.ok(metrics.every(m=>m.ended_at>=m.started_at));assert.equal(metrics[2].source_id,'3985');
  assert.match(metrics[2].request_id,/^[a-f0-9]{32}$/);assert.equal(metrics[2].generation_id,null);
  assert.ok(!JSON.stringify(metrics).includes('test-secret'));
 }finally{db.close();}
});

test('cron rejects redirects, unavailable validators, source403 and arbitrary configured destinations without dispatch',async()=>{
 for(const response of [new Response(null,{status:302,headers:{Location:'https://evil.example/'}}),new Response(null),new Response(null,{status:403})]){
  const {db,binding}=sqliteD1();let calls=0;
  const cron=createScheduledGateway({now:()=>START,fetch:async(_url,options)=>{calls++;assert.equal(options.method,'HEAD');assert.equal(options.redirect,'manual');return response;}});
  const configuredEnv={...env,DB:binding,CRON_ENABLED:'true',OFFICIAL_FEED_URL:'https://www.carm.es/web/pagina?IDCONTENIDO=3985&IDTIPO=100'};
  try{
   assert.ok(['source_failed','no_validator','source_forbidden'].includes((await cron({scheduledTime:START},configuredEnv)).status));assert.equal(calls,1);
   assert.equal(db.prepare('SELECT dispatches FROM gateway_gate').get().dispatches,0);
   assert.equal((await cron({}, {...configuredEnv,OFFICIAL_FEED_URL:'https://evil.example/'})).status,'invalid_config');
   assert.equal((await cron({}, {...configuredEnv,CRON_ENABLED:'false'})).status,'disabled');assert.equal(calls,1);
  }finally{db.close();}
 }
});

test('cron keeps a changed validator pending when cooldown reuses an older completed visitor',async()=>{
 const {db,binding}=sqliteD1();let now=Date.parse('2026-10-04T12:00:00Z'),validator='v1',dispatches=0,sequence=0,published=null;
 const deps={now:()=>now,newId:()=>(++sequence).toString(16).padStart(32,'0'),fetch:async(_url,o)=>{if(o.method==='HEAD')return new Response(null,{headers:{ETag:validator}});if(o.method==='POST'){dispatches++;return new Response(null,{status:204});}return Response.json(published);}};
 const configuredEnv={...env,DB:binding,CRON_ENABLED:'true',OFFICIAL_FEED_URL:'https://www.carm.es/web/pagina?IDCONTENIDO=3985&IDTIPO=100'};
 const cron=createScheduledGateway(deps),visitor=createGateway(deps),repository=new D1Repository(binding);
 try{
  assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'baseline_recorded');
  now=Date.parse('2026-10-04T12:29:00Z');const older=await(await visitor(request(),configuredEnv)).json();
  await repository.finish(older.id,'completed','confirmed',Date.parse('2026-10-04T12:29:30Z'));
  now=Date.parse('2026-10-04T12:30:01Z');validator='v2';assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'shared_job');
  assert.equal(dispatches,1);assert.equal(JSON.parse(db.prepare('SELECT validator FROM gateway_probe').get().validator)[0],'v1');
  assert.equal(db.prepare('SELECT request_id FROM gateway_probe_pending').get().request_id,older.id);
  now=Date.parse('2026-10-04T13:01:00Z');assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'shared_job');
  const pending=db.prepare('SELECT * FROM gateway_probe_pending').get();assert.notEqual(pending.request_id,older.id);assert.equal(dispatches,2);
  assert.equal(JSON.parse(db.prepare('SELECT validator FROM gateway_probe').get().validator)[0],'v1');
  await repository.finish(pending.request_id,'completed','confirmed newer source check',now+1000);
  published={freshness:{request_id:pending.request_id,status:'completed',last_attempt_at:new Date(now+1000).toISOString()}};
  now=Date.parse('2026-10-04T13:32:00Z');assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'checked');
  assert.equal(JSON.parse(db.prepare('SELECT validator FROM gateway_probe').get().validator)[0],'v2');assert.equal(db.prepare('SELECT COUNT(*) n FROM gateway_probe_pending').get().n,0);assert.equal(dispatches,2);
 }finally{db.close();}
});

test('accepted failed and uncertain cron checks keep pending observations and retry only after shared leases',async()=>{
 for(const uncertain of [false,true]){
  const {db,binding}=sqliteD1();let now=START,validator='v1',dispatches=0,sequence=0;
  const deps={now:()=>now,newId:()=>(++sequence).toString(16).padStart(32,'0'),fetch:async(_url,o)=>{if(o.method==='HEAD')return new Response(null,{headers:{ETag:validator}});if(o.method!=='POST')return Response.json({});dispatches++;if(uncertain)throw new Error('acceptance unknown');return new Response(null,{status:204});}};
  const configuredEnv={...env,DB:binding,CRON_ENABLED:'true',OFFICIAL_FEED_URL:'https://www.carm.es/web/pagina?IDCONTENIDO=3985&IDTIPO=100'};
  const cron=createScheduledGateway(deps),visitor=createGateway(deps),repository=new D1Repository(binding);
  try{
   await cron({scheduledTime:now},configuredEnv);now+=30*60000;validator='v2';assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'shared_job');
   const first=db.prepare('SELECT * FROM gateway_probe_pending').get();assert.ok(first.request_id);assert.equal(dispatches,1);
   await Promise.all(Array.from({length:100},()=>visitor(request(),configuredEnv)));assert.equal(dispatches,1);
   if(!uncertain)await repository.finish(first.request_id,'failed','source processing failed',now+1000);
   now+=31*60000;assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'shared_job');
   assert.equal(dispatches,2);assert.notEqual(db.prepare('SELECT request_id FROM gateway_probe_pending').get().request_id,first.request_id);
   assert.equal(JSON.parse(db.prepare('SELECT validator FROM gateway_probe').get().validator)[0],'v1');
  }finally{db.close();}
 }
});

test('cron-only jobs confirm through a bounded freshness publication without visitor polling',async()=>{
 const {db,binding}=sqliteD1();let now=START,validator='v1',dispatches=0,statusReads=0,sequence=0,published=null;
 const deps={now:()=>now,newId:()=>(++sequence).toString(16).padStart(32,'0'),fetch:async(url,o)=>{
  if(o.method==='HEAD')return new Response(null,{headers:{ETag:validator}});
  if(o.method==='POST'){dispatches++;return new Response(null,{status:204});}
  statusReads++;assert.equal(new URL(url).pathname,'/bolsa-abierta/data/gateway-status.json');assert.equal(o.redirect,'manual');return Response.json(published);
 }};
 const configuredEnv={...env,DB:binding,CRON_ENABLED:'true',OFFICIAL_FEED_URL:'https://www.carm.es/web/pagina?IDCONTENIDO=3985&IDTIPO=100'};
 const cron=createScheduledGateway(deps);
 try{
  await cron({scheduledTime:now},configuredEnv);now+=30*60000;validator='v2';await cron({scheduledTime:now},configuredEnv);
  const pending=db.prepare('SELECT * FROM gateway_probe_pending').get();
  published={freshness:{request_id:pending.request_id,status:'completed',last_attempt_at:new Date(now+1000).toISOString()}};
  // The next natural half-hour tick follows the twenty-minute job deadline.
  now+=30*60000;
  assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'checked');assert.equal(statusReads,1);assert.equal(dispatches,1);
  assert.equal(db.prepare('SELECT status FROM gateway_jobs WHERE id=?').get(pending.request_id).status,'completed');
  assert.equal(JSON.parse(db.prepare('SELECT validator FROM gateway_probe').get().validator)[0],'v2');
 }finally{db.close();}
});

test('public polling and cron require aggregate completion even when vacancy state or stored job says completed',async()=>{
 const {db,binding}=sqliteD1();let now=START,validator='v1',dispatches=0,sequence=0,published=null;
 const deps={now:()=>now,newId:()=>(++sequence).toString(16).padStart(32,'0'),fetch:async(url,o)=>{
  if(o.method==='HEAD')return new Response(null,{headers:{ETag:validator}});
  if(o.method==='POST'){dispatches++;return new Response(null,{status:204});}
  if(new URL(url).pathname.endsWith('/state.json'))return Response.json({freshness:{...published.freshness,status:'completed'}});
  assert.ok(new URL(url).pathname.endsWith('/gateway-status.json'));return Response.json(published);
 }};
 const configuredEnv={...env,DB:binding,CRON_ENABLED:'true',OFFICIAL_FEED_URL:'https://www.carm.es/web/pagina?IDCONTENIDO=3985&IDTIPO=100'};
 const cron=createScheduledGateway(deps),visitor=createGateway(deps),repository=new D1Repository(binding);
 try{
  await cron({scheduledTime:now},configuredEnv);now+=30*60000;validator='v2';await cron({scheduledTime:now},configuredEnv);
  const pending=db.prepare('SELECT * FROM gateway_probe_pending').get();
  published={freshness:{request_id:pending.request_id,status:'partial',last_attempt_at:new Date(now+1000).toISOString()}};
  now+=1000;assert.equal((await(await visitor(get(pending.request_id),configuredEnv)).json()).status,'partial');
  // A legacy writer or old Worker can leave a completed flag; it is not source evidence.
  db.prepare("UPDATE gateway_jobs SET status='completed' WHERE id=?").run(pending.request_id);
  now+=30*60000;assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'shared_job');
  assert.equal(JSON.parse(db.prepare('SELECT validator FROM gateway_probe').get().validator)[0],'v1');assert.equal(dispatches,2);
  const newer=db.prepare('SELECT * FROM gateway_probe_pending').get();
  // Even a visitor timeout cannot discard a later, correlated successful publication.
  await repository.finish(newer.request_id,'failed','visitor timeout',now+20*60000);
  published={freshness:{request_id:newer.request_id,status:'completed',last_attempt_at:new Date(now+21*60000).toISOString()}};
  now+=30*60000;assert.equal((await cron({scheduledTime:now},configuredEnv)).status,'checked');
  assert.equal(JSON.parse(db.prepare('SELECT validator FROM gateway_probe').get().validator)[0],'v2');assert.equal(dispatches,2);
 }finally{db.close();}
});
