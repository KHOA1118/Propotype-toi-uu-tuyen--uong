import ast
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import patch, Mock
import io
import contextlib
import math
import copy
import zipfile
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from lns.adapter import solve_mock, mock_instance, solve_instance
from server import Handler, HTTPServer

ROOT = Path(__file__).resolve().parents[1]


def request_options(**options):
    return {"instance": mock_instance(), "options": options}


class PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), Handler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, payload):
        request = Request(self.url + "/api/optimize", data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=15) as response:
            return json.load(response)

    def test_http_flow_and_solution_constraints(self):
        for path in ["/", "/app.js", "/style.css", "/api/health"]:
            with urlopen(self.url + path) as response:
                self.assertEqual(response.status, 200)
        result = self.post(request_options(iterations=30, seed=42))
        self.assertTrue(result["feasible"])
        self.assertEqual(result["iterations_completed"], 30)
        self.assertLessEqual(tuple(result["objective"]), tuple(result["initial_objective"]))
        customers = [n for route in result["routes"] for n in route if n != 0]
        self.assertEqual(sorted(customers), list(range(1, 11)))
        self.assertLessEqual(len(result["routes"]), 3)
        for route in result["routes"]:
            self.assertEqual((route[0], route[-1]), (0, 0))
            self.assertLessEqual((len(route) - 2) * 10, 40)

    def test_invalid_requests_and_recovery(self):
        for payload in [{"iterations": 0}, {"iterations": True}, {"iterations": 101}, {"seed": "oops"}, {"seed": -1}, [], {"unexpected": 2}]:
            with self.assertRaises(HTTPError) as error:
                self.post({"instance": mock_instance(), "options": payload})
            self.assertEqual(error.exception.code, 400)
        request = Request(self.url + "/api/optimize", data=b"{broken")
        with self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)
        self.assertTrue(self.post(request_options())["feasible"])

    def test_isolated_repeatable_instances(self):
        first = solve_mock(seed=42)
        solve_mock(seed=7)
        second = solve_mock(seed=42)
        self.assertEqual(first["routes"], second["routes"])
        self.assertEqual(first["objective"], second["objective"])

    def test_solver_errors_are_500_and_recover(self):
        for failure in [ValueError("internal data failure"), RuntimeError("search failed")]:
            with patch("server.solve_instance", side_effect=failure), contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(HTTPError) as error:
                    self.post(request_options())
                self.assertEqual(error.exception.code, 500)
                self.assertIn("LNS failed", json.load(error.exception)["error"])
        self.assertTrue(self.post(request_options())["feasible"])

    def test_client_disconnect_does_not_raise(self):
        handler = Handler.__new__(Handler)
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()
        handler.wfile = Mock()
        handler.wfile.write.side_effect = ConnectionAbortedError("Browser cancelled")
        handler.reply(200, {"status": "ok"})
        self.assertTrue(handler.close_connection)

    def test_boundaries_and_independent_distance_calculation(self):
        for iterations, seed in [(1, 0), (100, 2147483647), (30, 7)]:
            result = self.post(request_options(iterations=iterations, seed=seed))
            self.assertEqual(result["iterations_completed"], iterations)
            self.assertTrue(result["feasible"])
            self.assertLessEqual(tuple(result["objective"]), tuple(result["initial_objective"]))
            nodes = {node["id"]: node for node in result["dataset"]["nodes"]}
            actual_distance = sum(
                math.hypot(nodes[a]["x"] - nodes[b]["x"], nodes[a]["y"] - nodes[b]["y"])
                for route in result["routes"] for a, b in zip(route, route[1:])
            )
            self.assertAlmostEqual(actual_distance, result["objective"][1])
            for route in result["routes"]:
                self.assertLessEqual(sum(nodes[n]["demand"] for n in route), result["dataset"]["vehicle_capacity"])

    def test_unknown_routes_and_oversized_body(self):
        for path in ["/missing", "/../server.py"]:
            with self.assertRaises(HTTPError) as error:
                urlopen(self.url + path)
            self.assertEqual(error.exception.code, 404)
        request = Request(self.url + "/api/optimize", data=b" " * 4097)
        with patch("server.MAX_BODY_BYTES", 4096), self.assertRaises(HTTPError) as error:
            urlopen(request)
        self.assertEqual(error.exception.code, 400)

    def test_instance_required_no_silent_mock_fallback(self):
        for payload in [{}, {"iterations": 30}, {"instance": None}]:
            with self.assertRaises(HTTPError) as error:
                self.post(payload)
            self.assertEqual(error.exception.code, 400)

    def test_custom_ids_coordinates_and_supplied_matrices(self):
        instance = {
            "name": "custom-matrix", "vehicle_count": 1, "vehicle_capacity": 10,
            "nodes": [
                {"id": 23, "x": -200, "y": 900, "demand": 2, "ready_time": 0, "due_date": 100, "service_time": 2},
                {"id": 0, "x": 0, "y": 0, "demand": 0, "ready_time": 0, "due_date": 100, "service_time": 0},
                {"id": 71, "x": 400, "y": 800, "demand": 3, "ready_time": 0, "due_date": 100, "service_time": 4},
            ],
            "distance_matrix": [[0, 2, 7], [3, 0, 11], [13, 5, 0]],
            "travel_time_matrix": [[0, 1, 2], [3, 0, 4], [5, 6, 0]],
        }
        original = copy.deepcopy(instance)
        result = self.post({"instance": instance, "initial_routes": [[0, 23, 71, 0]], "options": {"iterations": 1, "removal_count": 0}})
        self.assertEqual(result["routes"], [[0, 23, 71, 0]])
        self.assertEqual(result["objective"], [1, 15.0])
        self.assertEqual(result["engine"], "original-lns")
        self.assertEqual(result["matrix_sources"], {"distance": "provided", "travel_time": "provided"})
        details = result["route_details"][0]
        self.assertEqual(details["arrival_times"], [0, 3, 7, 17])
        self.assertEqual(instance, original)
        self.assertEqual(solve_instance(instance, {"iterations": 1, "removal_count": 0}, [[0, 23, 71, 0]])["objective"], [1, 15.0])
        self.assertEqual(instance, original)

    def test_invalid_instance_fields(self):
        bad_instances = []
        for mutate in [
            lambda x: x["nodes"][1].update(id=0),
            lambda x: x["nodes"][0].update(id=999),
            lambda x: x["nodes"][1].update(demand=999),
            lambda x: x["nodes"][1].update(x=float("nan")),
            lambda x: x["nodes"][1].update(ready_time=20000),
            lambda x: x.update(vehicle_count=True),
            lambda x: x.update(travel_speed=0),
            lambda x: x.update(distance_matrix=[[0]]),
            lambda x: x["nodes"][1].pop("service_time"),
        ]:
            instance = mock_instance()
            mutate(instance)
            bad_instances.append(instance)
        for instance in bad_instances:
            with self.assertRaises(HTTPError) as error:
                self.post({"instance": instance})
            self.assertEqual(error.exception.code, 400)

    def test_unconstructable_and_infeasible_initial_routes(self):
        instance = mock_instance()
        instance["nodes"][1]["due_date"] = 0
        for payload in [
            {"instance": instance},
            {"instance": mock_instance(), "initial_routes": [[0] + list(range(1, 11)) + [0]]},
        ]:
            with self.assertRaises(HTTPError) as error:
                self.post(payload)
            self.assertEqual(error.exception.code, 422)
        with self.assertRaises(HTTPError) as error:
            self.post({"instance": mock_instance(), "initial_routes": [[0, 1, 1, 0]]})
        self.assertEqual(error.exception.code, 400)

    def test_changed_input_changes_computed_cost(self):
        instance = mock_instance()
        baseline = self.post({"instance": instance})
        for node in instance["nodes"]:
            node["x"] *= 2
            node["y"] *= 2
        changed = self.post({"instance": instance})
        self.assertNotEqual(baseline["objective"][1], changed["objective"][1])
        self.assertGreater(changed["objective"][1], baseline["objective"][1])

    def test_homberger_subset_real_data(self):
        source = Path("D:/homberger_1000_customer_instances.zip")
        if not source.exists():
            self.skipTest("User's Homberger archive is not present")
        with zipfile.ZipFile(source) as archive:
            text = archive.read("C1_10_1.TXT").decode()
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        vehicle_index = lines.index("VEHICLE")
        fleet, capacity = lines[vehicle_index + 2].split()
        rows = lines[lines.index("CUSTOMER") + 2:][:11]
        fields = ["id", "x", "y", "demand", "ready_time", "due_date", "service_time"]
        nodes = []
        for row in rows:
            values = row.split()
            nodes.append(dict(zip(fields, [int(values[0])] + [float(v) for v in values[1:]])))
        result = self.post({"instance": {"name": "C1_10_1-first-10", "vehicle_count": int(fleet), "vehicle_capacity": float(capacity), "nodes": nodes}, "options": {"iterations": 5}})
        self.assertTrue(result["feasible"])
        self.assertEqual(result["dataset"]["nodes"][1]["service_time"], 90)
        self.assertEqual(sorted(n for r in result["routes"] for n in r if n), list(range(1, 11)))

    def test_original_functions_unchanged(self):
        source = Path("D:/base_vrp+lns_(refined).py")
        if not source.exists():
            self.skipTest("Original export is optional outside the owner's machine")
        original_text = source.read_text(encoding="utf-8-sig")
        extracted_text = (ROOT / "lns/core.py").read_text(encoding="utf-8")
        original = ast.parse(original_text)
        extracted = ast.parse(extracted_text)
        originals = {node.name: node for node in original.body if isinstance(node, ast.FunctionDef)}
        functions = [node for node in extracted.body if isinstance(node, ast.FunctionDef)]
        self.assertEqual(len(functions), 54)
        for node in functions:
            self.assertEqual(ast.dump(node), ast.dump(originals[node.name]), node.name)
            self.assertEqual(ast.get_source_segment(extracted_text, node), ast.get_source_segment(original_text, originals[node.name]), node.name)
        for name in ["DESTROY_OPERATORS", "REPAIR_OPERATORS"]:
            def registry(tree):
                return next(n for n in tree.body if isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in n.targets))
            self.assertEqual(ast.dump(registry(original)), ast.dump(registry(extracted)))


if __name__ == "__main__":
    unittest.main()
