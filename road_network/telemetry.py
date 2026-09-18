"""World truth is separate from the optimizer's acknowledged incident overlay."""
import math
from .incidents import IncidentError


class Traffic:
    def __init__(self):
        self.events = {}

    def inject(self, payload, network, incidents):
        sid = payload['session_id']
        incidents.state(sid, network)
        eid = payload['edge_id']
        speed = payload['expected_speed']
        if eid not in network['edges'] or type(speed) not in (int,float) or not math.isfinite(speed) or speed <= 0:
            raise IncidentError('Invalid hidden traffic configuration')
        if sid in self.events:
            raise IncidentError('This demo session already has a traffic event')
        self.events[sid] = {'lifecycle':'ACTIVE_UNDETECTED','edge_id':eid,'expected_speed':speed,'samples':{},'counts':{}}
        return {'lifecycle':'ACTIVE_UNDETECTED','physical_overrides':{eid:{'available':True,'travel_time_factor':3.0}}}

    def sample(self, payload, network, incidents):
        sid = payload['session_id']
        known = incidents.state(sid, network)
        event = self.events.get(sid)
        if event is None:
            raise IncidentError('No injected event')
        evidence = []
        if event['lifecycle'] == 'ACTIVE_UNDETECTED':
            for sample in payload.get('samples', []):
                vid, eid, fraction, timestamp = (sample[k] for k in ('vehicle_id','edge_id','fraction','time_ms'))
                if type(vid) is not int or vid < 1 or any(type(v) not in (int,float) or not math.isfinite(v) for v in (fraction,timestamp)) or not 0 <= fraction <= 1:
                    raise IncidentError('Invalid telemetry sample')
                previous = event['samples'].get(vid)
                if previous and timestamp <= previous['time_ms']:
                    continue
                event['samples'][vid] = sample
                abnormal = False
                if previous and eid == previous['edge_id'] == event['edge_id']:
                    dt = timestamp-previous['time_ms']
                    travelled = (fraction-previous['fraction'])*network['edges'][eid]['distance']
                    ratio = travelled/dt/event['expected_speed']
                    abnormal = 450 <= dt <= 750 and 0 <= ratio <= .5
                    evidence.append({'vehicle_id':vid,'observed_ratio':ratio,'interval_ms':dt})
                event['counts'][vid] = event['counts'].get(vid,0)+1 if abnormal else 0
                if event['counts'][vid] >= 2:
                    known = incidents.report({'session_id':sid,'type':'congestion','edge_id':event['edge_id'],'vehicle_id':vid},network)
                    event['lifecycle']='DETECTED'
                    event['detected_vehicle']=vid
                    break
        return {'lifecycle':event['lifecycle'],'known_state':known,'evidence':evidence,
                'detected_vehicle':event.get('detected_vehicle')}

    def transition(self, sid, phase):
        event=self.events.get(sid)
        if event:
            allowed={'DETECTED':'REOPTIMIZING','REOPTIMIZING':'ROUTES_UPDATED'}
            if allowed.get(event['lifecycle']) != phase:
                raise IncidentError('Invalid traffic lifecycle transition')
            event['lifecycle']=phase
