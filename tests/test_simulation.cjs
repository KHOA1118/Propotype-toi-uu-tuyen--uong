const {test} = require('node:test');
const assert = require('node:assert/strict');
const {Simulation} = require('../frontend/simulation.js');
const network = {nodes: {a:{lat:10,lon:106}, b:{lat:10,lon:106.001}, c:{lat:10.001,lon:106.001}}, edges:{
  ab:{from_node:'a',to_node:'b',distance:100}, ba:{from_node:'b',to_node:'a',distance:100},
  bc:{from_node:'b',to_node:'c',distance:100}, ca:{from_node:'c',to_node:'a',distance:100}}};
const routes = [
  {node_ids:['a','b','a'],edge_ids:['ab','ba'],legs:[{to_stop:1,edge_ids:['ab']},{to_stop:0,edge_ids:['ba']}]},
  {node_ids:['a','b','c','a'],edge_ids:['ab','bc','ca'],legs:[{to_stop:2,edge_ids:['ab','bc']},{to_stop:0,edge_ids:['ca']}]}];
const make = () => new Simulation(routes,network,{durationMs:3100,dwellMs:100});
test('one vehicle per route; ordered edge interpolation and service stop',()=>{
  const s=make(); assert.equal(s.snapshot().length,2); s.start(); s.advance(500);
  assert.equal(s.snapshot()[0].edgeId,'ab'); assert.equal(s.snapshot()[0].position.lon,106.0005);
  s.advance(500); assert.equal(s.snapshot()[0].status,'servicing');
  assert.equal(s.snapshot()[1].edgeId,'bc'); assert.equal(s.snapshot()[1].segment,1);
  s.advance(100); assert.equal(s.snapshot()[0].edgeId,'ba');
});
test('pause/resume/reset and repeated start do not change immutable routes',()=>{
  const before=JSON.stringify(routes), s=make(); s.start(); s.advance(450); s.start(); s.pause();
  const paused=s.snapshot(); s.advance(99999); assert.deepEqual(s.snapshot(),paused);
  s.resume(); s.advance(50); assert.equal(s.elapsed,500);
  s.reset(); assert.equal(s.status,'ready'); assert.equal(s.elapsed,0);
  assert.ok(s.snapshot().every(v=>v.position.lat===10 && v.position.lon===106));
  s.start(); s.advance(500); assert.equal(s.snapshot()[0].position.lon,106.0005);
  assert.equal(JSON.stringify(routes),before);
});
test('frame-independent result and individual depot completion',()=>{
  const a=make(),b=make(); a.start(); b.start(); a.advance(2100);
  for(let i=0;i<21;i++) b.advance(100);
  assert.deepEqual(a.snapshot(),b.snapshot()); assert.equal(a.snapshot()[0].status,'completed');
  assert.equal(a.snapshot()[1].status,'moving'); a.advance(100000);
  assert.equal(a.status,'completed'); assert.ok(a.snapshot().every(v=>v.stopId===0 && v.position.lon===106));
});
test('reject disconnected paths and invalid times',()=>{
  const bad=structuredClone(routes); bad[0].node_ids[1]='c';
  assert.throws(()=>new Simulation(bad,network)); assert.throws(()=>make().advance(NaN));
  assert.throws(()=>make().advance(-1));
});
test('zero-length route and zero-length edges complete without NaN',()=>{
  const s=new Simulation([{node_ids:['a'],edge_ids:[],legs:[{to_stop:1,edge_ids:[]},{to_stop:0,edge_ids:[]}]}],network,{durationMs:100,dwellMs:0});
  s.start(); s.advance(0); assert.equal(s.status,'completed'); assert.equal(s.snapshot()[0].position.lon,106);
});
test('incident slows remaining travel only, keeps geometry and unaffected vehicle moving',()=>{
  const s=make(); s.start(); s.advance(1200);
  const position=s.snapshot()[0].position;
  s.setIncidentState({incidents:[{type:'congestion'}],edge_overrides:{ba:{available:true,travel_time_factor:3}}});
  assert.deepEqual(s.snapshot()[0].position,position);
  s.advance(300);
  assert.ok(Math.abs(s.snapshot()[0].position.lon-106.0008)<1e-10);
  assert.ok(Math.abs(s.snapshot()[1].position.lat-10.0005)<1e-10);
  assert.equal(s.snapshot()[0].status,'slowed');
});
test('blockage stops before entry and midway, reset retains incident',()=>{
  const s=make(); s.setIncidentState({incidents:[],edge_overrides:{bc:{available:false,travel_time_factor:null}}});
  s.start(); s.advance(10000);
  assert.equal(s.snapshot()[1].status,'blocked'); assert.deepEqual(s.snapshot()[1].position,network.nodes.b);
  assert.equal(s.snapshot()[0].status,'completed'); assert.equal(s.status,'running');
  s.pause(); const paused=s.snapshot(); s.advance(100); assert.deepEqual(s.snapshot(),paused);
  s.reset(); s.start(); s.advance(10000); assert.equal(s.snapshot()[1].status,'blocked');
  const mid=make(); mid.start(); mid.advance(500); const p=mid.snapshot()[0].position;
  mid.setIncidentState({incidents:[],edge_overrides:{ab:{available:false}}}); mid.advance(10000);
  assert.deepEqual(mid.snapshot()[0].position,p);
});
test('incident traversal is independent of frame size',()=>{
  const a=make(),b=make();
  for(const s of [a,b]) {s.setIncidentState({incidents:[],edge_overrides:{ab:{available:true,travel_time_factor:6}}});s.start();}
  a.advance(7500); for(let i=0;i<75;i++)b.advance(100);
  for(let i=0;i<2;i++) {
    assert.ok(Math.abs(a.snapshot()[i].position.lat-b.snapshot()[i].position.lat)<1e-10);
    assert.ok(Math.abs(a.snapshot()[i].position.lon-b.snapshot()[i].position.lon)<1e-10);
  }
});
