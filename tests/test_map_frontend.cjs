// Run against a running server: node --test tests/test_map_frontend.cjs
const {test, before} = require('node:test');
const assert = require('node:assert/strict');
const http = require('node:http');
const map = require('../frontend/map-data.js');
const {Simulation} = require('../frontend/simulation.js');
const base = process.env.LNS_TEST_URL || 'http://127.0.0.1:8004';
let network, scenario;
before(async () => {
  const response = await fetch(base + '/api/network');
  assert.equal(response.status, 200);
  network = await response.json();
  const scenarioResponse = await fetch(base + '/api/demo-scenario');
  assert.equal(scenarioResponse.status, 200);
  scenario = await scenarioResponse.json();
});
test('real source and road geometry have valid references', () => {
  assert.equal(network.metadata.source.sha256, 'a8f1c6a74e6fb1eb0d952a3d34d6794ec6d630283be21a699824cf1597eb89fa');
  const project = map.displayProjection(network);
  for (const way of Object.values(network.ways)) for (const id of way.node_ids) {
    assert.ok(network.nodes[id]);
    const [x, y] = project(network.nodes[id]);
    assert.ok(Number.isFinite(x) && Number.isFinite(y));
    assert.ok(x >= 44 && x <= 756 && y >= 49 && y <= 481);
  }
});
test('presentation demo binds 24 unique OSM customers with six capacity-constrained vehicles', () => {
  assert.equal(scenario.stops.length, 25);
  assert.equal(scenario.vehicle_count, 6);
  assert.equal(scenario.vehicle_capacity, 40);
  assert.equal(new Set(scenario.stops.map(s => s.osm_node_id)).size, 25);
  const request = map.toRequest(network, scenario);
  assert.equal(request.instance.nodes.length, 25);
  for (const stop of scenario.stops) assert.ok(network.nodes[stop.osm_node_id]);
  assert.deepEqual(scenario.design.customer_groups.map(group => group.length), [8, 8, 8]);
});
test('projection uses meters and preserves demand/time fields', () => {
  const project = map.projection(network), origin = Object.values(network.nodes)[0];
  assert.ok(Math.abs(project({...origin, lat: origin.lat + 0.001})[1] - project(origin)[1] - 111.1949266) < 0.001);
  const request = map.toRequest(network, scenario);
  scenario.stops.forEach((s, i) => {
    for (const key of ['id', 'demand', 'ready_time', 'due_date', 'service_time']) assert.equal(request.instance.nodes[i][key], s[key]);
  });
});
test('invalid geographic bindings and duplicate IDs fail without fallback', () => {
  for (const alter of [s => s.stops[1].osm_node_id = 'missing', s => s.stops[1].id = 0,
    s => s.stops[1].osm_node_id = s.stops[0].osm_node_id, s => s.stops[0].id = 50]) {
    const bad = structuredClone(scenario); alter(bad); assert.throws(() => map.toRequest(network, bad));
  }
});
test('live network → mapped request → real LNS → geographic result', async () => {
  const request = map.toRequest(network, scenario);
  const response = await fetch(base + '/api/optimize', {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(request)});
  assert.equal(response.status, 200);
  const result = await response.json(), nodes = map.bindResult(network, scenario, result);
  assert.equal(result.feasible, true);
  assert.equal(result.routes.length, 6);
  assert.deepEqual(result.routes.map(route => route.filter(id => id !== 0).length).sort(), [4,4,4,4,4,4]);
  assert.deepEqual(result.routes.flat().filter(id => id !== 0).sort((a,b) => a-b), Array.from({length: 24}, (_, i) => i + 1));
  let distance = 0;
  for (const route of result.routes) {
    assert.equal(route[0], 0); assert.equal(route.at(-1), 0);
    for (let i = 1; i < route.length; i++) {
      const a = nodes.find(n => n.id === route[i-1]), b = nodes.find(n => n.id === route[i]);
      distance += Math.hypot(a.x - b.x, a.y - b.y);
    }
  }
  assert.ok(Math.abs(distance - result.objective[1]) < 1e-6);
  for (const n of nodes) assert.equal(n.lat, network.nodes[n.osm_node_id].lat);
  const bad = structuredClone(result); bad.dataset.nodes[1].x += 1;
  assert.throws(() => map.bindResult(network, scenario, bad));
});
test('frontend assets served by backend', async () => {
  for (const path of ['/', '/app.js', '/map-data.js', '/simulation.js', '/style.css']) {
    const status = await new Promise((resolve, reject) => http.get(base + path, response => {
      response.resume(); response.once('end', () => resolve(response.statusCode));
    }).once('error', reject));
    assert.equal(status, 200);
  }
});
test('real incident API updates session and running simulation without changing geometry',async()=>{
  async function post(path,body) {
    const response=await fetch(base+path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    assert.equal(response.status,200); return response.json();
  }
  const result=await post('/api/optimize',map.toRequest(network,scenario));
  const geometry=await post('/api/network/routes',{stops:scenario.stops,routes:result.routes});
  const original=JSON.stringify(geometry.routes);
  const session=await post('/api/simulation',{source_sha256:network.metadata.source.sha256});
  const simulation=new Simulation(geometry.routes,network); simulation.start(); simulation.advance(1);
  const vehicle=simulation.snapshot()[0];
  const updated=await post('/api/incidents',{session_id:session.session_id,type:'road_blockage',edge_id:vehicle.edgeId,vehicle_id:1});
  simulation.setIncidentState(updated); simulation.advance(10000);
  assert.equal(simulation.snapshot()[0].status,'blocked');
  assert.deepEqual(simulation.snapshot()[0].position,vehicle.position);
  const stored=await(await fetch(base+'/api/simulation?session_id='+session.session_id)).json();
  assert.deepEqual(stored,updated);
  assert.equal(JSON.stringify(geometry.routes),original);
  assert.notEqual(network.edges[vehicle.edgeId].status,'blocked');
});

test('live geometry follows directed existing edges for every stop and rejects disconnected old demo', async () => {
  const result = await (await fetch(base + '/api/optimize', {method: 'POST', body: JSON.stringify(map.toRequest(network, scenario))})).json();
  const response = await fetch(base + '/api/network/routes', {method: 'POST', body: JSON.stringify({stops: scenario.stops, routes: result.routes, initial_routes: result.initial_routes})});
  assert.equal(response.status, 200);
  const geometry = await response.json();
  assert.equal(geometry.weight, 'distance');
  assert.equal(geometry.snapped_stops.length, 25);
  assert.equal(geometry.source_sha256, network.metadata.source.sha256);
  const simulation = new Simulation(geometry.routes, network);
  const unchanged = JSON.stringify(geometry.routes);
  simulation.start();
  for (let tick = 0; tick < 1800; tick++) {
    simulation.advance(100);
    for (const v of simulation.snapshot()) {
      if (!v.edgeId) continue;
      assert.equal(v.edgeId, geometry.routes[v.routeIndex].edge_ids[v.segment]);
      const edge = network.edges[v.edgeId], a = network.nodes[edge.from_node], b = network.nodes[edge.to_node];
      assert.ok(v.position.lat >= Math.min(a.lat,b.lat)-1e-10 && v.position.lat <= Math.max(a.lat,b.lat)+1e-10);
      assert.ok(v.position.lon >= Math.min(a.lon,b.lon)-1e-10 && v.position.lon <= Math.max(a.lon,b.lon)+1e-10);
    }
  }
  simulation.advance(1);
  assert.equal(simulation.status,'completed');
  assert.equal(simulation.snapshot().length,6);
  assert.equal(JSON.stringify(geometry.routes),unchanged);
  for (const key of ['routes', 'initial_routes']) for (let i = 0; i < result[key].length; i++) {
    const route = geometry[key][i];
    assert.deepEqual(route.stop_sequence, result[key][i]);
    assert.equal(route.node_ids.length, route.edge_ids.length + 1);
    assert.ok(route.node_ids.length > route.stop_sequence.length);
    route.edge_ids.forEach((eid, j) => {
      const edge = network.edges[eid];
      assert.equal(edge.from_node, route.node_ids[j]); assert.equal(edge.to_node, route.node_ids[j+1]);
    });
    route.coordinates.forEach((xy, j) => {const n = network.nodes[route.node_ids[j]]; assert.deepEqual(xy, [n.lon, n.lat]);});
    route.legs.forEach(leg => {
      assert.equal(leg.node_ids[0], geometry.snapped_stops.find(s => s.id === leg.from_stop).nearest_osm_node_id);
      assert.equal(leg.node_ids.at(-1), geometry.snapped_stops.find(s => s.id === leg.to_stop).nearest_osm_node_id);
    });
  }
  assert.ok(geometry.overlap.shared_node_count > 1);
  assert.ok(geometry.overlap.shared_edge_count > 0);
  assert.ok(geometry.overlap.incident_hotspot);
  assert.ok(geometry.overlap.incident_hotspot.routes_affected >= 2);
  assert.ok(geometry.overlap.incident_hotspot.vehicles_affected.length >= 2);
  const old = map.demoScenario(network);
  const bad = await fetch(base + '/api/network/routes', {method: 'POST', body: JSON.stringify({stops: old.stops, routes: [[0,1,0]]})});
  assert.equal(bad.status, 422);
  assert.match((await bad.json()).error, /no directed path/);
});
