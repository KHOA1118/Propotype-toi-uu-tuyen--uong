const fs=require('node:fs');
const assert=require('node:assert/strict');
const {Simulation}=require('../frontend/simulation.js');
const {Presentation}=require('../frontend/presentation.js');

async function validateScenario(fixture,{base=process.env.LNS_TEST_URL||'http://127.0.0.1:8013',frame=50,solveAdvanceMs=500}={}){
 const api=async(path,body)=>{const r=await fetch(base+path,body?{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)}:{});const d=await r.json();assert.ok(r.ok,JSON.stringify(d));return d;};
 const finishJob=async job=>{for(let n=0;n<300;n++){const j=await api('/api/jobs/'+job.job_id);if(j.status==='completed')return j.result;if(j.status==='failed')throw Error(j.error);await new Promise(r=>setTimeout(r,100));}throw Error('Job timeout');};
 const network=await api('/api/network');
 const initial=await finishJob(await api('/api/jobs/initial',{scenario:fixture.scenario}));
 assert.equal(initial.feasible,true);assert.equal(initial.routes.length,6);assert.ok(initial.overlap_analysis.accepted);
 const customers=initial.routes.flatMap(r=>r.filter(id=>id>0));assert.equal(customers.length,24);assert.equal(new Set(customers).size,24);
 assert.equal(fixture.scenario.vehicle_count,6);assert.equal(fixture.scenario.vehicle_capacity,40);
 assert.ok(fixture.scenario.stops.every(s=>s.demand===(s.id?10:0)));
 assert.ok(initial.routes.every(r=>r.length===6));
 const sim=new Simulation(initial.road_geometry.routes,network,{durationMs:fixture.duration_ms,stops:fixture.scenario.stops});
 const session=await api('/api/simulation',{source_sha256:fixture.source_sha256});sim.setIncidentState(session);
 const run=new Presentation(fixture);run.phase='moving';sim.start();
 const completion={};const record=()=>{for(const v of sim.snapshot())if(v.status==='completed'&&completion[v.vehicleId]===undefined)completion[v.vehicleId]=sim.elapsed;};
 const advance=ms=>{sim.advance(ms);record();};
 while(sim.elapsed<fixture.event.inject_at_ms)advance(run.budget(sim.elapsed,frame));
 const original=JSON.stringify(sim.routes),lifecycle=['INACTIVE'];
 const injected=await api('/api/traffic/inject',{session_id:session.session_id,edge_id:fixture.event.edge_id,expected_speed:sim.metersPerMs});
 run.lifecycle=injected.lifecycle;lifecycle.push(run.lifecycle);sim.setPhysicalState(injected.physical_overrides);
 let detected;
 for(let n=0;n<500;n++){
  while(sim.elapsed<run.nextSample&&sim.status!=='completed')advance(run.budget(sim.elapsed,frame));
  if(sim.status==='completed')break;
  const measured=await api('/api/traffic/telemetry',{session_id:session.session_id,samples:run.samples(sim)});run.nextSample+=fixture.event.sample_interval_ms;
  assert.equal(JSON.stringify(sim.routes),original);
  if(measured.lifecycle==='DETECTED'){detected=measured;break;}
  assert.equal(measured.known_state.revision,0);assert.deepEqual(measured.known_state.edge_overrides,{});
 }
 if(!detected)return {accepted:false,reason:'No detection'};
 lifecycle.push(detected.lifecycle);
 const detectionMs=sim.elapsed,v2=sim.snapshot().find(v=>v.vehicleId===2);
 sim.setIncidentState(detected.known_state);
 // Production waits 700ms to show detection. Solver latency is an explicit
 // deterministic validation parameter; no runtime simulation code is changed.
 for(let t=0;t<700;t+=frame)advance(Math.min(frame,700-t));
 const snapshots=sim.beginReoptimization(fixture.scenario);
 const queued=await api('/api/reoptimize',{session_id:session.session_id,revision:detected.known_state.revision,scenario:fixture.scenario,vehicles:snapshots});
 lifecycle.push((await api('/api/traffic/telemetry',{session_id:session.session_id,samples:[]})).lifecycle);
 const result=await finishJob(queued);assert.equal(result.failures.length,0);assert.ok(result.completed_lns_solves>0);
 for(let t=0;t<solveAdvanceMs;t+=frame)advance(Math.min(frame,solveAdvanceMs-t));
 const positions=sim.snapshot().map(v=>v.position);sim.applyReoptimization(result);assert.deepEqual(sim.snapshot().map(v=>v.position),positions);
 lifecycle.push((await api('/api/traffic/applied',{session_id:session.session_id,job_id:queued.job_id})).lifecycle);
 while(sim.elapsed<600000&&sim.status!=='completed')advance(frame);
 assert.equal(sim.status,'completed');assert.equal(sim.snapshot().reduce((n,v)=>n+v.served.length,0),24);
 assert.deepEqual(lifecycle,['INACTIVE','ACTIVE_UNDETECTED','DETECTED','REOPTIMIZING','ROUTES_UPDATED']);
 const report={frame_ms:frame,solver_advance_ms:solveAdvanceMs,detection_ms:detectionMs,detected_vehicle:detected.detected_vehicle,
 vehicle_2_active_at_detection:v2.status!=='completed'&&v2.progress<1,vehicle_2_progress_at_detection:v2.progress,
 vehicle_completion_ms:completion,vehicle_2_finishes_after_vehicle_5:completion[2]>completion[5],
 customer_counts:initial.routes.map(r=>r.length-2),incident_edge_id:fixture.event.edge_id,
 vehicle_5_uses_hotspot:initial.road_geometry.routes[4].edge_ids.includes(fixture.event.edge_id),
 lifecycle,completed_lns_solves:result.completed_lns_solves};
 report.accepted=report.vehicle_5_uses_hotspot&&report.detected_vehicle===5&&report.vehicle_2_active_at_detection&&completion[2]>completion[5]+2000;
 return report;
}
module.exports={validateScenario};
if(require.main===module){validateScenario(JSON.parse(fs.readFileSync(process.argv[2],'utf8'))).then(r=>console.log(JSON.stringify(r))).catch(e=>{console.error(e);process.exitCode=1;});}
