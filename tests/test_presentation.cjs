const {test}=require('node:test');
const assert=require('node:assert/strict');
const {Presentation}=require('../frontend/presentation.js');
const {Simulation}=require('../frontend/simulation.js');
const {Dashboard}=require('../frontend/dashboard.js');
const base=process.env.LNS_TEST_URL||'http://127.0.0.1:8011';
async function api(path,body){const r=await fetch(base+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();assert.ok(r.ok,JSON.stringify(d));return d;}
async function completed(job,advance){for(let n=0;n<300;n++){const j=await api('/api/jobs/'+job.job_id);if(j.status==='completed')return j.result;if(j.status==='failed')throw Error(j.error);if(advance)advance();await new Promise(r=>setTimeout(r,100));}throw Error('Job timeout');}
test('three real road-cost LNS demos: hidden physics, two telemetry intervals, async solve, preserved progress, depot return',async()=>{
 const fixture=await api('/api/presentation-scenario'),network=await api('/api/network'),runs=[];
 for(const frame of [17,50,100]){
  const initial=await completed(await api('/api/jobs/initial',{scenario:fixture.scenario}));
  assert.equal(initial.feasible,true);assert.equal(initial.routes.length,6);assert.equal(initial.cost_unit,'seconds');assert.ok(initial.overlap_analysis.accepted);
  const geometry=initial.road_geometry, scenario=fixture.scenario;
  assert.equal(scenario.vehicle_count,6);assert.equal(scenario.vehicle_capacity,40);
  assert.equal(scenario.stops.length,25);assert.ok(scenario.stops.every(s=>s.demand===(s.id?10:0)));
  assert.ok(initial.routes.every(r=>r.length===6));
  assert.equal(new Set(initial.routes.flatMap(r=>r.filter(id=>id>0))).size,24);
  assert.ok(geometry.routes[4].edge_ids.includes(fixture.event.edge_id));
  const sim=new Simulation(geometry.routes,network,{durationMs:fixture.duration_ms,stops:scenario.stops});
  const session=await api('/api/simulation',{source_sha256:fixture.source_sha256});sim.setIncidentState(session);
  const dashboard=new Dashboard();dashboard.initial({...geometry,initial_routes:geometry.routes},initial,network,session);
  const run=new Presentation(fixture);run.phase='moving';sim.start();
  const completionTimes={};
  const advance=ms=>{sim.advance(ms);for(const v of sim.snapshot())if(v.status==='completed'&&completionTimes[v.vehicleId]===undefined)completionTimes[v.vehicleId]=sim.elapsed;};
  while(sim.elapsed<fixture.event.inject_at_ms)advance(run.budget(sim.elapsed,frame));
  const original=JSON.stringify(sim.routes);
  const injected=await api('/api/traffic/inject',{session_id:session.session_id,edge_id:fixture.event.edge_id,expected_speed:sim.metersPerMs});
  run.lifecycle=injected.lifecycle;sim.setPhysicalState(injected.physical_overrides);
  assert.equal((await api('/api/simulation?session_id='+session.session_id)).revision,0);
  const premature=await fetch(base+'/api/reoptimize',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({session_id:session.session_id,revision:0})});assert.equal(premature.status,422);
  assert.match((await premature.json()).error,/not been detected/);
  let detected,evidence=[];
  for(let n=0;n<500;n++){
   while(sim.elapsed<run.nextSample)advance(run.budget(sim.elapsed,frame));
   const measured=await api('/api/traffic/telemetry',{session_id:session.session_id,samples:run.samples(sim)});run.nextSample+=500;
   evidence.push(...measured.evidence);
   assert.equal(JSON.stringify(sim.routes),original);
   if(measured.lifecycle==='DETECTED'){detected=measured;break;}
   assert.equal(measured.known_state.revision,0);assert.deepEqual(measured.known_state.edge_overrides,{});
  }
  assert.ok(detected,'vehicle reaches hidden incident');
  assert.equal(detected.detected_vehicle,5);
  const vehicle2=sim.snapshot().find(v=>v.vehicleId===2);
  assert.notEqual(vehicle2.status,'completed');assert.ok(vehicle2.progress<1);
  const detectionMs=sim.elapsed;
  assert.ok(evidence.filter(e=>e.observed_ratio<=.5).length>=2);
  assert.ok(Math.abs(evidence.at(-1).observed_ratio-1/3)<1e-6);
  sim.setIncidentState(detected.known_state);dashboard.incident(sim);
  advance(700); // existing UI detection presentation delay
  const snapshots=sim.beginReoptimization(scenario);dashboard.begin(sim,snapshots,network,detected.known_state);
  assert.ok(snapshots.some(s=>s.served.length));
  const queued=await api('/api/reoptimize',{session_id:session.session_id,revision:detected.known_state.revision,scenario,vehicles:snapshots});
  assert.ok(queued.job_id);assert.equal((await api('/api/traffic/telemetry',{session_id:session.session_id,samples:[]})).lifecycle,'REOPTIMIZING');
  const result=await completed(queued,()=>advance(100));
  assert.equal(result.failures.length,0);assert.ok(result.completed_lns_solves>0);
  const positions=sim.snapshot().map(v=>v.position);sim.applyReoptimization(result);dashboard.applied(result,sim.elapsed);
  assert.deepEqual(sim.snapshot().map(v=>v.position),positions);
  assert.equal((await api('/api/traffic/applied',{session_id:session.session_id,job_id:queued.job_id})).lifecycle,'ROUTES_UPDATED');
  assert.ok(dashboard.rerouted>0);assert.ok(dashboard.before.travel>dashboard.after.travel);
  for(let t=0;t<600000&&sim.status!=='completed';t+=100)advance(100);
  assert.ok(completionTimes[2]>completionTimes[5],JSON.stringify(completionTimes));
  assert.equal(sim.status,'completed');assert.deepEqual(dashboard.live(sim,24),{active:0,remaining:0});
  const report={frame,detectionMs,detectedVehicle:detected.detected_vehicle,completionTimes,affected:dashboard.affected,rerouted:dashboard.rerouted,initialSeconds:initial.initial_pipeline_seconds,geometrySeconds:initial.geometry_seconds,reoptSeconds:result.elapsed_seconds,workerPid:result.worker_pid,summary:run.summary(dashboard)};runs.push(report);console.log(JSON.stringify(report));
 }
 assert.equal(runs.length,3);
});
test('presentation summary never invents savings',()=>{const p=new Presentation({event:{inject_at_ms:5000,sample_interval_ms:500}});assert.equal(p.budget(0,100),0);assert.match(p.summary({before:{travel:10},after:{travel:20},rerouted:1}),/Tăng/);assert.match(p.summary({before:{travel:null},after:{travel:20}}),/Không thể/);assert.match(p.summary({before:{travel:20},after:{travel:20},rerouted:0}),/Không đổi/);});

test('scenario timing evidence uses real Simulation across frame sizes and solver delays',async()=>{
 const {validateScenario}=require('../tools/validate_presentation.cjs');
 const fixture=await api('/api/presentation-scenario');
 const evidence=require('../data/scenario_validation.json');
 for(const [frame,solveAdvanceMs] of [[17,0],[50,500],[100,2500]]){
  const report=await validateScenario(fixture,{base,frame,solveAdvanceMs});
  assert.equal(report.accepted,true,JSON.stringify(report));
  if(frame===50){
   assert.equal(report.detection_ms,evidence.detection_ms);
   assert.deepEqual(report.vehicle_completion_ms,evidence.vehicle_completion_ms);
   assert.equal(report.detected_vehicle,evidence.detected_vehicle);
  }
 }
});
