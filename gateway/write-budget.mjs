/* DB-authoritative UTC reservations. Allocations never reset an existing day. */
export async function reserveWriteBudget(db,env,rows,overhead=8){
  const limit=Number(env.POSITION_DAILY_WRITE_LIMIT||70000),estimate=Number(env.POSITION_ROW_WRITE_ESTIMATE||32);
  if(!Number.isInteger(limit)||limit<1000||limit>90000||!Number.isInteger(estimate)||estimate<16||estimate>200)throw new Error('Invalid write budget');
  const id=crypto.randomUUID().replaceAll('-',''),reserved=rows*estimate+overhead;
  await db.batch([
    // Retain a monotonic snapshot of an earlier Worker's legacy allowance.
    db.prepare(`INSERT INTO position_write_allocations(reservation_id,day,charged)
      SELECT 'legacy:'||day,day,writes FROM position_write_budget WHERE singleton=1 AND day<>'' AND writes>0
      ON CONFLICT(reservation_id,day) DO UPDATE SET charged=MAX(charged,excluded.charged)`),
    db.prepare(`INSERT INTO position_write_reservations(id,day,reserved)
      SELECT ?,date('now'),? WHERE date('now')>=COALESCE((SELECT MAX(day) FROM position_write_allocations),'')
      AND COALESCE((SELECT SUM(charged) FROM position_write_allocations WHERE day=date('now')),0)
      +COALESCE((SELECT SUM(reserved) FROM position_write_reservations r JOIN position_write_reservation_leases l ON l.id=r.id WHERE settled=0 AND r.day<date('now') AND date(l.expires_at,'unixepoch')>=date('now')
        AND NOT EXISTS(SELECT 1 FROM position_write_allocations a WHERE a.reservation_id=r.id AND a.day=date('now'))),0)+?<=?`)
      .bind(id,reserved,reserved,limit),
    db.prepare(`INSERT INTO position_write_allocations(reservation_id,day,charged)
      SELECT id,day,reserved FROM position_write_reservations WHERE id=?`).bind(id)
  ]);
  const reservation=await db.prepare('SELECT id,day,reserved FROM position_write_reservations WHERE id=?').bind(id).first();
  return reservation?{...reservation,limit,overhead}:null;
}

export async function settleWriteBudget(db,reservation,results){
  const lease=await db.prepare("SELECT expires_at,unixepoch('now') AS now,date(expires_at,'unixepoch') AS expires_day,date('now') AS today FROM position_write_reservation_leases WHERE id=?").bind(reservation.id).first();
  const expired=!lease||lease.now>=lease.expires_at;
  const counters=results.map(r=>r.meta?.rows_written);
  const known=counters.every(x=>Number.isFinite(x)&&x>=0);
  const estimated=expired||!known;
  const measured=known?counters.reduce((n,x)=>n+x,0)+reservation.overhead:reservation.reserved;
  // Expiry keeps the reserved floor, but cannot erase larger actual counters
  // from a batch that finished before its settlement request reached D1.
  const actual=expired?Math.max(reservation.reserved,measured):measured;
  // If completion crosses midnight, charge the whole batch to both days.
  // This is conservative because precise per-statement completion times are absent.
  const allocationDay=expired?lease?.expires_day:lease?.today;
  await db.batch([
    db.prepare(`INSERT INTO position_write_allocations(reservation_id,day,charged)
      SELECT id,day,? FROM position_write_reservations WHERE id=?
      UNION ALL SELECT id,?,? FROM position_write_reservations WHERE id=? AND day<?
      UNION ALL SELECT id,date('now'),? FROM position_write_reservations WHERE id=? AND date('now')>?
      ON CONFLICT(reservation_id,day) DO UPDATE SET charged=excluded.charged`)
      .bind(actual,reservation.id,allocationDay||reservation.day,actual,reservation.id,allocationDay||reservation.day,reservation.overhead,reservation.id,allocationDay||reservation.day),
    db.prepare('UPDATE position_write_reservations SET settled=1 WHERE id=?').bind(reservation.id)
  ]);
  return {day:reservation.day,limit:reservation.limit,estimated,expired,batch_writes:actual};
}

export async function pendingWriteBudget(db){
  const row=await db.prepare("SELECT date('now','+1 day') AS next_day").bind().first();
  return {pending_budget:true,resume_after:row.next_day+'T00:00:00.000Z'};
}
