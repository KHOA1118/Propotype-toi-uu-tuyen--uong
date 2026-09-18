import copy
import unittest
from road_network.routing import RoadRouter, RoutingError


def network():
    nodes = {str(i): {'id': str(i), 'lat': 10 + y / 1000, 'lon': 106 + x / 1000}
             for i, (x, y) in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)])}
    edges = {str(i): {'id': str(i), 'from_node': str(i), 'to_node': str((i + 1) % 4),
                     'way_id': 'w', 'distance': 100, 'travel_time': None, 'status': 'unassessed'} for i in range(4)}
    return {'nodes': nodes, 'edges': edges, 'ways': {'w': {'tags': {'highway': 'residential'}}},
            'metadata': {'source': {'sha256': 'test'}}}


class RoutingTests(unittest.TestCase):
    def setUp(self):
        self.n = network()
        self.stops = [{'id': 0, 'lat': 10.00001, 'lon': 106}, {'id': 7, 'lat': 10.001, 'lon': 106.001}]

    def test_preserve_original_coordinates_and_nearest_snap(self):
        before = copy.deepcopy(self.stops)
        snaps = RoadRouter(self.n).snap(self.stops)
        self.assertEqual(self.stops, before)
        self.assertEqual(snaps[0]['lat'], 10.00001)
        self.assertEqual(snaps[0]['nearest_osm_node_id'], '0')
        self.assertGreater(snaps[0]['snap_distance_m'], 0)

    def test_geometry_uses_directed_edges_never_diagonal(self):
        g = RoadRouter(self.n).route({'stops': self.stops, 'routes': [[0, 7, 0]]})
        self.assertEqual(g['weight'], 'distance')
        route = g['routes'][0]
        self.assertEqual(route['node_ids'], ['0', '1', '2', '3', '0'])
        self.assertEqual(route['distance_m'], 400)
        for a, b, eid in zip(route['node_ids'], route['node_ids'][1:], route['edge_ids']):
            self.assertEqual((a, b), (self.n['edges'][eid]['from_node'], self.n['edges'][eid]['to_node']))

    def test_unreachable_return_is_error(self):
        del self.n['edges']['3']
        with self.assertRaisesRegex(RoutingError, 'no directed path'):
            RoadRouter(self.n).route({'stops': self.stops, 'routes': [[0, 7, 0]]})

    def test_all_times_required_no_mixed_units(self):
        for e in self.n['edges'].values():
            e['travel_time'] = 10
        self.assertEqual(RoadRouter(self.n).weight, 'travel_time')
        self.n['edges']['0']['travel_time'] = None
        self.assertEqual(RoadRouter(self.n).weight, 'distance')

    def test_parallel_edge_shortest_choice(self):
        self.n['edges']['fast'] = {**self.n['edges']['0'], 'id': 'fast', 'distance': 50}
        g = RoadRouter(self.n).route({'stops': self.stops, 'routes': [[0, 7, 0]]})
        self.assertEqual(g['routes'][0]['edge_ids'][0], 'fast')

    def test_invalid_stops_routes_and_coordinates(self):
        for stops in [None, [], self.stops + [self.stops[0]], [{'id': 0, 'lat': float('nan'), 'lon': 1}, self.stops[1]]]:
            with self.assertRaises(RoutingError):
                RoadRouter(self.n).snap(stops)
        for routes in [[[0, 99, 0]], [[7, 0]], [[0]], 'bad']:
            with self.assertRaises(RoutingError):
                RoadRouter(self.n).route({'stops': self.stops, 'routes': routes})

    def test_coincident_snapped_stops(self):
        self.stops[1].update(lat=10, lon=106)
        route = RoadRouter(self.n).route({'stops': self.stops, 'routes': [[0, 7, 0]]})['routes'][0]
        self.assertEqual(route['node_ids'], ['0'])
        self.assertEqual(route['edge_ids'], [])

    def test_access_filter_excludes_prohibited_road(self):
        self.n['ways']['w']['tags']['hgv'] = 'no'
        with self.assertRaisesRegex(RoutingError, 'No eligible'):
            RoadRouter(self.n)
