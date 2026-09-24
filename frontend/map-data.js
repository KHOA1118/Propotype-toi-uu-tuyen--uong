(function (root) {
  'use strict';
  function projection(network) {
    const b = network.metadata.network_bounds;
    const lat = (b.minlat + b.maxlat) / 2, lon = (b.minlon + b.maxlon) / 2;
    const rad = Math.PI / 180, radius = 6371000;
    return n => [(n.lon - lon) * rad * radius * Math.cos(lat * rad), (n.lat - lat) * rad * radius];
  }
  function displayProjection(network) {
    const project = projection(network), b = network.metadata.network_bounds;
    const lo = project({lat: b.minlat, lon: b.minlon}), hi = project({lat: b.maxlat, lon: b.maxlon});
    const scale = Math.min(710 / (hi[0] - lo[0]), 430 / (hi[1] - lo[1]));
    return n => { const [x, y] = project(n); return [400 + x * scale, 265 - y * scale]; };
  }
  function demoScenario(network, profile) {
    const ids = new Set();
    const allowed = new Set(['primary', 'secondary', 'tertiary', 'residential', 'unclassified', 'service']);
    for (const way of Object.values(network.ways)) {
      if (!way.edge_exclusion_reason && allowed.has(way.tags.highway) &&
          !['no', 'private'].includes(way.tags.access) && way.tags.motor_vehicle !== 'no' && way.tags.hgv !== 'no') {
        way.node_ids.forEach(id => ids.add(id));
      }
    }
    const project = projection(network);
    const reachable = profile ? new Set(profile.demo_node_ids) : ids;
    const candidates = [...ids].filter(id => reachable.has(id)).sort().map(id => ({id, p: project(network.nodes[id])}));
    if (candidates.length < 11) throw new Error('Cần ít nhất 11 điểm đường thật cho kịch bản demo');
    const sq = (a, b) => (a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2;
    const selected = [candidates.reduce((a, b) => sq(a.p, [0, 0]) <= sq(b.p, [0, 0]) ? a : b)];
    while (selected.length < 11) {
      let best = null, score = -1;
      for (const c of candidates) {
        const distance = Math.min(...selected.map(s => sq(c.p, s.p)));
        if (!selected.includes(c) && distance > score) { best = c; score = distance; }
      }
      selected.push(best);
    }
    return {vehicle_count: 3, vehicle_capacity: 40, options: {iterations: 30, seed: 42, removal_count: 3},
      stops: selected.map((n, id) => ({id, osm_node_id: n.id, lat: network.nodes[n.id].lat, lon: network.nodes[n.id].lon, demand: id ? 10 : 0, ready_time: 0, due_date: 100000, service_time: id ? 1 : 0}))};
  }
  function toRequest(network, scenario) {
    if (!Array.isArray(scenario.stops) || scenario.stops.length < 2) throw new Error('Thiếu danh sách điểm giao');
    const project = projection(network), ids = new Set(), osmIds = new Set();
    const nodes = scenario.stops.map(s => {
      if (!Number.isInteger(s.id) || s.id < 0 || s.id > 2147483647 || ids.has(s.id)) throw new Error('ID điểm giao không hợp lệ hoặc trùng');
      const referenced = network.nodes[s.osm_node_id];
      const n = {lat: s.lat ?? referenced?.lat, lon: s.lon ?? referenced?.lon};
      if (s.osm_node_id !== undefined && (typeof s.osm_node_id !== 'string' || !referenced || osmIds.has(s.osm_node_id))) throw new Error('không tồn tại hoặc trùng');
      if (!Number.isFinite(n.lat) || !Number.isFinite(n.lon) || Math.abs(n.lat) > 90 || Math.abs(n.lon) > 180) throw new Error('Tọa độ không hợp lệ');
      ids.add(s.id); if (s.osm_node_id !== undefined) osmIds.add(s.osm_node_id);
      const [x, y] = project(n);
      return {id: s.id, x, y, demand: s.demand, ready_time: s.ready_time, due_date: s.due_date, service_time: s.service_time};
    });
    if (!ids.has(0)) throw new Error('Thiếu depot ID 0');
    return {instance: {name: 'HCM-real-map-demo-stops', vehicle_count: scenario.vehicle_count,
      vehicle_capacity: scenario.vehicle_capacity, travel_speed: 1, nodes}, options: scenario.options};
  }
  function bindResult(network, scenario, result) {
    const expected = toRequest(network, scenario).instance.nodes;
    const received = result.dataset.nodes;
    if (received.length !== expected.length) throw new Error('Backend trả về sai danh sách điểm');
    const seen = new Set();
    return received.map(n => {
      const original = expected.find(s => s.id === n.id), stop = scenario.stops.find(s => s.id === n.id);
      if (!original || seen.has(n.id) || Object.keys(original).some(k => n[k] !== original[k])) throw new Error('Dữ liệu điểm từ backend không khớp bản đồ');
      seen.add(n.id);
      return {...n, lat: stop.lat ?? network.nodes[stop.osm_node_id]?.lat, lon: stop.lon ?? network.nodes[stop.osm_node_id]?.lon, id: n.id, osm_node_id: stop.osm_node_id};
    });
  }
  const api = {projection, displayProjection, demoScenario, toRequest, bindResult};
  if (typeof module !== 'undefined') module.exports = api;
  else root.MapData = api;
})(globalThis);
