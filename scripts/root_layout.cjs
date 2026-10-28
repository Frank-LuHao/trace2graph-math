// Center an explicit problem root without changing the mathematical graph.
// Input/output: measured layout {width,height,nodes,edges}; no DOM or trace access.
const VERSION='centered-problem-root/1.0';
const clone=x=>JSON.parse(JSON.stringify(x));
function simplify(points){
 const out=[];
 for(const p of points){
  if(out.length&&Math.hypot(p[0]-out.at(-1)[0],p[1]-out.at(-1)[1])<.01)continue;
  out.push(p);
  while(out.length>=3){const [a,b,c]=out.slice(-3);if(Math.abs((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))<.01)out.splice(-2,1);else break;}
 }
 return out;
}
function centerRoot(input,rootId){
 const L=clone(input),byId=new Map(L.nodes.map(n=>[n.id,n])),root=byId.get(rootId);
 if(!root)throw Error('Explicit root is absent from layout: '+rootId);
 if(L.root_presentation?.version===VERSION&&L.root_presentation.root_id===rootId&&Math.abs(root.x+root.w/2-L.width/2)<.01)return L;
 const cx=L.width/2,originalCX=root.x+root.w/2;
 // Cycles and disconnected/multi-root drawings must retain their established routes.
 // Symmetric padding centers their declared initial node without inventing a top root.
 function pad(reason){
  const left=Math.min(0,...L.nodes.map(n=>n.x),...L.edges.flatMap(e=>e.points.map(p=>p[0])));
  const right=Math.max(L.width,...L.nodes.map(n=>n.x+n.w),...L.edges.flatMap(e=>e.points.map(p=>p[0])));
  const half=Math.max(originalCX-left,right-originalCX),dx=half-originalCX;
  for(const n of L.nodes)n.x+=dx;
  for(const e of L.edges)e.points=e.points.map(([x,y])=>[x+dx,y]);
  L.width=2*half;
  L.root_presentation={version:VERSION,root_id:rootId,mode:'symmetric-padding',reason,moved_node_ids:[],added_height:0};
  return L;
 }
 if(L.edges.some(e=>e.target===rootId))return pad('The declared initial state has incoming edges.');
 const prefix=[root],seen=new Set([rootId]);
 while(true){
  const last=prefix.at(-1),out=L.edges.filter(e=>e.source===last.id);
  if(out.length!==1)break;
  const next=byId.get(out[0].target);
  if(!next||seen.has(next.id)||L.edges.filter(e=>e.target===next.id).length!==1||next.y<last.y+last.h)break;
  // Only an isolated opening chain can move; stop before any parallel component.
  if(L.nodes.some(n=>!seen.has(n.id)&&n.id!==next.id&&n.y<next.y+next.h))break;
  prefix.push(next);seen.add(next.id);
 }
 const rest=L.nodes.filter(n=>!seen.has(n.id)),last=prefix.at(-1),bottom=last.y+last.h;
 if(rest.some(n=>n.y<bottom+12))return pad('Other nodes share the opening rows.');
 const exits=L.edges.filter(e=>seen.has(e.source)&&!seen.has(e.target));
 if(exits.some(e=>e.source!==last.id)||L.edges.some(e=>!seen.has(e.source)&&seen.has(e.target)))return pad('Opening chain has a return or external dependency.');
 const cut=rest.length?Math.min(...rest.map(n=>n.y))-12:bottom+24;
 const suffixes=[];
 for(const e of exits){
  let suffix;
  for(let i=1;i<e.points.length;i++){
   const a=e.points[i-1],b=e.points[i];
   if(Math.abs(a[0]-b[0])<.01&&a[1]<=cut&&b[1]>=cut){suffix=[[a[0],cut],...e.points.slice(i)];break;}
  }
  if(!suffix)return pad('An outgoing route has no safe horizontal cut.');
  suffixes.push({edge:e,points:suffix,x:suffix[0][0]});
 }
 const left=[...new Set(suffixes.filter(s=>s.x<cx-.01).map(s=>s.x))].sort((a,b)=>a-b);
 const right=[...new Set(suffixes.filter(s=>s.x>cx+.01).map(s=>s.x))].sort((a,b)=>b-a);
 const lanes=Math.max(left.length,right.length,1),needed=24+(lanes-1)*8;
 const extra=exits.length?Math.max(0,needed-(cut-bottom)):0;
 for(const n of prefix)n.x=cx-n.w/2;
 for(const n of rest)n.y+=extra;
 for(const e of L.edges){
  if(seen.has(e.source)&&seen.has(e.target)){
   const a=byId.get(e.source),b=byId.get(e.target);
   e.points=[[cx,a.y+a.h],[cx,b.y-3]];
  }else if(!seen.has(e.source))e.points=e.points.map(([x,y])=>[x,y+extra]);
 }
 const maxDistance=Math.max(1,...suffixes.map(s=>Math.abs(s.x-cx)));
 const scale=Math.min(1,Math.max(1,last.w/2-20)/maxDistance);
 for(const s of suffixes){
  const side=s.x<cx-.01?left:s.x>cx+.01?right:[];
  const lane=Math.max(0,side.indexOf(s.x)),y=bottom+12+lane*8,port=cx+(s.x-cx)*scale;
  s.edge.points=simplify([[port,bottom],[port,y],[s.x,y],...s.points.map(([x,py])=>[x,py+extra])]);
 }
 L.height+=extra;
 L.root_presentation={version:VERSION,root_id:rootId,mode:'opening-chain',moved_node_ids:prefix.map(n=>n.id),added_height:extra};
 return L;
}
module.exports={centerRoot,VERSION};
