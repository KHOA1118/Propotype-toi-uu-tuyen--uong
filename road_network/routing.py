"""Directed shortest-path geometry; independent of LNS and its cost matrices."""
import heapq
import math


class RoutingError(ValueError):
    pass


def separation(a, b):
    lat1, lat2 = math.radians(a['lat']), math.radians(b['lat'])
    dlat = lat2 - lat1
    dlon = math.radians(b['lon'] - a['lon'])
    h = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    return 12742000 * math.asin(math.sqrt(min(1, max(0, h))))


class RoadRouter:
    def __init__(self, network):
        self.network = network
        self._snaps = {}
        self.adj = {}
        self.edges = {}
        allowed = {'motorway', 'motorway_link', 'trunk', 'trunk_link', 'primary', 'primary_link',
                   'secondary', 'secondary_link', 'tertiary', 'tertiary_link', 'residential',
                   'unclassified', 'service', 'living_street'}
        for eid, edge in network['edges'].items():
            tags = network['ways'][edge['way_id']]['tags']
            if tags.get('highway') not in allowed or edge['status'] == 'blocked':
                continue
            if any(tags.get(k) in {'no', 'private'} for k in ('access', 'vehicle', 'motor_vehicle', 'hgv')):
                continue
            if not math.isfinite(edge['distance']) or edge['distance'] < 0:
                raise RoutingError(f'Invalid length on edge {eid}')
            self.edges[eid] = edge
            self.adj.setdefault(edge['from_node'], []).append(eid)
            self.adj.setdefault(edge['to_node'], [])
        if not self.edges:
            raise RoutingError('No eligible road edges in network')
        self.weight = 'travel_time' if all(isinstance(e.get('travel_time'), (int, float)) and
            math.isfinite(e['travel_time']) and e['travel_time'] > 0 for e in self.edges.values()) else 'distance'

    def snap(self, stops):
        if not isinstance(stops, list) or not 2 <= len(stops) <= 1001:
            raise RoutingError('Expected 2–1001 geographic stops')
        import copy
        import json
        signature = json.dumps(stops, sort_keys=True)
        if signature in self._snaps:
            return copy.deepcopy(self._snaps[signature])
        result, seen = [], set()
        for stop in stops:
            if not isinstance(stop, dict):
                raise RoutingError('Invalid stop')
            sid = stop.get('id')
            if type(sid) is not int or sid < 0 or sid in seen:
                raise RoutingError('Invalid or duplicate stop ID')
            seen.add(sid)
            for key, limit in [('lat', 90), ('lon', 180)]:
                value = stop.get(key)
                if type(value) not in (int, float) or not math.isfinite(value) or abs(value) > limit:
                    raise RoutingError(f'Invalid {key} for stop {sid}')
            nearest = min(self.adj, key=lambda nid: (separation(stop, self.network['nodes'][nid]), nid))
            node = self.network['nodes'][nearest]
            result.append({'id': sid, 'lat': stop['lat'], 'lon': stop['lon'], 'nearest_osm_node_id': nearest,
                           'snapped_lat': node['lat'], 'snapped_lon': node['lon'], 'snap_distance_m': separation(stop, node)})
        if 0 not in seen:
            raise RoutingError('Depot ID 0 is required')
        if len(self._snaps) >= 64:
            self._snaps.clear()
        self._snaps[signature] = copy.deepcopy(result)
        return result

    def demo_profile(self):
        """Only constrain generated demo orders; never relocate submitted stops."""
        b = self.network['metadata']['network_bounds']
        center = {'lat': (b['minlat'] + b['maxlat']) / 2, 'lon': (b['minlon'] + b['maxlon']) / 2}
        depot = min(self.adj, key=lambda n: (separation(center, self.network['nodes'][n]), n))
        forward = self.tree(depot)[0]
        reverse = {n: [] for n in self.adj}
        for edge in self.edges.values():
            reverse[edge['to_node']].append(edge['from_node'])
        seen, stack = {depot}, [depot]
        while stack:
            for node in reverse[stack.pop()]:
                if node not in seen:
                    seen.add(node)
                    stack.append(node)
        return {'demo_node_ids': sorted(seen.intersection(forward)), 'depot_osm_node_id': depot,
                'weight': self.weight, 'source_sha256': self.network['metadata']['source']['sha256']}

    def presentation_scenario(self):
        """Derive 24 real stops behind three shared directed depot corridors."""
        profile = self.demo_profile()
        depot = profile['depot_osm_node_id']
        distances, previous = self.tree(depot)
        reachable = set(profile['demo_node_ids'])
        first_edge = {}
        for node in reachable:
            if node == depot or not 1200 <= distances[node] <= 4200:
                continue
            cursor = node
            while cursor != depot:
                edge_id = previous.get(cursor)
                if edge_id is None:
                    break
                parent = self.edges[edge_id]['from_node']
                if parent == depot:
                    first_edge[node] = edge_id
                    break
                cursor = parent
        # Geographic areas are selected after verifying all paths traverse the depot's
        # real outbound tree. The eventual vehicle assignments remain LNS decisions.
        depot_point = self.network['nodes'][depot]
        angular_bins = {}
        for node in first_edge:
            point = self.network['nodes'][node]
            angle = (math.degrees(math.atan2(point['lat'] - depot_point['lat'], point['lon'] - depot_point['lon'])) + 360) % 360
            angular_bins.setdefault(int(angle // 30), []).append(node)
        candidate_bins = [nodes for nodes in angular_bins.values() if len(nodes) >= 12]
        if len(candidate_bins) < 3:
            raise RoutingError('Unable to find three sufficiently populated presentation areas')
        # Pick the largest area then the two areas whose direction is farthest from it.
        def angle_of(nodes):
            point = self.network['nodes'][nodes[0]]
            return (math.degrees(math.atan2(point['lat'] - depot_point['lat'], point['lon'] - depot_point['lon'])) + 360) % 360
        candidate_bins.sort(key=len, reverse=True)
        selected_bins = [candidate_bins[0]]
        while len(selected_bins) < 3:
            def angular_gap(nodes):
                value = angle_of(nodes)
                return min(abs((value - angle_of(chosen) + 180) % 360 - 180) for chosen in selected_bins)
            selected_bins.append(max((nodes for nodes in candidate_bins if nodes not in selected_bins), key=lambda nodes: (angular_gap(nodes), len(nodes))))
        selected_groups = []
        for nodes in selected_bins:
            chosen = [min(nodes, key=lambda n: (distances[n], n))]
            while len(chosen) < 8:
                def score(node):
                    return min(separation(self.network['nodes'][node], self.network['nodes'][other]) for other in chosen)
                next_node = max((n for n in nodes if n not in chosen), key=lambda n: (score(n), n))
                chosen.append(next_node)
            selected_groups.append(chosen)
        stops = [{'id': 0, 'lat': self.network['nodes'][depot]['lat'], 'lon': self.network['nodes'][depot]['lon'],
                  'osm_node_id': depot, 'demand': 0, 'ready_time': 0, 'due_date': 100000, 'service_time': 0}]
        for number, node in enumerate((n for group in selected_groups for n in group), 1):
            point = self.network['nodes'][node]
            stops.append({'id': number, 'lat': point['lat'], 'lon': point['lon'], 'osm_node_id': node,
                          'demand': 10, 'ready_time': 0, 'due_date': 100000, 'service_time': 1})
        return {'vehicle_count': 6, 'vehicle_capacity': 40,
                'options': {'iterations': 80, 'seed': 42, 'removal_count': 5}, 'stops': stops,
                'design': {'depot_osm_node_id': depot, 'shared_outbound_corridor_edges': [first_edge[group[0]] for group in selected_groups],
                    'customer_groups': [[stop['id'] for stop in stops[1 + index * 8:1 + (index + 1) * 8]] for index in range(3)]}}

    def tree(self, source):
        distances, previous, heap = {source: 0}, {}, [(0, source)]
        while heap:
            cost, node = heapq.heappop(heap)
            if cost != distances[node]:
                continue
            for eid in self.adj[node]:
                edge = self.edges[eid]
                target, candidate = edge['to_node'], cost + edge[self.weight]
                if candidate < distances.get(target, math.inf):
                    distances[target] = candidate
                    previous[target] = eid
                    heapq.heappush(heap, (candidate, target))
        return distances, previous

    def route(self, payload):
        if not isinstance(payload, dict):
            raise RoutingError('Expected routing object')
        snaps = self.snap(payload.get('stops'))
        by_id = {s['id']: s for s in snaps}
        trees = {s['nearest_osm_node_id']: self.tree(s['nearest_osm_node_id']) for s in snaps}
        depot = by_id[0]['nearest_osm_node_id']
        for stop in snaps:
            node = stop['nearest_osm_node_id']
            if node not in trees[depot][0] or depot not in trees[node][0]:
                raise RoutingError(f"Stop {stop['id']} (OSM {node}) has no directed path to/from depot; no straight-line fallback")
        groups = {}
        for key in ('routes', 'initial_routes'):
            routes = payload.get(key, [])
            if not isinstance(routes, list) or len(routes) > 1001:
                raise RoutingError(f'Invalid {key}')
            geometries = []
            for route in routes:
                if not isinstance(route, list) or not 2 <= len(route) <= 1003 or route[0] != 0 or route[-1] != 0:
                    raise RoutingError('Routes must start and end at depot 0')
                if any(type(sid) is not int or sid not in by_id for sid in route):
                    raise RoutingError('Route contains unknown stop ID')
                nodes, edges, legs = [], [], []
                for a, b in zip(route, route[1:]):
                    source, target = by_id[a]['nearest_osm_node_id'], by_id[b]['nearest_osm_node_id']
                    distance, previous = trees[source]
                    if target not in distance:
                        raise RoutingError(f'No directed road path from stop {a} to {b}')
                    cursor, leg_edges = target, []
                    while cursor != source:
                        eid = previous[cursor]
                        leg_edges.append(eid)
                        cursor = self.edges[eid]['from_node']
                    leg_edges.reverse()
                    leg_nodes = [source] + [self.edges[eid]['to_node'] for eid in leg_edges]
                    legs.append({'from_stop': a, 'to_stop': b, 'node_ids': leg_nodes, 'edge_ids': leg_edges})
                    nodes.extend(leg_nodes if not nodes else leg_nodes[1:])
                    edges.extend(leg_edges)
                geometries.append({'stop_sequence': route, 'node_ids': nodes, 'edge_ids': edges, 'legs': legs,
                    'coordinates': [[self.network['nodes'][n]['lon'], self.network['nodes'][n]['lat']] for n in nodes],
                    'distance_m': sum(self.edges[e]['distance'] for e in edges),
                    'cost': sum(self.edges[e][self.weight] for e in edges)})
            groups[key] = geometries
        overlap = self._overlap(groups['routes'])
        return {'snapped_stops': snaps, **groups, 'overlap': overlap, 'weight': self.weight,
                'cost_unit': 'seconds' if self.weight == 'travel_time' else 'meters',
                'source_sha256': self.network['metadata']['source']['sha256'],
                'limitations': 'Directed edges and basic motor-road access only; turn restrictions and truck dimensions are not enforced.'}

    def _overlap(self, routes):
        edge_users, node_users = {}, {}
        for vehicle, route in enumerate(routes, 1):
            for edge_id in set(route['edge_ids']):
                edge_users.setdefault(edge_id, set()).add(vehicle)
            for node_id in set(route['node_ids']):
                node_users.setdefault(node_id, set()).add(vehicle)
        shared_edges = []
        for edge_id, users in edge_users.items():
            if len(users) < 2:
                continue
            edge = self.edges[edge_id]
            shared_edges.append({'edge_id': edge_id, 'from_node': edge['from_node'], 'to_node': edge['to_node'],
                                 'vehicles_affected': sorted(users), 'routes_affected': len(users),
                                 'baseline_distance_m': edge['distance'], 'baseline_travel_time_s': edge.get('travel_time'),
                                 'travel_time_source': edge.get('travel_time_source')})
        shared_nodes = [{'node_id': node, 'vehicles_affected': sorted(users), 'routes_affected': len(users)}
                        for node, users in node_users.items() if len(users) >= 2]
        # Prefer a shared edge away from the exact depot so an incident is easy to see.
        depot_node = routes[0]['node_ids'][0] if routes and routes[0]['node_ids'] else None
        depot = self.network['nodes'][depot_node] if depot_node else {'lat': 0, 'lon': 0}
        ranked = sorted(shared_edges, key=lambda item: (-item['routes_affected'], -item['baseline_distance_m'],
            abs(separation(depot, self.network['nodes'][item['from_node']]) - 450), item['edge_id']))
        return {'shared_node_count': len(shared_nodes), 'shared_edge_count': len(shared_edges),
                'shared_nodes': sorted(shared_nodes, key=lambda item: (-item['routes_affected'], item['node_id'])),
                'shared_edges': sorted(shared_edges, key=lambda item: (-item['routes_affected'], item['edge_id'])),
                'most_shared_intersection': sorted(shared_nodes, key=lambda item: (-item['routes_affected'], item['node_id']))[0] if shared_nodes else None,
                'incident_hotspot': ranked[0] if ranked else None}
