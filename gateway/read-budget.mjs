// Bound public JSON scans below the Free account allowance. Metadata queries
// and authenticated validation retain a separate two-million-read margin.
export async function reserveReadBudget(db,estimate){
 const row=await db.prepare(`INSERT INTO position_read_budget(day,used,requests) VALUES(date('now'),?,1)
 ON CONFLICT(day) DO UPDATE SET used=used+excluded.used,requests=requests+1
 WHERE used+excluded.used<=3000000 AND requests<2000 RETURNING day`).bind(estimate).first();
 return row?{day:row.day,estimate}:null;
}
export async function clientReadKey(request,env){
 const address=request.headers.get('CF-Connecting-IP');
 // This header is overwritten by Cloudflare, never taken from a request body.
 if(!address||!env.POSITION_INGEST_TOKEN)return null;
 const day=new Date().toISOString().slice(0,10),encoder=new TextEncoder();
 const key=await crypto.subtle.importKey('raw',encoder.encode(env.POSITION_INGEST_TOKEN),{name:'HMAC',hash:'SHA-256'},false,['sign']);
 const hash=await crypto.subtle.sign('HMAC',key,encoder.encode(day+':'+address));
 const client=[...new Uint8Array(hash)].map(b=>b.toString(16).padStart(2,'0')).join('');
 return {day,client};
}
export async function allowClientRead(db,key){
 if(!key)return true;
 const row=await db.prepare('SELECT requests FROM position_client_budget WHERE day=? AND client=?').bind(key.day,key.client).first();
 return !row||row.requests<120;
}
export async function chargeClientRead(db,key){
 if(!key)return null;
 const row=await db.prepare(`INSERT INTO position_client_budget(day,client,requests) VALUES(?,?,1)
 ON CONFLICT(day,client) DO UPDATE SET requests=requests+1 WHERE requests<120 RETURNING requests`).bind(key.day,key.client).all();
 return row;
}
export async function settleReadBudget(db,reservation,reports){
 const counts=reports.map(r=>r.meta?.rows_read);
 const actual=counts.every(n=>Number.isInteger(n)&&n>=0)?counts.reduce((a,b)=>a+b,0)+32:reservation.estimate;
 await db.prepare(`UPDATE position_read_budget SET used=MAX(0,used-?+?) WHERE day=?`).bind(reservation.estimate,actual,reservation.day).run();
 // If a request crossed UTC midnight, also charge the new day conservatively.
 await db.prepare(`INSERT INTO position_read_budget(day,used,requests) SELECT date('now'),?,1 WHERE date('now')<>?
 ON CONFLICT(day) DO UPDATE SET used=used+excluded.used,requests=requests+1`).bind(actual,reservation.day).run();
}
