// Geometry regression checks for branching, return edges, and replay.
const assert=require('node:assert/strict');
const {centerRoot}=require('./root_layout.cjs');
const nodes=[{id:'root',x:100,y:0,w:100,h:40},{id:'intro',x:100,y:90,w:100,h:40},
 {id:'left',x:0,y:180,w:100,h:40},{id:'right',x:300,y:180,w:100,h:40},
 {id:'end',x:300,y:300,w:100,h:40}];
const edge=(id,source,target,points)=>({id,source,target,points,kind:'attempt',transition_ids:[id]});
const layout={width:500,height:340,nodes,edges:[edge('a','root','intro',[[150,40],[150,87]]),
 edge('b','intro','left',[[120,130],[120,155],[50,155],[50,177]]),
 edge('c','intro','right',[[180,130],[180,155],[350,155],[350,177]]),
 edge('d','right','end',[[350,220],[350,297]])]};
const before=JSON.stringify(layout),out=centerRoot(layout,'root');
assert.equal(JSON.stringify(layout),before,'Do not mutate a saved input layout');
assert.equal(out.nodes[0].x+50,250);assert.equal(out.nodes[1].x+50,250);
assert.equal(out.width,layout.width,'A normal DAG must not gain horizontal padding');
assert.deepEqual(out.edges.map(({points,...e})=>e),layout.edges.map(({points,...e})=>e));
assert.deepEqual(out.nodes.map(({x,y,...n})=>n),layout.nodes.map(({x,y,...n})=>n));
for(const e of out.edges){
 for(let i=1;i<e.points.length;i++){
  const [x,y]=e.points[i-1],[xx,yy]=e.points[i];
  assert.ok(x===xx||y===yy,'All segments stay orthogonal');
  for(const n of out.nodes){
   if([e.source,e.target].includes(n.id))continue;
   const hit=x===xx?x>n.x&&x<n.x+n.w&&Math.max(y,yy)>n.y&&Math.min(y,yy)<n.y+n.h:
    y>n.y&&y<n.y+n.h&&Math.max(x,xx)>n.x&&Math.min(x,xx)<n.x+n.w;
   assert.ok(!hit,'New root routing must not cross another node');
  }
 }
}
assert.deepEqual(centerRoot(out,'root'),out,'Saved layouts replay without drift');
const cyclic=JSON.parse(before);cyclic.edges.push(edge('return','end','root',[[400,320],[480,320],[480,20],[200,20]]));
const preserved=centerRoot(cyclic,'root'),dx=preserved.nodes[0].x-cyclic.nodes[0].x;
assert.equal(preserved.root_presentation.mode,'symmetric-padding');
assert.equal(preserved.nodes[0].x+50,preserved.width/2);
assert.deepEqual(preserved.edges.map(e=>e.points.map(([x,y])=>[x-dx,y])),cyclic.edges.map(e=>e.points),'Cycles keep their complete paths');
assert.throws(()=>centerRoot(layout,'missing'),/absent/);
console.log('Root presentation: branching, metadata preservation, nonmutation, replay and cycle checks passed.');
