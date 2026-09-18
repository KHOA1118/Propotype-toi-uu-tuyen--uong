const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Simulation}=require('../frontend/simulation.js');
const {Dashboard,costs}=require('../frontend/dashboard.js');
const MapData=require('../frontend/map-data.js');
const base=process.env.LNS_TEST_URL || 'http://127.0.0.1:8008';
async function get(path) {const r=await fetch(base+path); assert.ok(r.ok); return r.json();}
async function post(path,body) {const r=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}); const data=await r.json(); assert.ok(r.ok,JSON.stringify(data)); if(r.status===202){for(;;){await new Promise(r=>setTimeout(r,100));const j=await get(`/api/jobs/${data.job_id}`);if(j.status==='completed')return j.result;if(j.status==='failed')throw Error(j.error);}}return data;}

test('real OSM moving fleet -> incident -> real LNS -> continuous completion, repeat and reset',async()=>{
  const network=await get('/api/network'), scenario=await get('/api/demo-scenario');
  const optimized=await post('/api/optimize',MapData.toRequest(network,scenario));
  const original=JSON.stringify(optimized);
  const geometry=await post('/api/network/routes',{stops:scenario.stops,routes:optimized.routes});
  const sim=new Simulation(geometry.routes,network,{stops:scenario.stops});
  let incidents=await post('/api/simulation',{source_sha256:network.metadata.source.sha256});
  sim.setIncidentState(incidents); sim.start(); sim.advance(30000);
  const dashboard=new Dashboard();
  dashboard.initial({...geometry,initial_routes:geometry.routes},optimized,network,incidents); dashboard.moving(0);
  assert.equal(dashboard.live(sim,24).active,6);
  const servedBefore=sim.plans.map((p,i)=>p.events.filter(e=>e.status==='servicing'&&e.end<=sim.clocks[i]).map(e=>e.stopId));
  assert.ok(servedBefore.some(ids=>ids.length>0),'at least one delivery already served');
  let totalCalls=0;
  for (const type of ['accident','road_blockage']) {
    const preview=sim.beginReoptimization(scenario);
    const target=preview.find(v=>v.remaining.length>0 && v.suffix_edge_ids.length);
    assert.ok(target,'remaining work');
    const redundant = id => {
      const banned=new Set([id,...Object.keys(incidents.edge_overrides).filter(e=>incidents.edge_overrides[e].available===false)]);
      const adj=new Map();
      for(const [eid,e] of Object.entries(network.edges)) {
        const tags=network.ways[e.way_id].tags;
        if(banned.has(eid)||['access','vehicle','motor_vehicle','hgv'].some(k=>['no','private'].includes(tags[k]))||!['motorway','motorway_link','trunk','trunk_link','primary','primary_link','secondary','secondary_link','tertiary','tertiary_link','residential','unclassified','service','living_street'].includes(tags.highway)) continue;
        if(!adj.has(e.from_node)) adj.set(e.from_node,[]); adj.get(e.from_node).push(e.to_node);
      }
      const seen=new Set([network.edges[id].from_node]), stack=[...seen];
      while(stack.length) for(const n of adj.get(stack.pop())||[]) if(!seen.has(n)){seen.add(n);stack.push(n);}
      return seen.has(network.edges[id].to_node);
    };
    const edge=target.suffix_edge_ids.find(e=>!preview.some(v=>v.committed_edge_ids.includes(e)) && (type!=='road_blockage'||redundant(e)));
    assert.ok(edge,'a future edge with a legal detour');
    sim.cancelReoptimization();
    incidents=await post('/api/incidents',{session_id:incidents.session_id,type,edge_id:edge}); sim.setIncidentState(incidents);
    const vehicles=sim.beginReoptimization(scenario);
    dashboard.incident(sim); dashboard.begin(sim,vehicles,network,incidents);
    const expectedBefore=costs(dashboard.capture.flatMap(v=>[...v.prefix,...v.suffix]),network,incidents);
    assert.deepEqual(dashboard.before,expectedBefore);
    const pending=post('/api/reoptimize',{session_id:incidents.session_id,revision:incidents.revision,scenario,vehicles});
    const start=sim.snapshot(); sim.advance(250);
    assert.ok(sim.snapshot().some((v,i)=>JSON.stringify(v.position)!==JSON.stringify(start[i].position)),'movement during solve');
    const result=await pending;
    assert.ok(result.updates.length,JSON.stringify(result.failures));
    const before=sim.snapshot(), untouched=sim.plans.map(p=>JSON.stringify(p));
    sim.applyReoptimization(result);
    dashboard.applied(result,sim.elapsed);
    assert.equal(dashboard.runtime,result.elapsed_seconds);
    assert.ok(dashboard.affected>=dashboard.rerouted);
    assert.ok(dashboard.after.distance>0);
    assert.equal(dashboard.events.at(-1).label,'Đã áp dụng nghiệm mới');
    assert.deepEqual(sim.snapshot().map(v=>v.position),before.map(v=>v.position),'no teleport');
    for(const u of result.updates) {
      const v=vehicles[u.route_index];
      assert.deepEqual([...u.order].sort(),[...v.remaining].sort());
      assert.ok(!u.order.some(id=>v.served.includes(id)||id===v.anchor));
      if(u.solver) {totalCalls++; assert.equal(u.solver.engine,'original-lns'); assert.equal(u.solver.feasible,true); assert.ok(Math.abs(u.solver.objective[1]-u.metrics.after)<1e-6);}
      for(const id of u.geometry.edge_ids) assert.notEqual(incidents.edge_overrides[id]?.available,false);
    }
    for(let i=0;i<sim.plans.length;i++) if(!result.updates.some(u=>u.route_index===i)) assert.equal(JSON.stringify(sim.plans[i]),untouched[i]);
    sim.pause(); const paused=sim.snapshot(); sim.advance(5000); assert.deepEqual(sim.snapshot(),paused); sim.resume();
  }
  assert.ok(totalCalls>0);
  for(let t=0;t<1000000 && sim.status!=='completed';t+=100) sim.advance(100);
  assert.equal(sim.status,'completed');
  assert.deepEqual(dashboard.live(sim,24),{active:0,remaining:0});
  assert.ok(sim.snapshot().every(v=>v.stopId===0));
  for(const p of sim.plans) {const served=p.events.filter(e=>e.status==='servicing').map(e=>e.stopId); assert.equal(new Set(served).size,served.length);}
  assert.equal(JSON.stringify(optimized),original,'static optimization immutable');
  sim.reset(); assert.equal(sim.status,'ready'); assert.ok(sim.modelClocks.every(t=>t===0));
  console.log(JSON.stringify({vehicles:sim.plans.length,realLnsCalls:totalCalls,servedBefore},null,2));
});

test('pending horizon, stale results, delivery wait and cancellation',()=>{
  const network={nodes:{a:{lat:0,lon:0},b:{lat:0,lon:1}},edges:{ab:{from_node:'a',to_node:'b',distance:100},ba:{from_node:'b',to_node:'a',distance:100}}};
  const route={stop_sequence:[0,1,0],node_ids:['a','b','a'],edge_ids:['ab','ba'],legs:[{from_stop:0,to_stop:1,edge_ids:['ab']},{from_stop:1,to_stop:0,edge_ids:['ba']}]};
  const sim=new Simulation([route],network,{durationMs:3100,dwellMs:100,stops:[{id:1,ready_time:50,service_time:2}]});
  sim.setIncidentState({revision:1,edge_overrides:{}}); sim.start(); sim.advance(1500);
  assert.equal(sim.snapshot()[0].status,'servicing'); assert.ok(sim.modelClocks[0]<50);
  sim.beginReoptimization({});
  assert.throws(()=>sim.applyReoptimization({revision:0,updates:[]}),/Stale/);
  sim.advance(10001); assert.throws(()=>sim.applyReoptimization({revision:1,updates:[]}),/exceeded/);
  sim.cancelReoptimization(); sim.reset(); assert.equal(sim.pending,null);
});
