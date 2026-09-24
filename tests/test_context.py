import copy
from pathlib import Path
import tempfile
import unittest
from road_network.context import load_context
from road_network.store import NetworkStore
from road_network.costs import initial_road_solution
import json

class ContextTests(unittest.TestCase):
    def test_only_real_complete_display_features(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.osm'
            p.write_text('<osm><node id="1" lat="10" lon="106"/><node id="2" lat="10.1" lon="106"/><node id="3" lat="10" lon="106.1"/><way id="10"><nd ref="1"/><nd ref="2"/><nd ref="3"/><nd ref="1"/><tag k="leisure" v="park"/></way><way id="11"><nd ref="1"/><nd ref="99"/><tag k="waterway" v="river"/></way><way id="12"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/></way></osm>')
            result=load_context(p)
            self.assertTrue(result['display_only']);self.assertEqual(len(result['features']),1)
            self.assertEqual(result['features'][0]['geometry']['type'],'Polygon')
    def test_full_map_context_does_not_change_routes_or_lns(self):
        root=Path(__file__).resolve().parents[1]
        store=NetworkStore(root/'data/raw/hcm_map4.osm');network=store.get()
        original=copy.deepcopy(network)
        scenario=json.loads((root/'data/presentation_scenario.json').read_text())['scenario']
        before=initial_road_solution(scenario,network)
        context=store.get('context')
        self.assertGreater(len(context['features']),0)
        self.assertIs(store.get('context'),context)
        self.assertEqual(network,original)
        after=initial_road_solution(scenario,store.get())
        self.assertEqual(before['routes'],after['routes'])
        self.assertEqual(before['objective'],after['objective'])
        self.assertEqual(before['road_geometry'],after['road_geometry'])
