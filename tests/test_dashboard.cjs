const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Dashboard,costs}=require('../frontend/dashboard.js');
const network={edges:{a:{distance:100,travel_time:10},b:{distance:200,travel_time:null},c:{distance:120,travel_time:12}}};
const incident={edge_overrides:{b:{available:false}}};
const sim={elapsed:1000,clocks:[5,0],plans:[{events:[{edgeId:'a',start:0,end:10}]},{events:[]}],snapshot:()=>[{status:'paused',served:[1]},{status:'completed',served:[2]}]};
const snapshots=[{cutoff:10,suffix_edge_ids:['b'],remaining:[3]},{cutoff:0,suffix_edge_ids:[],remaining:[]}];
test('fractional progress, blocked baselines, unchanged updates and live counts',()=>{
  const d=new Dashboard();d.begin(sim,snapshots,network,incident);
  assert.equal(d.before.distance,250);assert.equal(d.before.travel,null);assert.equal(d.affected,1);
  d.applied({updates:[{route_index:0,geometry:{edge_ids:['c']},order:[3]}],failures:[],elapsed_seconds:.2},1100);
  assert.deepEqual(d.after,{distance:170,travel:17});assert.equal(d.rerouted,1);
  assert.deepEqual(d.live(sim,3),{active:1,remaining:1});
  d.begin(sim,snapshots,network,{edge_overrides:{b:{available:true,travel_time_factor:3}}});
  d.applied({updates:[{route_index:0,geometry:{edge_ids:['b']},order:[3]}],failures:[],elapsed_seconds:.1},1200);
  assert.equal(d.rerouted,0);assert.deepEqual(d.before,d.after);
});
test('partial failure is not fleet feasibility; reset and bounded ordered timeline',()=>{
  const d=new Dashboard();d.event('Nghiệm ban đầu');d.moving(100);d.moving(200);d.incident(sim);d.begin(sim,snapshots,network,incident);
  d.applied({updates:[],failures:[{route_index:0,error:'blocked'}],elapsed_seconds:1},2000);
  assert.equal(d.feasibility,'Chưa bảo đảm toàn đội');assert.equal(d.after.travel,null);
  assert.equal(d.events.filter(e=>e.label==='Xe di chuyển').length,1);
  d.failed(2200);assert.equal(d.after,null);
  for(let i=0;i<10;i++)d.event('retry',3000+i);assert.equal(d.events.length,8);
  d.reset();assert.equal(d.scope,null);assert.equal(d.events.length,0);assert.equal(d.before,null);
});
test('static distance is OSM and travel estimate uses the declared speed',()=>{
  assert.deepEqual(costs([{id:'b'}],network,null),{distance:200,travel:24});
  const d=new Dashboard();d.initial({initial_routes:[{edge_ids:['a','b']}],routes:[{edge_ids:['c']}]},{feasible:true,total_seconds:.5},network,null);
  assert.equal(d.before.distance,300);assert.equal(d.after.distance,120);assert.equal(d.runtime,.5);
});
