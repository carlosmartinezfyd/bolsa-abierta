import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { DatabaseSync } from 'node:sqlite';
import { createGateway, D1Repository } from '../gateway/worker.mjs';

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

test('20 concurrent requests reserve one shared job and one exact GitHub dispatch', async () => {
  const f = fixture();
  const replies = await Promise.all(Array.from({length:20}, () => f.handler(request(), env)));
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
  assert.equal(f.calls.length, 2);
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
  })}) };
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
    const results = await Promise.all(Array.from({length:20},async () => (await handler(request(),configuredEnv)).json()));
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
