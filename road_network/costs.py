"""Cached static road preprocessing and an explicit seconds-based LNS boundary."""
from copy import deepcopy
from time import perf_counter
from .routing import RoadRouter, RoutingError, separation
from lns.adapter import solve_instance

_contexts = {}


def context(network):
    key = (id(network), network['metadata']['source']['sha256'])
    if key not in _contexts:
        edges = {eid: dict(e, travel_time=e.get('travel_time') or e['distance']/(30/3.6))
                 for eid, e in network['edges'].items()}
        timed = dict(network, edges=edges)
        router = RoadRouter(timed)
        router.weight = 'travel_time'
        _contexts[key] = (timed, router)
    return _contexts[key]


def overlap_areas(router, geometry):
    """Disjoint 250m spatial areas with >=100m shared directed infrastructure.

    Require centers >=350m apart: adjacent OSM fragments do not count as
    separate corridors merely because a way was split into many short edges.
    """
    shared = geometry['overlap']['shared_edges']
    remaining = {e['edge_id']: e for e in shared}
    areas = []
    for seed in sorted(shared, key=lambda e: (-e['routes_affected'], -e['baseline_distance_m'], e['edge_id'])):
        center = router.network['nodes'][seed['from_node']]
        if any(separation(center, a['center']) < 350 for a in areas):
            continue
        members = [e for e in remaining.values() if separation(center, router.network['nodes'][e['from_node']]) <= 250]
        distance = sum(e['baseline_distance_m'] for e in members)
        if distance < 100:
            continue
        users = sorted(set(v for e in members for v in e['vehicles_affected']))
        areas.append({'center': center, 'edge_ids': [e['edge_id'] for e in members], 'distance_m': distance, 'vehicles': users})
        for e in members:
            remaining.pop(e['edge_id'], None)
    sharing = sorted(set(v for e in shared for v in e['vehicles_affected']))
    maximum = max((e['routes_affected'] for e in shared), default=0)
    return {'areas': areas, 'shared_corridors': len(areas), 'sharing_vehicles': sharing,
            'maximum_edge_users': maximum,
            'accepted': len(geometry['routes']) == 6 and len(sharing) >= 4 and maximum >= 3 and len(areas) >= 3}


def initial_road_solution(scenario, network):
    started = perf_counter()
    timed, router = context(network)
    snaps = router.snap(scenario['stops'])
    by_id = {s['id']: s['nearest_osm_node_id'] for s in snaps}
    stops = scenario['stops']
    trees = {nid: router.tree(nid)[0] for nid in set(by_id.values())}
    try:
        matrix = [[trees[by_id[a['id']]][by_id[b['id']]] for b in stops] for a in stops]
    except KeyError as error:
        raise RoutingError('Some customers cannot be reached by directed roads') from error
    nodes = [dict(id=s['id'], x=s['lon'], y=s['lat'], demand=s['demand'], ready_time=s['ready_time'],
                  due_date=s['due_date'], service_time=s['service_time']) for s in stops]
    result = solve_instance({'name':'HCM-road-seconds', 'nodes':nodes, 'vehicle_count':scenario['vehicle_count'],
                             'vehicle_capacity':scenario['vehicle_capacity'], 'distance_matrix':matrix,
                             'travel_time_matrix':matrix}, scenario.get('options'))
    before_geometry = perf_counter()
    geometry = router.route({'stops':stops, 'routes':result['routes'], 'initial_routes':result['initial_routes']})
    result['road_geometry'] = geometry
    result['overlap_analysis'] = overlap_areas(router, geometry)
    result['cost_unit'] = 'seconds'
    result['geometry_seconds'] = perf_counter()-before_geometry
    result['initial_pipeline_seconds'] = perf_counter()-started
    return result
