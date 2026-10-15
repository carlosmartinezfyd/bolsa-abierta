import test from 'node:test';
import assert from 'node:assert/strict';
import {assessHealth,createWatchdog} from '../gateway/watchdog.mjs';
import {DatabaseSync} from 'node:sqlite';
import {readFileSync} from 'node:fs';
const now=Date.parse('2026-10-13T10:00:00Z');
const active={id:'a'.repeat(64),checked_at:'2026-10-13T09:50:00Z',row_count:10};
const health={published_at:'2026-10-13T09:55:00Z',run_status:'partial',position_status:'verified',
 origin_check_complete:true,checked_at:active.checked_at,active_version:active.id,record_count:10,
 vacancy_status:'partial',pending_documents:29,unavailable_documents:17,cache_status:'ready',recovery_status:'verified'};
test('ready cached originals cannot hide a failed or missing restore drill',()=>{
 for(const recovery_status of [undefined,'failed','unavailable']){
  const report=assessHealth({...health,recovery_status},active,now);
  assert.ok(report.issues.includes('recovery_unavailable'));
  assert.equal(report.needs_refresh,false);
 }
});
test('fresh partial coverage remains explicit, without redispatching unchanged unknown documents',()=>{
 const report=assessHealth(health,active,now);
 assert.equal(report.needs_refresh,false);assert.equal(report.status,'partial');
 assert.ok(report.issues.includes('coverage_partial'));
});
test('freshness cannot be fabricated by recent publication, cached recovery or a future timestamp',()=>{
 for(const change of [{checked_at:'2026-10-12T00:00:00Z'},{checked_at:'2099-01-01T00:00:00Z'},
  {origin_check_complete:false},{active_version:'b'.repeat(64)}]){
  const report=assessHealth({...health,...change,published_at:'2026-10-13T09:00:00Z'},active,now);
  assert.equal(report.needs_refresh,true);
 }
});
test('zero pending counters cannot turn incomplete discovery into complete coverage',()=>{
 const report=assessHealth({...health,pending_documents:0,unavailable_documents:0,vacancy_status:'success',coverage_complete:false},active,now);
 assert.equal(report.status,'partial');assert.ok(report.issues.includes('coverage_partial'));
});
test('watchdog continues after four attempts while spacing requests and avoiding active workflows',async()=>{
 const db=new DatabaseSync(':memory:');
 for(const file of ['0003-search-blocks.sql','0004-watchdog.sql'])db.exec(readFileSync(new URL('../gateway/migrations/'+file,import.meta.url),'utf8'));
 const binding={withSession:()=>binding,prepare:sql=>({args:[],bind(...a){this.args=a;return this;},async first(){return db.prepare(sql).get(...this.args)||null;},async run(){return {meta:db.prepare(sql).run(...this.args)};}})};
 const env={DB:binding,WATCHDOG_ENABLED:'true',SNAPSHOT_URL:'https://carlosmartinezfyd.github.io/bolsa-abierta/data/state.json',GITHUB_TOKEN:'test',GITHUB_REPOSITORY:'carlosmartinezfyd/bolsa-abierta',GITHUB_REF:'main'};
 let time=now,calls=0,running=false;
 const watchdog=createWatchdog({now:()=>time,readActive:async()=>active,
  readPublished:async()=>({...health,checked_at:'2026-10-12T00:00:00Z'}),isRunning:async()=>running,
  dispatch:async()=>{calls++;return {id:'b'.repeat(32),status:'queued'};}});
 try{
  await watchdog({},env);await watchdog({},env);assert.equal(calls,1);
  time+=3600001;running=true;await watchdog({},env);assert.equal(calls,1);
  time+=3600001;running=false;await watchdog({},env);assert.equal(calls,2);
  db.exec('UPDATE gateway_watchdog SET retries=4,next_retry=0,lease_until=0');
  time+=3600001;await watchdog({},env);assert.equal(calls,3);
  assert.equal(db.prepare('SELECT retries FROM gateway_watchdog').get().retries,5);
  time+=30*60000;await watchdog({},env);assert.equal(calls,3);
  time+=30*60000;await watchdog({},env);assert.equal(calls,4);
  assert.ok(JSON.parse(db.prepare('SELECT issues FROM gateway_watchdog').get().issues).includes('position_stale'));
 }finally{db.close();}
});

test('uncertain dispatches keep their hourly reservation across midnight without stopping later recovery',async()=>{
 const db=new DatabaseSync(':memory:');
 for(const file of ['0003-search-blocks.sql','0004-watchdog.sql'])db.exec(readFileSync(new URL('../gateway/migrations/'+file,import.meta.url),'utf8'));
 const binding={withSession:()=>binding,prepare:sql=>({args:[],bind(...a){this.args=a;return this;},async first(){return db.prepare(sql).get(...this.args)||null;},async run(){return {meta:db.prepare(sql).run(...this.args)};}})};
 const env={DB:binding,WATCHDOG_ENABLED:'true'};
 let time=Date.parse('2026-10-13T23:40:00Z'),calls=0,recovered=false;
 const watchdog=createWatchdog({now:()=>time,readActive:async()=>({...active,checked_at:new Date(time).toISOString()}),
  readPublished:async()=>recovered?{...health,published_at:new Date(time).toISOString(),checked_at:new Date(time).toISOString()}:health,
  isRunning:async()=>false,dispatch:async()=>{calls++;throw new Error('Response lost');}});
 try{
  assert.equal((await watchdog({},env)).dispatch_status,'dispatch_unavailable');
  time+=30*60000;await watchdog({},env);assert.equal(calls,1);
  for(let attempt=2;attempt<=7;attempt++){
   time+=attempt===2?30*60000:3600000;
   await watchdog({},env);assert.equal(calls,attempt);
  }
  assert.equal(db.prepare('SELECT retries FROM gateway_watchdog').get().retries,6);
  recovered=true;time+=3600000;
  assert.equal((await watchdog({},env)).dispatch_status,'not_needed');assert.equal(calls,7);
 }finally{db.close();}
});
