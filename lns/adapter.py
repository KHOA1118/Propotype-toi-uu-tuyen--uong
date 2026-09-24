import contextlib
import io
import json
import math
from pathlib import Path
import random
import runpy
import threading
import time
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
SOLVE_LOCK = threading.Lock()  # notebook stdout redirection is process-global

class InputError(ValueError):
    pass

class ConstructionError(ValueError):
    pass


def _number(value, label, minimum=None):
    try:
        valid = type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        valid = False
    if not valid:
        raise InputError(f"{label} must be a finite number")
    if minimum is not None and value < minimum:
        raise InputError(f"{label} must be >= {minimum}")
    return float(value)


def _integer(value, label, minimum, maximum):
    if type(value) is not int or not minimum <= value <= maximum:
        raise InputError(f"{label} must be an integer between {minimum} and {maximum}")
    return value


def validate_options(iterations=30, seed=42, removal_count=3,
                     initial_temperature=100.0, cooling_rate=0.995, min_temperature=0.01):
    options = {
        "iterations": _integer(iterations, "iterations", 1, 100),
        "seed": _integer(seed, "seed", 0, 2147483647),
        "removal_count": _integer(removal_count, "removal_count", 0, 1000),
        "initial_temperature": _number(initial_temperature, "initial_temperature", 0),
        "cooling_rate": _number(cooling_rate, "cooling_rate", 0),
        "min_temperature": _number(min_temperature, "min_temperature", 0),
    }
    if not 0 < options["min_temperature"] <= options["initial_temperature"]:
        raise InputError("Temperatures must satisfy 0 < min_temperature <= initial_temperature")
    if not 0 < options["cooling_rate"] <= 1:
        raise InputError("cooling_rate must be in (0, 1]")
    return options


def validate_request(payload):
    if not isinstance(payload, dict) or set(payload) - {"instance", "options", "initial_routes"}:
        raise InputError("Expected instance, optional options and optional initial_routes")
    instance = payload.get("instance")
    allowed = {"name", "vehicle_count", "vehicle_capacity", "nodes", "travel_speed", "distance_matrix", "travel_time_matrix"}
    if not isinstance(instance, dict) or set(instance) - allowed:
        raise InputError("instance must be an object with supported instance fields")
    name = instance.get("name", "api-instance")
    if not isinstance(name, str) or len(name) > 200:
        raise InputError("instance.name must be a string of at most 200 characters")
    count = _integer(instance.get("vehicle_count"), "vehicle_count", 1, 1000)
    capacity = _number(instance.get("vehicle_capacity"), "vehicle_capacity", 0)
    if capacity <= 0:
        raise InputError("vehicle_capacity must be positive")
    nodes = instance.get("nodes")
    if not isinstance(nodes, list) or not 2 <= len(nodes) <= 1001:
        raise InputError("nodes must contain one depot and 1–1000 customers")
    fields = {"id", "x", "y", "demand", "ready_time", "due_date", "service_time"}
    normalized, ids = [], set()
    for index, node in enumerate(nodes):
        if not isinstance(node, dict) or set(node) != fields:
            raise InputError(f"nodes[{index}] must contain exactly {sorted(fields)}")
        node_id = _integer(node["id"], f"nodes[{index}].id", 0, 2147483647)
        if node_id in ids:
            raise InputError(f"Duplicate node ID {node_id}")
        ids.add(node_id)
        row = {"id": node_id}
        for key in fields - {"id"}:
            row[key] = _number(node[key], f"nodes[{index}].{key}", None if key in {"x", "y"} else 0)
        if row["ready_time"] > row["due_date"]:
            raise InputError(f"Node {node_id}: ready_time exceeds due_date")
        if node_id == 0 and (row["demand"] != 0 or row["service_time"] != 0):
            raise InputError("Depot 0 must have zero demand and service_time")
        if node_id != 0 and not 0 < row["demand"] <= capacity:
            raise InputError(f"Customer {node_id}: demand must be positive and <= capacity")
        normalized.append(row)
    if 0 not in ids:
        raise InputError("Exactly one depot with id 0 is required")
    if sum(row["demand"] for row in normalized) > count * capacity:
        raise InputError("Total demand exceeds fleet capacity")
    speed = _number(instance.get("travel_speed", 1.0), "travel_speed", 0)
    if speed <= 0:
        raise InputError("travel_speed must be positive")
    clean = dict(name=name, vehicle_count=count, vehicle_capacity=capacity, nodes=normalized, travel_speed=speed)
    for key in ("distance_matrix", "travel_time_matrix"):
        if key not in instance:
            continue
        matrix = instance[key]
        if not isinstance(matrix, list) or len(matrix) != len(nodes):
            raise InputError(f"{key} must have one row per node")
        result = []
        for i, row in enumerate(matrix):
            if not isinstance(row, list) or len(row) != len(nodes):
                raise InputError(f"{key} must be square, in nodes array order")
            values = [_number(v, key, 0) for v in row]
            if values[i] != 0:
                raise InputError(f"{key} diagonal must be zero")
            result.append(values)
        clean[key] = result
    options = payload.get("options", {})
    option_names = {"iterations", "seed", "removal_count", "initial_temperature", "cooling_rate", "min_temperature"}
    if not isinstance(options, dict) or set(options) - option_names:
        raise InputError("Unsupported options")
    options = validate_options(**options)
    routes = payload.get("initial_routes")
    if "initial_routes" in payload:
        if not isinstance(routes, list) or not routes or len(routes) > count:
            raise InputError("initial_routes must contain 1–vehicle_count routes")
        customers = []
        for route in routes:
            if (not isinstance(route, list) or len(route) < 3
                    or any(type(n) is not int or n not in ids for n in route)
                    or route[0] != 0 or route[-1] != 0 or 0 in route[1:-1]):
                raise InputError("Each initial route must be [0, customer IDs..., 0]")
            customers.extend(route[1:-1])
        if len(customers) != len(ids) - 1 or set(customers) != ids - {0}:
            raise InputError("initial_routes must cover every customer exactly once")
        routes = [list(route) for route in routes]
    return {"instance": clean, "options": options, "initial_routes": routes}


