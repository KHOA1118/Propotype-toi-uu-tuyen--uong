(function(root) {
  'use strict';
  class Simulation {
    constructor(routes, network, {durationMs = 180000, dwellMs = 1000, metersPerMs = null, stops = []} = {}) {
      if (!routes.length || !Number.isFinite(durationMs) || durationMs <= 0 || !Number.isFinite(dwellMs) || dwellMs < 0) throw new Error('Invalid simulation configuration');
      const lengths = routes.map(r => r.edge_ids.reduce((sum, id) => {
        const e = network.edges[id];
        if (!e || !Number.isFinite(e.distance) || e.distance < 0) throw new Error('Invalid simulation edge');
        return sum + e.distance;
      }, 0));
      const movingTime = durationMs - Math.max(...routes.map(r => r.legs.filter(l => l.to_stop !== 0).length)) * dwellMs;
      if (movingTime <= 0) throw new Error('Simulation duration must exceed service time');
      this.metersPerMs = metersPerMs || Math.max(...lengths) / movingTime || 1;
      this.network = network; this.routes = structuredClone(routes); this.dwellMs = dwellMs;
      this.stops = stops;
      this.plans = routes.map((r, routeIndex) => {
        let time = 0, segment = 0, cursor = r.node_ids[0];
        const events = [];
        const point = id => {
          const n = network.nodes[id];
          if (!n || !Number.isFinite(n.lat) || !Number.isFinite(n.lon)) throw new Error('Invalid simulation node');
          return {lat: n.lat, lon: n.lon};
        };
        const start = point(cursor);
        for (const [legIndex, leg] of r.legs.entries()) {
          for (const id of leg.edge_ids) {
            const edge = network.edges[id];
            if (!edge || edge.from_node !== cursor || r.edge_ids[segment] !== id || r.node_ids[segment + 1] !== edge.to_node) throw new Error('Discontinuous simulation geometry');
            const end = time + edge.distance / this.metersPerMs;
            events.push({start: time, end, modelSeconds: edge.travel_time > 0 ? edge.travel_time : edge.distance / (30 / 3.6), from: point(cursor), to: point(edge.to_node), edgeId: id, segment, legIndex, stopId: leg.to_stop, status: 'moving'});
            cursor = edge.to_node; segment++; time = end;
          }
          if (leg.to_stop > 0) {
            const stop = stops.find(s=>s.id===leg.to_stop);
            events.push({start: time, end: time + dwellMs, modelSeconds: stop?.service_time ?? 1, readyTime:stop?.ready_time ?? 0, from: point(cursor), to: point(cursor), edgeId: null, segment, legIndex, stopId: leg.to_stop, status: 'servicing'});
            time += dwellMs;
          }
        }
        if (segment !== r.edge_ids.length || r.node_ids.length !== segment + 1 || cursor !== r.node_ids[0]) throw new Error('Simulation route must return to depot');
        return {routeIndex, start, finish: point(cursor), events, duration: time, segments: segment};
      });
      this.duration = Math.max(...this.plans.map(p => p.duration));
      this.reset();
    }
    reset() { this.elapsed = 0; this.status = 'ready'; this.clocks = this.plans.map(() => 0); this.modelClocks = this.plans.map(() => 0); this.pending = null; }
    beginReoptimization(scenario) {
      if (this.pending) throw new Error('Optimization already pending');
      // Only the currently traversed directed edge (or active service) is committed.
      const snapshots = this.plans.map((p, i) => {
        const clock=this.clocks[i], route=this.routes[i];
        const served=p.events.filter(e=>e.status==='servicing' && e.end<=clock).map(e=>e.stopId);
        const current=this.status==='ready' ? null : p.events.find(e=>e.end>clock);
        let cutoff=clock, anchor=0, prefixLegs=[], suffixLegs=route.legs;
        let anchorNode=route.node_ids[0];
        if (current?.edgeId) {
          const entered=clock>current.start;
          const edgeEnd=current.segment+(entered ? 1 : 0);
          cutoff=entered ? current.end : clock; anchor=-1; anchorNode=route.node_ids[edgeEnd];
          prefixLegs=structuredClone(route.legs.slice(0,current.legIndex));
          const prefixEdges=prefixLegs.flatMap(l=>l.edge_ids).length;
          const partial=route.edge_ids.slice(prefixEdges,edgeEnd);
          if(partial.length) prefixLegs.push({from_stop:route.legs[current.legIndex].from_stop,to_stop:-1,edge_ids:partial});
          suffixLegs=[{...route.legs[current.legIndex],from_stop:-1,edge_ids:route.legs[current.legIndex].edge_ids.slice(edgeEnd-prefixEdges)},...route.legs.slice(current.legIndex+1)];
        } else if(current) {
          cutoff=current.end; anchor=current.stopId; anchorNode=route.node_ids[current.segment];
          prefixLegs=structuredClone(route.legs.slice(0,current.legIndex+1)); suffixLegs=route.legs.slice(current.legIndex+1);
        } else if(this.status!=='ready') { prefixLegs=structuredClone(route.legs); suffixLegs=[]; }
        const committed=p.events.filter(e=>e.end>clock && e.end<=cutoff);
        const travel=committed.reduce((sum,e)=>sum+e.modelSeconds*(e.end-Math.max(clock,e.start))/(e.end-e.start||1)*(this.incidentState?.edge_overrides[e.edgeId]?.travel_time_factor||1),0);
        const suffix_edge_ids=suffixLegs.flatMap(l=>l.edge_ids);
        const affected=suffix_edge_ids.some(e=>this.incidentState?.edge_overrides[e]);
        return {route_index:i,assigned:route.stop_sequence.filter(id=>id>0),served,anchor,anchor_osm_node_id:anchorNode,
          remaining:suffixLegs.map(l=>l.to_stop).filter(id=>id>0),
          committed_edge_ids:committed.filter(e=>e.edgeId).map(e=>e.edgeId),suffix_edge_ids,cutoff,prefixLegs,affected,
          ready_time:Math.max(this.modelClocks[i]+travel,(this.stops.find(s=>s.id===anchor)?.ready_time??0)+(this.stops.find(s=>s.id===anchor)?.service_time??0))+10*this.modelScale()};
      });
      this.pending = {snapshots, waitMs:0};
      return snapshots;
    }
    modelScale() { return Math.max(1, ...this.plans.flatMap(p=>p.events.map(e=>e.modelSeconds / ((e.end-e.start)/1000 || 1)))); }
    cancelReoptimization() { this.pending = null; }
    applyReoptimization(result) {
      if (!this.pending || result.revision !== this.incidentState?.revision) throw new Error('Stale optimization response');
      if (this.pending.waitMs > 10000) throw new Error('Solve exceeded reserved time; retry required');
      const candidates = result.updates.map(update => {
        const i = update.route_index, s = this.pending.snapshots[i], old = this.routes[i];
        if (!s || s.anchor !== update.anchor || JSON.stringify([...s.remaining].sort()) !== JSON.stringify([...update.order].sort())) throw new Error('Invalid replacement ownership');
        const legs = [...s.prefixLegs, ...update.geometry.legs];
        const edge_ids = legs.flatMap(l=>l.edge_ids), node_ids = [old.node_ids[0], ...edge_ids.map(e=>this.network.edges[e].to_node)];
        const geometry = {...old, legs, edge_ids, node_ids, stop_sequence:[0,...legs.map(l=>l.to_stop)],
          distance_m:edge_ids.reduce((sum,id)=>sum+this.network.edges[id].distance,0),
          coordinates:node_ids.map(n=>[this.network.nodes[n].lon,this.network.nodes[n].lat])};
        const replacement = new Simulation([geometry],this.network,{dwellMs:this.dwellMs,metersPerMs:this.metersPerMs,durationMs:180000,stops:this.stops});
        const plan = replacement.plans[0]; plan.routeIndex=i;
        return {i,geometry,plan};
      });
      for (const {i,geometry,plan} of candidates) { this.routes[i]=geometry; this.plans[i]=plan; }
      this.duration=Math.max(...this.plans.map(p=>p.duration)); this.pending=null;
      return this.routes;
    }
    setIncidentState(state) {
      // Backend acknowledgement is the sole source of applied edge effects.
      this.incidentState = JSON.parse(JSON.stringify(state));
    }
    start() { if (this.status === 'ready') this.status = 'running'; }
    setPhysicalState(overrides) { this.physicalOverrides=structuredClone(overrides); }
    pause() { if (this.status === 'running') this.status = 'paused'; }
    resume() { if (this.status === 'paused') this.status = 'running'; }
    advance(ms) {
      if (!Number.isFinite(ms) || ms < 0) throw new Error('Invalid simulation time');
      if (this.status !== 'running') return;
      if (this.pending) this.pending.waitMs += ms;
      let consumed = 0;
      this.plans.forEach((p, i) => {
        let remaining = ms, clock = this.clocks[i];
        for (const e of p.events) {
          if (e.end <= clock) continue;
          if (this.pending?.snapshots[i].affected && clock >= this.pending.snapshots[i].cutoff) {
            this.modelClocks[i] += remaining / 1000 * this.modelScale(); remaining=0; break;
          }
          if (e.readyTime > this.modelClocks[i]) {
            const wait = Math.min(remaining, (e.readyTime-this.modelClocks[i])*1000/this.modelScale());
            this.modelClocks[i] += wait/1000*this.modelScale(); remaining-=wait;
            if (!remaining) break;
          }
          const effect = e.edgeId ? (this.physicalOverrides?.[e.edgeId] || this.incidentState?.edge_overrides[e.edgeId]) : null;
          if (effect?.available === false) { remaining = 0; break; }
          const factor = effect?.travel_time_factor || 1;
          const needed = (e.end - clock) * factor;
          if (remaining < needed) { this.modelClocks[i] += e.modelSeconds * remaining / (e.end-e.start || 1); clock += remaining / factor; remaining = 0; break; }
          this.modelClocks[i] += e.modelSeconds * needed / (e.end-e.start || 1);
          remaining -= needed; clock = e.end;
        }
        this.clocks[i] = clock;
        consumed = Math.max(consumed, ms - remaining);
      });
      this.elapsed += consumed;
      if (this.plans.every((p,i) => this.clocks[i] >= p.duration)) this.status = 'completed';
    }
    snapshot() {
      return this.plans.map((p, i) => {
        const clock = this.clocks[i];
        const base = {vehicleId: p.routeIndex + 1, routeIndex: p.routeIndex, segmentCount: p.segments,
          served: p.events.filter(e=>e.status==='servicing' && e.end<=clock).map(e=>e.stopId)};
        if (clock >= p.duration) return {...base, position: {...p.finish}, segment: p.segments, edgeId: null, status: 'completed', stopId: 0, progress: 1};
        if (this.status === 'ready') return {...base, position: {...p.start}, segment: 0, edgeId: null, status: 'ready', stopId: 0, progress: 0};
        const e = p.events.find(e => e.end > clock);
        const effect = e.edgeId ? this.incidentState?.edge_overrides[e.edgeId] : null;
        const fraction = e.end === e.start ? 1 : (clock - e.start) / (e.end - e.start);
        return {...base, position: {lat: e.from.lat + (e.to.lat - e.from.lat) * fraction, lon: e.from.lon + (e.to.lon - e.from.lon) * fraction},
          segment: e.segment, edgeId: e.edgeId, edgeFraction:fraction, stopId: e.stopId,
          status: effect?.available === false ? 'blocked' : effect?.travel_time_factor > 1 ? 'slowed' : e.status, progress: clock / p.duration};
      });
    }
  }
  if (typeof module !== 'undefined') module.exports = {Simulation};
  else root.VehicleSimulation = {Simulation};
})(globalThis);
