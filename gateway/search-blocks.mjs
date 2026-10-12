// Only derived inside the authenticated Worker from a stored, immutable block.
export function searchIndex(rows){
 const index=Object.create(null);
 rows.forEach((row,ordinal)=>{
  const chars=[...row.search_name],keys=new Set(['#'+row.list_number]);
  for(let i=2;i<chars.length;i++)keys.add(chars[i-2]+chars[i-1]+chars[i]);
  for(const key of keys)(index[key]??=[]).push(ordinal);
 });
 return JSON.stringify(index);
}
export async function completeSearchIndex(db,id){
 // Ready generations cannot acquire another block. Never acknowledge partial staging.
 await db.prepare(`INSERT OR IGNORE INTO position_search_complete(version_id)
 SELECT id FROM position_versions WHERE id=? AND ready=1
 AND EXISTS(SELECT 1 FROM position_blocks WHERE version_id=?) AND NOT EXISTS(
 SELECT 1 FROM position_blocks b LEFT JOIN position_search_blocks s ON s.version_id=b.version_id AND s.bucket=b.bucket
 WHERE b.version_id=? AND s.bucket IS NULL)`).bind(id,id,id).run();
}
export function searchPaths(tokens,numeric,query){
 if(numeric)return ['$."#'+query+'"'];
 const grams=new Set();
 // One scan of <=256 index rows, at most 12 scalar counts (not a G-row join).
 for(const token of [...tokens].sort((a,b)=>b.length-a.length)){
  const chars=[...token];
  for(const start of [0,Math.floor((chars.length-3)/2),chars.length-3]){
   if(grams.size<12)grams.add(chars.slice(start,start+3).join(''));
  }
 }
 return [...grams].map(gram=>'$."'+gram+'"');
}
export async function selectivePath(db,version,paths){
 const report=await db.prepare(`SELECT ${paths.map((_,i)=>`COALESCE(SUM(json_array_length(payload,?)),0) AS n${i}`).join(',')}
 FROM position_search_blocks WHERE version_id=?`).bind(...paths,version).all();
 const counts=report.results[0];
 const index=paths.reduce((best,_,i)=>counts['n'+i]<counts['n'+best]?i:best,0);
 return {path:paths[index],report};
}
export const indexedCandidates=`SELECT json_remove(record,'$.search_name') AS payload,
 json_extract(record,'$.search_name') AS search_name,json_extract(record,'$.specialty') AS specialty,
 json_extract(record,'$.rank') AS rank,json_extract(record,'$.id') AS id,
 json_extract(record,'$.list_number') AS list_number FROM (
 SELECT json_extract(b.payload,'$['||p.value||']') AS record
 FROM position_search_blocks s CROSS JOIN json_each(s.payload,?) p
 JOIN position_blocks b ON b.version_id=s.version_id AND b.bucket=s.bucket
 WHERE s.version_id=?)`;
