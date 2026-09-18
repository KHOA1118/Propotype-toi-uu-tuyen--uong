"""Live HTTP audit: observe real engine execution, independently check its output."""
from collections import Counter
import copy
import json
import math
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from server import Handler, HTTPServer

ROOT = Path(__file__).resolve().parents[1]
CORE_PATH = str(ROOT / "lns/core.py")


class ObservedHandler(Handler):
    """Profiling observes Python calls/returns; it does not replace the solver."""
    audit = None

    def log_message(self, *args):
        pass

    def observe(self, frame, event, value):
        if frame.f_code.co_filename != CORE_PATH:
            return
        name = frame.f_code.co_name
        if event == "call":
            self.audit["calls"][name] += 1
            if name == "run_lns":
                names = ["node_ids", "coordinates", "demands", "ready_times", "due_dates", "service_times", "distance_matrix", "travel_time_matrix"]
                self.audit["inputs"] = {key: frame.f_globals[key].tolist() for key in names}
                self.audit["inputs"].update(
                    mapping=copy.deepcopy(frame.f_globals["node_id_to_index"]),
                    vehicle_count=frame.f_globals["vehicle_count"],
                    vehicle_capacity=frame.f_globals["vehicle_capacity"],
                    depot_id=frame.f_locals["depot_id"],
                    initial_solution=copy.deepcopy(frame.f_locals["initial_solution"]),
                )
        elif event == "return" and name == "run_lns":
            self.audit["engine_result"] = copy.deepcopy(value)

    def do_POST(self):
        self.audit = {"calls": Counter()}
        type(self).audit = self.audit
        old_profile = sys.getprofile()
        sys.setprofile(self.observe)
        try:
            super().do_POST()
        finally:
            sys.setprofile(old_profile)


def tiny_instance():
    # Depot deliberately second, IDs sparse; nonzero departure time and waiting.
    return {
        "name": "audit-sparse-ids", "vehicle_count": 1, "vehicle_capacity": 5,
        "nodes": [
            {"id": 71, "x": -3, "y": 4, "demand": 2, "ready_time": 10, "due_date": 10, "service_time": 2},
            {"id": 0, "x": 0, "y": 0, "demand": 0, "ready_time": 4, "due_date": 25, "service_time": 0},
            {"id": 23, "x": 6, "y": -8, "demand": 3, "ready_time": 15, "due_date": 15, "service_time": 1},
        ],
        "distance_matrix": [[0, 2, 7], [3, 0, 11], [13, 5, 0]],
        "travel_time_matrix": [[0, 2, 3], [2, 0, 4], [5, 4, 0]],
    }


class RealLNSAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), ObservedHandler)
        cls.url = f"http://127.0.0.1:{cls.server.server_port}/api/optimize"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def post(self, payload):
        request = Request(self.url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=20) as response:
            return json.load(response)

    def assert_independently_feasible(self, instance, response):
        """No engine evaluator is used here."""
        nodes = {node["id"]: node for node in instance["nodes"]}
        positions = {node["id"]: i for i, node in enumerate(instance["nodes"])}

        def distance(a, b):
            if "distance_matrix" in instance:
                return instance["distance_matrix"][positions[a]][positions[b]]
            return math.hypot(nodes[a]["x"] - nodes[b]["x"], nodes[a]["y"] - nodes[b]["y"])

        def travel(a, b):
            if "travel_time_matrix" in instance:
                return instance["travel_time_matrix"][positions[a]][positions[b]]
            return distance(a, b) / instance.get("travel_speed", 1)

        served = []
        total = 0.0
        self.assertEqual(len(response["routes"]), len(response["route_details"]))
        self.assertLessEqual(len(response["routes"]), instance["vehicle_count"])
        for route, details in zip(response["routes"], response["route_details"]):
            self.assertEqual(route[0], 0)
            self.assertEqual(route[-1], 0)
            self.assertNotIn(0, route[1:-1])
            self.assertTrue(all(node_id in nodes for node_id in route))
            served.extend(route[1:-1])
            load = sum(nodes[n]["demand"] for n in route[1:-1])
            self.assertLessEqual(load, instance["vehicle_capacity"])
            self.assertAlmostEqual(load, details["capacity"]["route_load"])
            route_distance = sum(distance(a, b) for a, b in zip(route, route[1:]))
            self.assertAlmostEqual(route_distance, details["route_distance"])
            total += route_distance
            now = nodes[0]["ready_time"]
            for i, (a, b) in enumerate(zip(route, route[1:]), start=1):
                arrival = now + travel(a, b)
                start = arrival if b == 0 else max(arrival, nodes[b]["ready_time"])
                self.assertLessEqual(start, nodes[b]["due_date"])
                self.assertAlmostEqual(arrival, details["arrival_times"][i])
                self.assertAlmostEqual(start, details["service_start_times"][i])
                self.assertAlmostEqual(start - arrival, details["waiting_times"][i])
                now = start + nodes[b]["service_time"]
                self.assertAlmostEqual(now, details["departure_times"][i])
            self.assertLessEqual(now, nodes[0]["due_date"])
        self.assertEqual(Counter(served), Counter({n: 1 for n in nodes if n != 0}))
        self.assertEqual(response["objective"][0], len(response["routes"]))
        self.assertAlmostEqual(response["objective"][1], total)
        self.assertTrue(response["feasible"])

    def test_live_api_calls_real_search_and_returns_its_actual_best_solution(self):
        payload = json.loads((ROOT / "data/example_request.json").read_text())
        payload["options"] = {"iterations": 12, "seed": 42}
        with patch("lns.adapter.solve_mock", side_effect=AssertionError("Mock called")), patch("lns.adapter.mock_instance", side_effect=AssertionError("Fixture loader called")):
            response = self.post(payload)
        trace = ObservedHandler.audit
        self.assertEqual(trace["calls"]["run_lns"], 1)
        for name in ["apply_destroy_operator", "apply_repair_operator", "accept_candidate"]:
            self.assertEqual(trace["calls"][name], 12)
        engine = trace["engine_result"]
        self.assertEqual(response["routes"], engine["best_solution"])
        self.assertEqual(response["objective"], list(engine["best_evaluation"]["objective"]))
        self.assertEqual(response["route_details"], engine["best_evaluation"]["route_evaluations"]["route_evaluations"])
        self.assertEqual(response["search_seconds"], engine["elapsed_seconds"])
        self.assert_independently_feasible(payload["instance"], response)

    def test_exact_input_arrays_and_depot_are_preserved(self):
        instance = tiny_instance()
        result = self.post({"instance": instance, "initial_routes": [[0, 71, 23, 0]], "options": {"iterations": 3, "removal_count": 0}})
        inputs = ObservedHandler.audit["inputs"]
        self.assertEqual(inputs["node_ids"], [71, 0, 23])
        self.assertEqual(inputs["mapping"], {71: 0, 0: 1, 23: 2})
        self.assertEqual(inputs["coordinates"], [[-3, 4], [0, 0], [6, -8]])
        for array, field in [("demands", "demand"), ("ready_times", "ready_time"), ("due_dates", "due_date"), ("service_times", "service_time")]:
            self.assertEqual(inputs[array], [n[field] for n in instance["nodes"]])
        for field in ["vehicle_count", "vehicle_capacity", "distance_matrix", "travel_time_matrix"]:
            self.assertEqual(inputs[field], instance[field])
        self.assertEqual(inputs["depot_id"], 0)
        self.assertEqual(inputs["initial_solution"], [[0, 71, 23, 0]])
        self.assertEqual(result["route_details"][0]["arrival_times"], [4, 6, 15, 20])
        self.assertEqual(result["route_details"][0]["waiting_times"], [0, 4, 0, 0])
        self.assert_independently_feasible(instance, result)

    def test_fixed_seed_requests_repeat_and_remain_feasible(self):
        payload = json.loads((ROOT / "data/example_request.json").read_text())
        for seed in [0, 7, 42, 2147483647]:
            with self.subTest(seed=seed):
                payload["options"] = {"iterations": 20, "seed": seed}
                a, b = self.post(payload), self.post(payload)
                self.assertEqual(a["routes"], b["routes"])
                self.assertEqual(a["objective"], b["objective"])
                self.assertLessEqual(tuple(a["objective"]), tuple(a["initial_objective"]))
                self.assert_independently_feasible(payload["instance"], a)

    def test_derived_distance_and_speed_conversion(self):
        instance = tiny_instance()
        instance.pop("distance_matrix")
        instance.pop("travel_time_matrix")
        instance["travel_speed"] = 2
        for n in instance["nodes"]:
            n.update(ready_time=0, due_date=100)
        result = self.post({"instance": instance, "options": {"iterations": 3}})
        inputs = ObservedHandler.audit["inputs"]
        self.assertEqual(inputs["distance_matrix"], [[0, 5, 15], [5, 0, 10], [15, 10, 0]])
        self.assertEqual(inputs["travel_time_matrix"], [[0, 2.5, 7.5], [2.5, 0, 5], [7.5, 5, 0]])
        self.assert_independently_feasible(instance, result)

    def test_single_customer_and_coincident_coordinates(self):
        for coincident in [False, True]:
            instance = tiny_instance()
            instance["nodes"] = [instance["nodes"][1], instance["nodes"][0]]
            instance.pop("distance_matrix")
            instance.pop("travel_time_matrix")
            for n in instance["nodes"]:
                n.update(ready_time=0, due_date=100)
                if coincident:
                    n.update(x=0, y=0)
            response = self.post({"instance": instance, "options": {"iterations": 2}})
            self.assertEqual(response["routes"], [[0, 71, 0]])
            self.assert_independently_feasible(instance, response)

    def test_capacity_time_and_depot_return_violations_are_rejected(self):
        for field in ["capacity", "customer-deadline", "depot-return"]:
            instance = tiny_instance()
            if field == "capacity":
                instance.update(vehicle_count=2, vehicle_capacity=3)
            elif field == "customer-deadline":
                instance["nodes"][2].update(ready_time=0, due_date=14)
            else:
                instance["nodes"][1]["due_date"] = 19
            with self.subTest(field=field), self.assertRaises(HTTPError) as error:
                self.post({"instance": instance, "initial_routes": [[0, 71, 23, 0]]})
            self.assertEqual(error.exception.code, 422)
            self.assertEqual(ObservedHandler.audit["calls"]["run_lns"], 0)

    def test_invalid_matrix_and_options_rejected_before_search(self):
        changes = [
            lambda p: p["instance"]["distance_matrix"][0].__setitem__(1, -1),
            lambda p: p["instance"]["travel_time_matrix"][0].__setitem__(1, float("inf")),
            lambda p: p["instance"]["distance_matrix"][0].__setitem__(0, 1),
            lambda p: p["instance"]["nodes"].clear(),
            lambda p: p.update(initial_routes=[[0, 999, 0]]),
            lambda p: p.update(options={"cooling_rate": 0}),
            lambda p: p.update(options={"initial_temperature": 0}),
            lambda p: p.update(options={"min_temperature": 200}),
            lambda p: p["instance"]["nodes"][0].update(demand=True),
        ]
        for change in changes:
            payload = {"instance": tiny_instance()}
            change(payload)
            with self.assertRaises(HTTPError) as error:
                self.post(payload)
            self.assertEqual(error.exception.code, 400)
            self.assertEqual(ObservedHandler.audit["calls"]["run_lns"], 0)

    def test_aggregate_numeric_overflow_returns_json_error(self):
        instance = tiny_instance()
        instance["distance_matrix"] = [[0 if a == b else 1e308 for b in range(3)] for a in range(3)]
        with self.assertRaises(HTTPError) as error:
            self.post({"instance": instance, "initial_routes": [[0, 71, 23, 0]], "options": {"iterations": 1, "removal_count": 0}})
        self.assertEqual(error.exception.code, 400)
        self.assertIn("error", json.load(error.exception))


if __name__ == "__main__":
    unittest.main()
