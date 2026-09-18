(function(root){
  'use strict';
  function costs(parts, network, incidents) {
    let distance=0, travel=0, available=true;
    for(const {id,fraction=1} of parts) {
      const edge=network.edges[id], effect=incidents?.edge_overrides[id];
      distance+=edge.distance*fraction;
      if(effect?.available===false) available=false;
      travel+=(edge.travel_time>0 ? edge.travel_time : edge.distance/(30/3.6))*fraction*(effect?.travel_time_factor||1);
    }
    return {distance,travel:available ? travel : null};
  }
  const parts=ids=>ids.map(id=>({id,fraction:1}));
  class Dashboard {
    constructor(){this.reset();}
    reset(){this.before=null;this.after=null;this.affected=0;this.rerouted=0;this.runtime=null;this.feasibility='Chưa có nghiệm';this.events=[];this.capture=null;this.scope=null;}
    event(label,elapsed=0){this.events.push({label,seconds:elapsed/1000});this.events=this.events.slice(-8);}
    initial(geometry,result,network,incidents){
      this.reset();
      this.before=costs(parts(geometry.initial_routes.flatMap(r=>r.edge_ids)),network,incidents);
      this.after=costs(parts(geometry.routes.flatMap(r=>r.edge_ids)),network,incidents);
      this.scope='Toàn bộ tuyến ban đầu · khoảng cách đường OSM';
      this.runtime=result.total_seconds;
      this.feasibility=result.feasible ? (this.after.travel===null ? 'Có đường bị chặn' : 'Nghiệm ban đầu hợp lệ') : 'Không hợp lệ';
      this.event('Nghiệm ban đầu');
    }
    moving(elapsed){if(!this.events.some(e=>e.label==='Xe di chuyển'))this.event('Xe di chuyển',elapsed);}
    incident(sim){
      this.rerouted=0;
      this.affected=sim.plans.filter((p,i)=>p.events.some(e=>e.edgeId && e.end>sim.clocks[i] && sim.incidentState?.edge_overrides[e.edgeId])).length;
      this.feasibility='Cần kiểm tra sau sự cố';this.event('Đã ghi nhận sự cố',sim.elapsed);
    }
    begin(sim, snapshots, network, incidents){
      this.capture=snapshots.map((s,i)=>{
        const prefix=sim.plans[i].events.filter(e=>e.edgeId && e.end>sim.clocks[i] && e.end<=s.cutoff)
          .map(e=>({id:e.edgeId,fraction:(e.end-Math.max(e.start,sim.clocks[i]))/(e.end-e.start||1)}));
        // Unaffected vehicles may advance during the solve; this comparison stays frozen.
        return {prefix,suffix:parts(s.suffix_edge_ids),remaining:[...s.remaining]};
      });
      this.network=network;this.incidents=structuredClone(incidents);
      this.before=costs(this.capture.flatMap(v=>[...v.prefix,...v.suffix]),network,incidents);
      this.after=null;this.rerouted=0;this.runtime=null;
      this.affected=this.capture.filter(v=>[...v.prefix,...v.suffix].some(e=>incidents.edge_overrides[e.id])).length;
      this.scope='Tổng phần đường còn lại của đội xe tại lúc yêu cầu · cùng chi phí sự cố';
      this.feasibility='Đang kiểm tra';this.event('Bắt đầu tái tối ưu',sim.elapsed);
    }
    applied(result,elapsed){
      const updates=new Map(result.updates.map(u=>[u.route_index,u]));
      this.after=costs(this.capture.flatMap((v,i)=>[...v.prefix,...(updates.has(i)?parts(updates.get(i).geometry.edge_ids):v.suffix)]),this.network,this.incidents);
      this.rerouted=result.updates.filter(u=>{
        const old=this.capture[u.route_index];
        return JSON.stringify(old.suffix.map(e=>e.id))!==JSON.stringify(u.geometry.edge_ids)||JSON.stringify(old.remaining)!==JSON.stringify(u.order);
      }).length;
      this.runtime=result.elapsed_seconds;
      this.feasibility=result.failures.length ? 'Chưa bảo đảm toàn đội' : this.after.travel===null ? 'Có đường bị chặn' : result.updates.length ? 'Phần tái tối ưu hợp lệ' : 'Không có tuyến cần đổi';
      this.event(result.updates.length ? 'Đã áp dụng nghiệm mới' : 'Giữ phương án hiện tại',elapsed);
    }
    failed(elapsed){this.after=null;this.feasibility='Chưa áp dụng · cần kiểm tra';this.event('Tái tối ưu chưa áp dụng',elapsed);}
    live(sim,total){const vehicles=sim?.snapshot()||[];return {active:vehicles.filter(v=>v.status!=='completed').length,remaining:Math.max(0,total-new Set(vehicles.flatMap(v=>v.served)).size)};}
  }
  if(typeof module!=='undefined')module.exports={Dashboard,costs};else root.DecisionDashboard={Dashboard,costs};
})(globalThis);