def solve_instance(instance, options=None, initial_routes=None):
    """Solve caller data without loading fixtures or depending on HTTP."""
    request = {"instance": instance, "options": {} if options is None else options}
    if initial_routes is not None:
        request["initial_routes"] = initial_routes
    clean = validate_request(request)
    with SOLVE_LOCK, contextlib.redirect_stdout(io.StringIO()):
        result = _solve(clean)
        # Finite individual costs can still overflow when the engine sums them.
        # Reject unrepresentable output at the boundary; never alter the costs.
        try:
            json.dumps(result, allow_nan=False)
        except ValueError as error:
            raise InputError("Numerical overflow in solution metrics; rescale input units") from error
        return result


def _solve(request):
    started = time.perf_counter()
    dataset, options = request["instance"], request["options"]
    loaded = runpy.run_path(str(ROOT / "lns/core.py"))
    env = loaded["run_lns"].__globals__
    nodes = dataset["nodes"]
    ids = np.array([n["id"] for n in nodes], dtype=int)
    coords = np.array([[n["x"], n["y"]] for n in nodes], dtype=float)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        distances = np.asarray(dataset["distance_matrix"], dtype=float) if "distance_matrix" in dataset else np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
        travel = np.asarray(dataset["travel_time_matrix"], dtype=float) if "travel_time_matrix" in dataset else distances / dataset["travel_speed"]
    if not np.isfinite(distances).all() or not np.isfinite(travel).all():
        raise InputError("Derived matrix overflow; use smaller coordinates or explicit matrices")
    env.update(
        random=random.Random(options["seed"]), node_ids=ids, coordinates=coords,
        node_id_to_index={int(n): i for i, n in enumerate(ids)},
        distance_matrix=distances, travel_time_matrix=travel,
        demands=np.array([n["demand"] for n in nodes]),
        ready_times=np.array([n["ready_time"] for n in nodes]),
        due_dates=np.array([n["due_date"] for n in nodes]),
        service_times=np.array([n["service_time"] for n in nodes]),
        vehicle_count=dataset["vehicle_count"], vehicle_capacity=dataset["vehicle_capacity"],
    )
    capacity = dataset["vehicle_capacity"]
    initial = request["initial_routes"]
    if initial is None:
        try:
            initial = env["build_initial_solution"](env["get_customers_by_ready_time"](), capacity)["solution"]
        except ValueError as error:
            raise ConstructionError(f"Initial construction failed: {error}. This does not prove infeasibility; supply feasible initial_routes or review the instance.") from error
    before = env["evaluate_solution"](initial, capacity)
    if not before["is_solution_feasible"]:
        raise ConstructionError("Initial routes violate capacity, time windows or depot return time")
    search_options = {k: v for k, v in options.items() if k != "seed"}
    result = env["run_lns"](initial, capacity, **search_options, progress_interval=options["iterations"])
    best = result["best_evaluation"]
    return {
        "dataset": {k: v for k, v in dataset.items() if not k.endswith("_matrix")},
        "engine": "original-lns", "objective_order": ["used_vehicle_count", "total_distance"],
        "matrix_sources": {"distance": "provided" if "distance_matrix" in dataset else "euclidean", "travel_time": "provided" if "travel_time_matrix" in dataset else "distance / travel_speed"},
        "initial_routes": initial, "routes": result["best_solution"],
        "initial_objective": list(before["objective"]), "objective": list(best["objective"]),
        "route_details": best["route_evaluations"]["route_evaluations"],
        "feasible": best["is_solution_feasible"], "iterations_completed": len(result["iteration_log"]),
        "seed": options["seed"], "options": options,
        "search_seconds": result["elapsed_seconds"], "total_seconds": time.perf_counter() - started,
    }


def mock_instance():
    """Explicit fixture utility; never an automatic API fallback."""
    dataset = json.loads((ROOT / "data/mock.json").read_text(encoding="utf-8"))
    for node in dataset["nodes"]:
        node.update(ready_time=0, due_date=10000, service_time=0 if node["id"] == 0 else 1)
    return dataset


def solve_mock(iterations=30, seed=42):
    return solve_instance(mock_instance(), {"iterations": iterations, "seed": seed})
