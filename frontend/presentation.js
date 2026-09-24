(function(root){
  class Presentation {
    constructor(fixture){this.fixture=fixture;this.phase='loading';this.active=true;this.lifecycle='INACTIVE';this.nextSample=fixture.event.inject_at_ms+fixture.event.sample_interval_ms;this.sampleQueue=[];this.sending=false;}
    budget(elapsed,ms){
      if(['loading','preview'].includes(this.phase))return 0;
      const limit=this.lifecycle==='INACTIVE'?this.fixture.event.inject_at_ms:this.lifecycle==='ACTIVE_UNDETECTED'?this.nextSample:Infinity;
      return Math.max(0,Math.min(ms,limit-elapsed));
    }
    samples(sim){return sim.snapshot().map(v=>({vehicle_id:v.vehicleId,edge_id:v.edgeId,fraction:v.edgeFraction??0,time_ms:sim.elapsed}));}
    summary(d){const a=d.before?.travel,b=d.after?.travel;if(a==null||b==null)return 'Không thể so sánh thời gian khi tuyến bị chặn';const gain=a-b;return `${d.rerouted} xe đổi tuyến - ${gain>0?'Giảm':gain<0?'Tăng':'Không đổi'} ${Math.abs(gain).toFixed(1)} giây thời gian chạy dự kiến`;}
  }
  if(typeof module!=='undefined')module.exports={Presentation};else root.DemoPresentation={Presentation};
})(globalThis);