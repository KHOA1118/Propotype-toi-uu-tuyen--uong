import copy
import json
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from road_network.incidents import IncidentStore, IncidentError
from server import Handler, HTTPServer


def network():
    return {'metadata': {'source': {'sha256': 'map-a'}}, 'edges': {
        'ab': {'from_node': 'a', 'to_node': 'b', 'distance': 100, 'travel_time': 10},
        'ba': {'from_node': 'b', 'to_node': 'a', 'distance': 100, 'travel_time': None}}}


class IncidentTests(unittest.TestCase):
    def test_policies_isolation_and_raw_map_unchanged(self):
        n = network(); before = copy.deepcopy(n); store = IncidentStore()
        a = store.create({'source_sha256': 'map-a'}, n); b = store.create({'source_sha256': 'map-a'}, n)
        for kind, factor in [('congestion', 3), ('accident', 6), ('congestion', 6), ('road_blockage', None)]:
            state = store.report({'session_id': a['session_id'], 'type': kind, 'edge_id': 'ab'}, n)
            effect = state['edge_overrides']['ab']
            self.assertEqual(effect['travel_time_factor'], factor)
            self.assertEqual(effect['travel_time'], 10 * factor if factor else None)
            self.assertEqual(effect['available'], factor is not None)
        self.assertNotIn('ba', state['edge_overrides'])
        self.assertEqual(store.state(b['session_id'], n)['incidents'], [])
        self.assertEqual(n, before)
        state['incidents'].clear()
        self.assertEqual(len(store.state(a['session_id'], n)['incidents']), 4)

    def test_unknown_time_and_invalid_reports(self):
        n = network(); store = IncidentStore(); session = store.create({'source_sha256': 'map-a'}, n)
        payload = {'session_id': session['session_id'], 'type': 'accident', 'edge_id': 'ba', 'vehicle_id': 1}
        state = store.report(payload, n)
        self.assertIsNone(state['edge_overrides']['ba']['travel_time'])
        for changes in [{'type': 'fake'}, {'edge_id': 'missing'}, {'session_id': 'missing'}, {'vehicle_id': True}, {'edge_id': []}]:
            with self.assertRaises(IncidentError): store.report({**payload, **changes}, n)
        self.assertEqual(store.state(session['session_id'], n)['revision'], 1)
        n['metadata']['source']['sha256'] = 'new-map'
        with self.assertRaises(IncidentError): store.report(payload, n)

    def test_http_report_and_readback(self):
        n = network()
        class Source:
            def get(self): return n
        server = HTTPServer(('127.0.0.1', 0), Handler); server.network_store = Source()
        thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        def post(path, body):
            with urlopen(Request(base + path, json.dumps(body).encode(), {'Content-Type': 'application/json'})) as r: return json.load(r)
        try:
            session = post('/api/simulation', {'source_sha256': 'map-a'})
            updated = post('/api/incidents', {'session_id': session['session_id'], 'type': 'congestion', 'edge_id': 'ab', 'vehicle_id': 2})
            with urlopen(base + '/api/simulation?session_id=' + session['session_id']) as r:
                self.assertEqual(json.load(r), updated)
            self.assertEqual(updated['edge_overrides']['ab']['travel_time'], 30)
            with self.assertRaises(HTTPError) as error: post('/api/incidents', {'session_id': session['session_id'], 'type': 'fake', 'edge_id': 'ab'})
            self.assertEqual(error.exception.code, 400)
        finally:
            server.shutdown(); server.server_close(); thread.join()
