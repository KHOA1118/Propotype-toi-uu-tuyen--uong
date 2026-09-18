"""Session-local prototype incident state. Raw maps and LNS inputs are untouched."""
from uuid import uuid4
from datetime import datetime, timezone
from copy import deepcopy


POLICIES = {
    'congestion': {'travel_time_factor': 3, 'available': True},
    'accident': {'travel_time_factor': 6, 'available': True},
    'road_blockage': {'travel_time_factor': None, 'available': False},
}


class IncidentError(ValueError):
    pass


class IncidentStore:
    def __init__(self):
        self.sessions = {}

    def create(self, payload, network):
        if not isinstance(payload, dict) or payload.get('source_sha256') != network['metadata']['source']['sha256']:
            raise IncidentError('Map version mismatch; reload the page')
        sid = str(uuid4())
        self.sessions[sid] = {'session_id': sid, 'source_sha256': payload['source_sha256'], 'revision': 0,
                              'incidents': [], 'edge_overrides': {}}
        return deepcopy(self.sessions[sid])

    def state(self, sid, network):
        if not isinstance(sid, str) or sid not in self.sessions:
            raise IncidentError('Unknown simulation session; reload the page')
        session = self.sessions[sid]
        if session['source_sha256'] != network['metadata']['source']['sha256']:
            raise IncidentError('Map version changed; reload the page')
        return deepcopy(session)

    def report(self, payload, network):
        if not isinstance(payload, dict):
            raise IncidentError('Expected incident object')
        state = self.state(payload.get('session_id'), network)
        kind, edge_id = payload.get('type'), payload.get('edge_id')
        if not isinstance(kind, str) or kind not in POLICIES:
            raise IncidentError('Unsupported incident type')
        if not isinstance(edge_id, str) or edge_id not in network['edges']:
            raise IncidentError('Unknown directed OSM edge')
        vehicle_id = payload.get('vehicle_id')
        if vehicle_id is not None and (type(vehicle_id) is not int or not 1 <= vehicle_id <= 1000):
            raise IncidentError('Invalid reporting vehicle ID')
        edge = network['edges'][edge_id]
        policy = POLICIES[kind]
        record = {'id': str(uuid4()), 'type': kind, 'edge_id': edge_id, 'vehicle_id': vehicle_id,
                  'status': 'active', 'reported_at': datetime.now(timezone.utc).isoformat(), **policy}
        state['incidents'].append(record)
        previous = state['edge_overrides'].get(edge_id)
        available = policy['available'] and (previous is None or previous['available'])
        factor = max(policy['travel_time_factor'] or 1, (previous or {}).get('travel_time_factor') or 1) if available else None
        baseline = edge.get('travel_time')
        state['edge_overrides'][edge_id] = {'edge_id': edge_id, 'from_node': edge['from_node'], 'to_node': edge['to_node'],
            'status': 'slowed' if available else 'blocked', 'available': available, 'travel_time_factor': factor,
            'base_travel_time': baseline, 'travel_time': baseline * factor if available and baseline is not None else None,
            'distance': edge['distance']}
        state['revision'] += 1
        self.sessions[state['session_id']] = state
        return deepcopy(state)
