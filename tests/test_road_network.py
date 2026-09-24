import hashlib
import json
import math
from pathlib import Path
import tempfile
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from road_network.loader import MapValidationError, load_osm, to_geojson
from road_network.prepare import prepare
from road_network.store import NetworkStore
from server import Handler, HTTPServer


def osm(tags='<tag k="highway" v="residential"/>', extra=""):
    return f'''<osm version="0.6"><bounds minlat="0" minlon="0" maxlat="1" maxlon="1"/>
    <node id="9007199254740993" lat="0" lon="0"><tag k="barrier" v="gate"/></node>
    <node id="2" lat="0" lon="1"/>
    <way id="100"><nd ref="9007199254740993"/><nd ref="2"/>{tags}</way>{extra}</osm>'''


class RoadNetworkTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "raw" / "test.osm"
        self.path.parent.mkdir()

    def load(self, xml=None):
        self.path.write_text(osm() if xml is None else xml, encoding="utf-8")
        return load_osm(self.path)

    def test_bidirectional_nodes_edges_ids_and_distance(self):
        network = self.load()
        self.assertEqual(set(network["nodes"]), {"9007199254740993", "2"})
        self.assertEqual(set(network["edges"]), {"osm:100:0:f", "osm:100:0:r"})
        a, b = network["edges"].values()
        self.assertEqual((a["from_node"], a["to_node"]), (b["to_node"], b["from_node"]))
        self.assertAlmostEqual(a["distance"], math.pi * 6371008.8 / 180, places=5)
        self.assertIsNone(a["travel_time"])
        self.assertEqual(a["status"], "unassessed")
        self.assertEqual(network["nodes"]["9007199254740993"]["tags"], {"barrier": "gate"})

    def test_explicit_reverse_and_implied_directions(self):
        for tag, expected in [
            ('<tag k="oneway" v="yes"/>', ["forward"]),
            ('<tag k="oneway" v="-1"/>', ["backward"]),
            ('<tag k="junction" v="roundabout"/>', ["forward"]),
            ('<tag k="junction" v="roundabout"/><tag k="oneway" v="no"/>', ["forward", "backward"]),
        ]:
            network = self.load(osm('<tag k="highway" v="residential"/>' + tag))
            self.assertEqual([e["direction"] for e in network["edges"].values()], expected)
        network = self.load(osm('<tag k="highway" v="motorway"/>'))
        self.assertEqual(len(network["edges"]), 1)

    def test_speed_units_and_directional_estimates(self):
        network = self.load(osm('<tag k="highway" v="primary"/><tag k="maxspeed" v="36"/><tag k="maxspeed:backward" v="10 mph"/><tag k="hgv" v="no"/>'))
        a, b = network["edges"].values()
        self.assertAlmostEqual(a["travel_time"], a["distance"] / 10)
        self.assertAlmostEqual(b["speed_limit_kph"], 16.09344)
        self.assertEqual(a["base_travel_time"], a["travel_time"])
        self.assertEqual(a["travel_time_source"], "maxspeed_estimate")
        self.assertEqual(network["ways"]["100"]["tags"]["hgv"], "no")

    def test_symbolic_speed_stays_unknown(self):
        for value in ["walk", "none", "0", "-5", "NaN", "50;70"]:
            network = self.load(osm(f'<tag k="highway" v="residential"/><tag k="maxspeed" v="{value}"/>'))
            self.assertTrue(all(e["travel_time"] is None for e in network["edges"].values()))

    def test_duplicate_primitive_ids_rejected(self):
        extras = ['<node id="2" lat="0" lon="1"/>', '<way id="100"/>', '<relation id="5"/><relation id="5"/>']
        for extra in extras:
            with self.subTest(extra=extra), self.assertRaisesRegex(MapValidationError, "Duplicate"):
                self.load(osm(extra=extra))

    def test_coordinate_validity(self):
        for value in ["NaN", "inf", "91", "-91", "abc"]:
            with self.subTest(value=value), self.assertRaises(MapValidationError):
                self.load(osm().replace('lat="0"', f'lat="{value}"', 1))
        with self.assertRaises(MapValidationError):
            self.load(osm().replace('lon="1"/>', 'lon="181"/>'))

    def test_missing_node_references_fail(self):
        with self.assertRaisesRegex(MapValidationError, "missing node 777"):
            self.load(osm().replace('<nd ref="2"/>', '<nd ref="777"/>'))

    def test_missing_relation_members_reported_not_silently_dropped(self):
        network = self.load(osm(extra='<relation id="5"><member type="way" ref="100" role="from"/><member type="way" ref="777" role="to"/><tag k="type" v="restriction"/><tag k="restriction" v="no_left_turn"/></relation>'))
        self.assertEqual(network["metadata"]["stats"]["missing_relation_members"], 1)
        self.assertEqual(network["validation"]["missing_relation_members"][0]["ref"], "777")
        self.assertFalse(network["relations"]["5"]["members"][1]["present_in_source"])

    def test_malformed_xml_ids_and_entities_rejected(self):
        cases = ["", "<osm>", "<html/>", '<osm version="0.5"/>', osm().replace('id="100"', 'id="bad"'), '<!DOCTYPE osm [<!ENTITY x "bad">]>' + osm()]
        for text in cases:
            with self.subTest(text=text[:30]), self.assertRaises(MapValidationError):
                self.load(text)

    def test_area_and_unresolved_direction_preserved_without_edges(self):
        extra = '<way id="200"><nd ref="2"/><nd ref="9007199254740993"/><tag k="highway" v="pedestrian"/><tag k="area" v="yes"/></way><way id="201"><nd ref="2"/><nd ref="9007199254740993"/><tag k="highway" v="service"/><tag k="oneway" v="reversible"/></way>'
        network = self.load(osm(extra=extra))
        self.assertEqual(len(network["ways"]), 3)
        self.assertEqual(len(network["edges"]), 2)
        self.assertEqual(len(network["validation"]["excluded_ways"]), 2)

    def test_parallel_ways_and_repeated_segments_keep_unique_ids(self):
        extra = '<way id="101"><nd ref="2"/><nd ref="9007199254740993"/><nd ref="2"/><tag k="highway" v="service"/></way>'
        network = self.load(osm(extra=extra))
        self.assertEqual(len(network["edges"]), 6)
        self.assertEqual(len(set(network["edges"])), 6)
        for edge in network["edges"].values():
            self.assertIn(edge["from_node"], network["nodes"])
            self.assertIn(edge["to_node"], network["nodes"])
            self.assertTrue(math.isfinite(edge["distance"]))

    def test_geojson_order_and_no_duplicate_reverse_geometry(self):
        geo = to_geojson(self.load())
        self.assertEqual(len(geo["features"]), 1)
        self.assertEqual(geo["features"][0]["geometry"]["coordinates"], [[0, 0], [1, 0]])
        self.assertEqual(len(geo["features"][0]["properties"]["edge_ids"]), 2)

    def test_readonly_source_determinism_and_cache_refresh(self):
        network = self.load()
        original = self.path.read_bytes()
        store = NetworkStore(self.path)
        a = store.get()
        self.assertIs(a, store.get())
        self.assertEqual(network["edges"], a["edges"])
        self.assertEqual(hashlib.sha256(original).hexdigest(), a["metadata"]["source"]["sha256"])
        self.assertEqual(self.path.read_bytes(), original)
        self.path.write_text(osm('<tag k="highway" v="service"/><tag k="oneway" v="yes"/>'))
        self.assertEqual(len(store.get()["edges"]), 1)

    def test_processed_artifacts_separate_from_raw(self):
        self.load()
        original = self.path.read_bytes()
        with self.assertRaises(ValueError):
            prepare(self.path, self.path.parent)
        output = Path(self.temp.name) / "processed"
        report = prepare(self.path, output)
        self.assertEqual(json.loads((output / "network.json").read_text())["metadata"]["schema_version"], "1.0")
        self.assertGreater(report["performance"]["traced_peak_python_bytes"], 0)
        self.assertEqual(original, self.path.read_bytes())

    def test_network_api_resources_and_errors(self):
        self.load()
        http = HTTPServer(("127.0.0.1", 0), Handler)
        http.network_store = NetworkStore(self.path)
        thread = threading.Thread(target=http.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{http.server_port}"
            for route in ["/api/network", "/api/network/metadata", "/api/network/geojson"]:
                with urlopen(base + route) as response:
                    self.assertEqual(response.status, 200)
                    self.assertIsInstance(json.load(response), dict)
            with self.assertRaises(HTTPError) as error:
                urlopen(Request(base + "/api/network", data=b'{}'))
            self.assertEqual(error.exception.code, 404)  # no mutation endpoint
            self.path.write_text("<broken>")
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/api/network")
            self.assertEqual(error.exception.code, 422)
            error.exception.read()
            error.exception.close()
            # Drain the serial server before deleting the malformed fixture.
            # ElementTree's failed iterator can retain its file until cyclic GC
            # on Windows; collect it without changing production map parsing.
            with urlopen(base + "/api/health") as response:
                response.read()
            import gc
            gc.collect()
            self.path.unlink()
            with self.assertRaises(HTTPError) as error:
                urlopen(base + "/api/network")
            self.assertEqual(error.exception.code, 503)
        finally:
            http.shutdown()
            http.server_close()
            thread.join()

    def test_complete_supplied_dataset_integrity(self):
        source = Path(__file__).resolve().parents[1] / "data/raw/hcm_map4.osm"
        if not source.exists():
            self.skipTest("Copy supplied hcm_map4.osm into data/raw to run complete-file test")
        before = hashlib.sha256(source.read_bytes()).hexdigest()
        network = load_osm(source)
        self.assertEqual(network["metadata"]["source"]["sha256"], before)
        self.assertEqual(hashlib.sha256(source.read_bytes()).hexdigest(), before)
        for node_id, node in network["nodes"].items():
            self.assertEqual(node_id, node["id"])
            self.assertTrue(math.isfinite(node["lat"]) and -90 <= node["lat"] <= 90)
            self.assertTrue(math.isfinite(node["lon"]) and -180 <= node["lon"] <= 180)
        for edge_id, edge in network["edges"].items():
            self.assertEqual(edge_id, edge["id"])
            self.assertIn(edge["from_node"], network["nodes"])
            self.assertIn(edge["to_node"], network["nodes"])
            way = network["ways"][edge["way_id"]]
            refs = way["node_ids"][edge["segment_index"]:edge["segment_index"] + 2]
            expected = refs if edge["direction"] == "forward" else list(reversed(refs))
            self.assertEqual([edge["from_node"], edge["to_node"]], expected)
            self.assertGreaterEqual(edge["distance"], 0)
            self.assertTrue(math.isfinite(edge["distance"]))
            if edge["travel_time"] is not None:
                self.assertTrue(math.isfinite(edge["travel_time"]))
                self.assertAlmostEqual(edge["travel_time"], edge["distance"] / (edge["speed_limit_kph"] / 3.6))


if __name__ == "__main__":
    unittest.main()
