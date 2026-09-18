"""Incident-aware remaining-work adapter. The authoritative LNS is untouched.

Dynamic objective: travel seconds (passed in the legacy distance_matrix slot).
Virtual depot outgoing costs originate at the next safe road node; incoming costs
terminate at the real depot. Customer ownership never changes.
"""
import math
from time import perf_counter
from lns.adapter import solve_instance, validate_request, ConstructionError
from road_network.routing import RoadRouter, RoutingError
from road_network.costs import context


def reoptimize(payload, network, incident_state):
    started = perf_counter()
    if payload.get('revision') != incident_state['revision']:
        raise RoutingError('Stale incident revision; request a new optimization')
    scenario = payload['scenario']
    stops = {s['id']: s for s in scenario['stops']}
    if len(stops) != len(scenario['stops']):
        raise RoutingError('Duplicate stop IDs')
    nodes = [dict(id=s['id'], x=s['lon'], y=s['lat'], demand=s['demand'],
                  ready_time=s['ready_time'], due_date=s['due_date'], service_time=s['service_time'])
             for s in scenario['stops']]
    validate_request({'instance': {'nodes': nodes, 'vehicle_count': scenario['vehicle_count'],
                                  'vehicle_capacity': scenario['vehicle_capacity']}})
    base = context(network)[1]
    snaps = {s['id']: s['nearest_osm_node_id'] for s in base.snap(scenario['stops'])}
    edges = {}
    for eid, edge in network['edges'].items():
        effect = incident_state['edge_overrides'].get(eid, {})
        time = edge.get('travel_time')
        if not isinstance(time, (int, float)) or not math.isfinite(time) or time <= 0:
            time = edge['distance'] / (30 / 3.6)
        edges[eid] = dict(edge, travel_time=time * (effect.get('travel_time_factor') or 1),
                          status='blocked' if effect.get('available') is False else edge['status'])
    router = RoadRouter(dict(network, edges=edges))
    router.weight = 'travel_time'
    trees = {}

    def path(a, b):
        if a not in router.adj or b not in router.adj:
            raise RoutingError('Disconnected road anchor; no fallback')
        if a not in trees:
            trees[a] = router.tree(a)
        costs, previous = trees[a]
        if b not in costs:
            raise RoutingError(f'No directed road path from {a} to {b}')
        ids, cursor = [], b
        while cursor != a:
            eid = previous[cursor]
            ids.append(eid)
            cursor = edges[eid]['from_node']
        return costs[b], list(reversed(ids))

    vehicles = payload['vehicles']
    if not isinstance(vehicles, list) or len(vehicles) > scenario['vehicle_count']:
        raise RoutingError('Invalid vehicle snapshots')
    owners, indexes = set(), set()
    for v in vehicles:
        assigned = v['assigned']
        if (type(v['route_index']) is not int or v['route_index'] < 0 or
                v['route_index'] >= scenario['vehicle_count'] or v['route_index'] in indexes or
                len(set(assigned)) != len(assigned) or owners.intersection(assigned) or
                not set(assigned) <= set(stops) - {0}):
            raise RoutingError('Invalid vehicle ownership')
        indexes.add(v['route_index']); owners.update(assigned)
        served, remaining = v['served'], v['remaining']
        committed = [] if v['anchor'] in (0, -1) else [v['anchor']]
        if v['anchor'] == -1 and v.get('anchor_osm_node_id') not in base.adj:
            raise RoutingError('Invalid current road node')
        if v['anchor'] != -1 and v['anchor'] not in stops:
            raise RoutingError('Invalid anchor stop')
        partition = served + committed + remaining
        if len(set(partition)) != len(partition) or set(partition) != set(assigned):
            raise RoutingError('Served, committed and remaining customers must partition ownership')
        if type(v['ready_time']) not in (int, float) or not math.isfinite(v['ready_time']) or v['ready_time'] < 0:
            raise RoutingError('Invalid vehicle clock')
    if owners != set(stops) - {0}:
        raise RoutingError('Snapshots must cover the whole fleet')
    updates, failures = [], []
    for v in vehicles:
        try:
            anchor, remaining = v['anchor'], v['remaining']
            if sum(stops[s]['demand'] for s in v['assigned']) > scenario['vehicle_capacity']:
                raise RoutingError('Original vehicle assignment exceeds capacity')
            anchor_node = v.get('anchor_osm_node_id', snaps.get(anchor))
            if anchor != -1 and anchor_node != snaps[anchor]:
                raise RoutingError('Anchor does not match original snapped stop')
            def location(sid):
                return anchor_node if sid == -1 else snaps[sid]
            old_edges = v['suffix_edge_ids']
            cursor = anchor_node
            for eid in old_edges:
                if eid not in base.edges or base.edges[eid]['from_node'] != cursor:
                    raise RoutingError('Invalid remaining route geometry')
                cursor = base.edges[eid]['to_node']
            if cursor != snaps[0]:
                raise RoutingError('Remaining route must return to depot')
            if any(incident_state['edge_overrides'].get(eid, {}).get('available') is False
                   for eid in v.get('committed_edge_ids', [])):
                raise RoutingError('Current directed edge is blocked; vehicle held in place')
            if not any(eid in incident_state['edge_overrides'] for eid in old_edges):
                continue
            if anchor > 0 and v['ready_time'] - stops[anchor]['service_time'] > stops[anchor]['due_date']:
                raise RoutingError('Committed customer time window cannot be guaranteed')
            ids = [0] + remaining
            matrix = [[0 if i == j else path(anchor_node if i == 0 else snaps[a], snaps[b])[0]
                       for j, b in enumerate(ids)] for i, a in enumerate(ids)]
            order, result = [], None
            if remaining:
                depot = dict(nodes[next(i for i,n in enumerate(nodes) if n['id'] == 0)], ready_time=v['ready_time'])
                instance = {'nodes': [depot] + [n for sid in remaining for n in nodes if n['id'] == sid],
                            'vehicle_count': 1, 'vehicle_capacity': scenario['vehicle_capacity'],
                            'distance_matrix': matrix, 'travel_time_matrix': matrix}
                try:
                    result = solve_instance(instance, scenario.get('options'), [[0] + remaining + [0]])
                except ConstructionError:
                    result = solve_instance(instance, scenario.get('options'))
                if not result['feasible'] or len(result['routes']) != 1:
                    raise RoutingError('LNS did not return a feasible single-vehicle solution')
                order = result['routes'][0][1:-1]
                if sorted(order) != sorted(remaining):
                    raise RoutingError('LNS coverage mismatch')
            sequence = [anchor] + order + [0]
            leg_list, edge_ids, node_ids, total = [], [], [anchor_node], 0
            for a, b in zip(sequence, sequence[1:]):
                cost, leg_edges = path(location(a), location(b))
                leg_nodes = [location(a)] + [edges[e]['to_node'] for e in leg_edges]
                leg_list.append(dict(from_stop=a, to_stop=b, edge_ids=leg_edges, node_ids=leg_nodes))
                total += cost; edge_ids.extend(leg_edges); node_ids.extend(leg_nodes[1:])
            if not remaining and v['ready_time'] + total > stops[0]['due_date']:
                raise RoutingError('Depot return deadline violated')
            old_blocked = any(edges[e]['status'] == 'blocked' for e in old_edges)
            updates.append({'route_index': v['route_index'], 'anchor': anchor, 'order': order,
                'geometry': dict(stop_sequence=sequence, legs=leg_list, edge_ids=edge_ids, node_ids=node_ids,
                    coordinates=[[network['nodes'][n]['lon'], network['nodes'][n]['lat']] for n in node_ids],
                    distance_m=sum(edges[e]['distance'] for e in edge_ids), cost=total),
                'metrics': {'unit': 'seconds', 'before': None if old_blocked else sum(edges[e]['travel_time'] for e in old_edges),
                            'before_available': not old_blocked, 'after': total},
                'solver': result, 'engine': 'original-lns' if result else 'road-return-only'})
        except (RoutingError, ConstructionError, ValueError) as error:
            failures.append({'route_index': v['route_index'], 'error': str(error)})
    return {'revision': incident_state['revision'], 'updates': updates, 'failures': failures,
            'completed_lns_solves': sum(u['solver'] is not None for u in updates),
            'elapsed_seconds': perf_counter() - started,
            'cost_model': 'Directed travel seconds; missing speeds estimated at 30 km/h; fixed vehicle ownership',
            'objective': 'travel_time_seconds', 'engine': 'original-lns'}
