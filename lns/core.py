import math
import random
import time
from collections import Counter
import numpy as np

DEPOT_ID = 0

def get_distance(from_node, to_node):
    from_node = int(from_node)
    to_node = int(to_node)

    if from_node not in node_id_to_index:
        raise KeyError(f"Unknown origin node ID: {from_node}")
    if to_node not in node_id_to_index:
        raise KeyError(f"Unknown destination node ID: {to_node}")

    from_index = node_id_to_index[from_node]
    to_index = node_id_to_index[to_node]

    return float(distance_matrix[from_index, to_index])

def get_travel_time(from_node, to_node):
    from_node = int(from_node)
    to_node = int(to_node)

    if from_node not in node_id_to_index:
        raise KeyError(f"Unknown origin node ID: {from_node}")

    if to_node not in node_id_to_index:
        raise KeyError(f"Unknown destination node ID: {to_node}")

    from_index = node_id_to_index[from_node]
    to_index = node_id_to_index[to_node]

    return float(travel_time_matrix[from_index, to_index])

def get_node_attributes(node_id):
    node_id = int(node_id)

    if node_id not in node_id_to_index:
        raise KeyError(f"Unknown node ID: {node_id}")

    node_index = node_id_to_index[node_id]

    return {
        "node_id": node_id,
        "demand": float(demands[node_index]),
        "ready_time": float(
            ready_times[node_index]
        ),
        "due_date": float(
            due_dates[node_index]
        ),
        "service_time": float(
            service_times[node_index]
        ),
        "x_coord": float(
            coordinates[node_index, 0]
        ),
        "y_coord": float(
            coordinates[node_index, 1]
        ),
    }

def normalize_route(route, depot_id=DEPOT_ID):
    normalized_route = [int(node_id) for node_id in route]

    if not normalized_route:
        return [depot_id, depot_id]

    if normalized_route[0] != depot_id:
        normalized_route.insert(0, depot_id)

    if normalized_route[-1] != depot_id:
        normalized_route.append(depot_id)

    if len(normalized_route) == 1:
        normalized_route.append(depot_id)

    return normalized_route

def validate_route_structure(route, depot_id=DEPOT_ID):
    normalized_route = normalize_route(route, depot_id)
    unknown_nodes = sorted(
        {
            node_id
            for node_id in normalized_route
            if node_id not in node_id_to_index
        }
    )

    if unknown_nodes:
        raise ValueError(f"Unknown node IDs in route: {unknown_nodes}")
    internal_depot_positions = [
        position
        for position, node_id in enumerate(
            normalized_route[1:-1],
            start=1,
        )
        if node_id == depot_id
    ]
    if internal_depot_positions:
        raise ValueError("Depot found inside route at positions: ")
    return normalized_route

def check_duplicate_customers_in_route(
    route,
    depot_id=DEPOT_ID,
):
    normalized_route = validate_route_structure(
        route,
        depot_id,
    )

    customer_counts = Counter(
        node_id
        for node_id in normalized_route
        if node_id != depot_id
    )

    duplicate_customers = sorted(
        node_id
        for node_id, count in customer_counts.items()
        if count > 1
    )

    if duplicate_customers:
        raise ValueError("Duplicate customers detected in route: ")
    return normalized_route

def _calculate_route_load_from_normalized(
    normalized_route,
    depot_id,
):
    return float(
        sum(
            demands[node_id_to_index[node_id]]
            for node_id in normalized_route
            if node_id != depot_id
        )
    )

def _build_capacity_result(
    route_load,
    vehicle_capacity,
):
    vehicle_capacity = float(vehicle_capacity)

    if vehicle_capacity <= 0:
        raise ValueError( "Vehicle capacity must be greater than zero.")

    return {
        "route_load": float(route_load),
        "vehicle_capacity": vehicle_capacity,
        "remaining_capacity": float(
            vehicle_capacity - route_load
        ),
        "is_capacity_feasible": bool(
            route_load <= vehicle_capacity
        ),
    }

def calculate_route_load(
    route,
    depot_id=DEPOT_ID,
):
    normalized_route = check_duplicate_customers_in_route(
        route,
        depot_id,
    )

    return _calculate_route_load_from_normalized(
        normalized_route,
        depot_id,
    )

def check_route_capacity(
    route,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    normalized_route = check_duplicate_customers_in_route(
        route,
        depot_id,
    )

    route_load = _calculate_route_load_from_normalized(
        normalized_route,
        depot_id,
    )

    return _build_capacity_result(
        route_load,
        vehicle_capacity,
    )

def _calculate_route_distance_from_normalized(
    normalized_route,
):
    return float(
        sum(
            get_distance(from_node, to_node)
            for from_node, to_node in zip(
                normalized_route[:-1],
                normalized_route[1:],
            )
        )
    )

def calculate_route_distance(
    route,
    depot_id=DEPOT_ID,
):
    normalized_route = check_duplicate_customers_in_route(
        route,
        depot_id,
    )

    return _calculate_route_distance_from_normalized(
        normalized_route
    )

def _calculate_route_schedule_from_normalized(
    normalized_route,
    depot_id,
):
    route_length = len(normalized_route)

    arrival_times = [0.0] * route_length
    waiting_times = [0.0] * route_length
    service_start_times = [0.0] * route_length
    departure_times = [0.0] * route_length

    depot_index = node_id_to_index[depot_id]

    arrival_times[0] = float(
        ready_times[depot_index]
    )

    service_start_times[0] = arrival_times[0]

    departure_times[0] = float(
        service_start_times[0]
        + service_times[depot_index]
    )

    for position in range(1, route_length):
        from_node = normalized_route[position - 1]
        to_node = normalized_route[position]
        to_index = node_id_to_index[to_node]

        arrival_time = (
            departure_times[position - 1]
            + get_travel_time(from_node, to_node)
        )

        if to_node == depot_id:
            waiting_time = 0.0
            service_start_time = arrival_time
        else:
            waiting_time = max(
                0.0,
                float(ready_times[to_index]) - arrival_time,
            )
            service_start_time = (
                arrival_time + waiting_time
            )

        departure_time = (
            service_start_time
            + float(service_times[to_index])
        )

        arrival_times[position] = float(arrival_time)
        waiting_times[position] = float(waiting_time)
        service_start_times[position] = float(
            service_start_time
        )
        departure_times[position] = float(
            departure_time
        )

    return {
        "arrival_times": arrival_times,
        "waiting_times": waiting_times,
        "service_start_times": service_start_times,
        "departure_times": departure_times,
    }

def calculate_route_schedule(
    route,
    depot_id=DEPOT_ID,
):
    normalized_route = check_duplicate_customers_in_route(
        route,
        depot_id,
    )

    return _calculate_route_schedule_from_normalized(
        normalized_route,
        depot_id,
    )

def calculate_route_arrival_times(
    route,
    depot_id=DEPOT_ID,
):
    return calculate_route_schedule(
        route,
        depot_id,
    )["arrival_times"]

def calculate_route_waiting_times(
    route,
    depot_id=DEPOT_ID,
):
    return calculate_route_schedule(
        route,
        depot_id,
    )["waiting_times"]

def calculate_route_service_start_times(
    route,
    depot_id=DEPOT_ID,
):
    return calculate_route_schedule(
        route,
        depot_id,
    )["service_start_times"]

def calculate_route_departure_times(
    route,
    depot_id=DEPOT_ID,
):
    return calculate_route_schedule(
        route,
        depot_id,
    )["departure_times"]

def _build_time_window_results(
    normalized_route,
    service_start_times,
):
    time_window_results = []

    for node_id, service_start_time in zip(
        normalized_route,
        service_start_times,
    ):
        node_index = node_id_to_index[node_id]

        ready_time = float(
            ready_times[node_index]
        )

        due_time = float(
            due_dates[node_index]
        )

        time_window_results.append(
            {
                "node_id": node_id,
                "service_start_time": float(
                    service_start_time
                ),
                "ready_time": ready_time,
                "due_time": due_time,
                "is_time_window_feasible": bool(
                    ready_time
                    <= service_start_time
                    <= due_time
                ),
            }
        )

    return time_window_results

def _build_depot_return_result(
    return_time,
    depot_id,
):
    depot_index = node_id_to_index[depot_id]
    depot_due_time = float(
        due_dates[depot_index]
    )

    return {
        "return_time": float(return_time),
        "depot_due_time": depot_due_time,
        "overtime": float(
            max(0.0, return_time - depot_due_time)
        ),
        "is_depot_return_feasible": bool(
            return_time <= depot_due_time
        ),
    }

def check_route_time_windows(
    route,
    depot_id=DEPOT_ID,
):
    normalized_route = check_duplicate_customers_in_route(
        route,
        depot_id,
    )

    schedule = _calculate_route_schedule_from_normalized(
        normalized_route,
        depot_id,
    )

    return _build_time_window_results(
        normalized_route,
        schedule["service_start_times"],
    )

def check_depot_return_time(
    route,
    depot_id=DEPOT_ID,
):
    normalized_route = check_duplicate_customers_in_route(
        route,
        depot_id,
    )

    schedule = _calculate_route_schedule_from_normalized(
        normalized_route,
        depot_id,
    )

    return _build_depot_return_result(
        schedule["arrival_times"][-1],
        depot_id,
    )

def evaluate_route(
    route,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    normalized_route = check_duplicate_customers_in_route(
        route,
        depot_id,
    )

    route_load = _calculate_route_load_from_normalized(
        normalized_route,
        depot_id,
    )

    capacity_result = _build_capacity_result(
        route_load,
        vehicle_capacity,
    )

    route_distance = (
        _calculate_route_distance_from_normalized(
            normalized_route
        )
    )

    schedule = _calculate_route_schedule_from_normalized(
        normalized_route,
        depot_id,
    )

    time_window_results = _build_time_window_results(
        normalized_route,
        schedule["service_start_times"],
    )

    depot_return_result = _build_depot_return_result(
        schedule["arrival_times"][-1],
        depot_id,
    )

    customer_time_windows_feasible = all(
        result["is_time_window_feasible"]
        for result in time_window_results[1:-1]
    )

    is_route_feasible = bool(
        capacity_result["is_capacity_feasible"]
        and customer_time_windows_feasible
        and depot_return_result[
            "is_depot_return_feasible"
        ]
    )

    return {
        "route": normalized_route,
        "route_distance": route_distance,
        "capacity": capacity_result,
        "arrival_times": schedule["arrival_times"],
        "waiting_times": schedule["waiting_times"],
        "service_start_times": schedule[
            "service_start_times"
        ],
        "departure_times": schedule[
            "departure_times"
        ],
        "time_windows": time_window_results,
        "depot_return": depot_return_result,
        "is_route_feasible": is_route_feasible,
    }

def normalize_solution(
    solution,
    depot_id=DEPOT_ID,
):
    return [
        normalize_route(route, depot_id)
        for route in solution
    ]

def validate_solution_routes(
    solution,
    depot_id=DEPOT_ID,
):
    normalized_solution = normalize_solution(
        solution,
        depot_id,
    )

    return [
        validate_route_structure(route, depot_id)
        for route in normalized_solution
    ]

def get_served_customers(
    solution,
    depot_id=DEPOT_ID,
):
    validated_solution = validate_solution_routes(
        solution,
        depot_id,
    )

    return [
        node_id
        for route in validated_solution
        for node_id in route
        if node_id != depot_id
    ]

def check_duplicate_customers_in_solution(
    solution,
    depot_id=DEPOT_ID,
):
    customer_counts = Counter(
        get_served_customers(
            solution,
            depot_id,
        )
    )

    duplicate_customers = sorted(
        customer_id
        for customer_id, count in customer_counts.items()
        if count > 1
    )

    return {
        "duplicate_customers": duplicate_customers,
        "duplicate_count": len(duplicate_customers),
        "has_duplicates": bool(duplicate_customers),
    }

def check_missing_customers(
    solution,
    depot_id=DEPOT_ID,
):
    served_customers = set(
        get_served_customers(
            solution,
            depot_id,
        )
    )

    expected_customers = {
        int(node_id)
        for node_id in node_ids
        if int(node_id) != depot_id
    }

    missing_customers = sorted(
        expected_customers - served_customers
    )

    return {
        "missing_customers": missing_customers,
        "missing_count": len(missing_customers),
        "has_missing_customers": bool(missing_customers),
    }

def get_active_routes(
    solution,
    depot_id=DEPOT_ID,
):
    normalized_solution = normalize_solution(
        solution,
        depot_id,
    )

    active_routes = []
    empty_routes = []

    for route in normalized_solution:
        if any(
            node_id != depot_id
            for node_id in route
        ):
            active_routes.append(route)
        else:
            empty_routes.append(route)

    return {
        "active_routes": active_routes,
        "empty_routes": empty_routes,
        "active_route_count": len(active_routes),
        "empty_route_count": len(empty_routes),
    }

def count_used_vehicles(
    solution,
    depot_id=DEPOT_ID,
):
    route_usage = get_active_routes(
        solution,
        depot_id,
    )

    used_vehicle_count = route_usage[
        "active_route_count"
    ]

    return {
        "used_vehicle_count": used_vehicle_count,
        "available_vehicle_count": int(vehicle_count),
        "remaining_vehicle_count": int(
            vehicle_count - used_vehicle_count
        ),
        "is_fleet_limit_feasible": bool(
            used_vehicle_count <= vehicle_count
        ),
    }

def calculate_solution_distance(
    solution,
    depot_id=DEPOT_ID,
):
    active_routes = get_active_routes(
        solution,
        depot_id,
    )["active_routes"]

    route_distances = [
        calculate_route_distance(
            route,
            depot_id,
        )
        for route in active_routes
    ]

    return {
        "route_distances": route_distances,
        "total_distance": float(
            sum(route_distances)
        ),
    }

def evaluate_solution_routes(
    solution,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    active_routes = get_active_routes(
        solution,
        depot_id,
    )["active_routes"]

    route_evaluations = [
        evaluate_route(
            route,
            vehicle_capacity,
            depot_id,
        )
        for route in active_routes
    ]

    feasible_route_count = sum(
        evaluation["is_route_feasible"]
        for evaluation in route_evaluations
    )

    infeasible_route_count = (
        len(route_evaluations)
        - feasible_route_count
    )

    return {
        "route_evaluations": route_evaluations,
        "feasible_route_count": feasible_route_count,
        "infeasible_route_count": infeasible_route_count,
        "all_routes_feasible": bool(
            infeasible_route_count == 0
        ),
    }

def calculate_solution_objective(
    solution,
    depot_id=DEPOT_ID,
):
    vehicle_usage = count_used_vehicles(
        solution,
        depot_id,
    )

    distance_result = calculate_solution_distance(
        solution,
        depot_id,
    )

    return (
        vehicle_usage["used_vehicle_count"],
        distance_result["total_distance"],
    )

def evaluate_solution(
    solution,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    normalized_solution = validate_solution_routes(
        solution,
        depot_id,
    )

    served_customers = [
        node_id
        for route in normalized_solution
        for node_id in route
        if node_id != depot_id
    ]

    customer_counts = Counter(served_customers)

    duplicate_customers = sorted(
        customer_id
        for customer_id, count in customer_counts.items()
        if count > 1
    )

    duplicate_result = {
        "duplicate_customers": duplicate_customers,
        "duplicate_count": len(duplicate_customers),
        "has_duplicates": bool(duplicate_customers),
    }

    expected_customers = {
        int(node_id)
        for node_id in node_ids
        if int(node_id) != depot_id
    }

    missing_customers = sorted(
        expected_customers - set(served_customers)
    )

    missing_result = {
        "missing_customers": missing_customers,
        "missing_count": len(missing_customers),
        "has_missing_customers": bool(missing_customers),
    }

    active_routes = [
        route
        for route in normalized_solution
        if any(
            node_id != depot_id
            for node_id in route
        )
    ]

    used_vehicle_count = len(active_routes)

    vehicle_usage_result = {
        "used_vehicle_count": used_vehicle_count,
        "available_vehicle_count": int(vehicle_count),
        "remaining_vehicle_count": int(
            vehicle_count - used_vehicle_count
        ),
        "is_fleet_limit_feasible": bool(
            used_vehicle_count <= vehicle_count
        ),
    }

    route_evaluations = [
        evaluate_route(
            route,
            vehicle_capacity,
            depot_id,
        )
        for route in active_routes
    ]

    feasible_route_count = sum(
        evaluation["is_route_feasible"]
        for evaluation in route_evaluations
    )

    infeasible_route_count = (
        len(route_evaluations)
        - feasible_route_count
    )

    route_result = {
        "route_evaluations": route_evaluations,
        "feasible_route_count": feasible_route_count,
        "infeasible_route_count": infeasible_route_count,
        "all_routes_feasible": bool(
            infeasible_route_count == 0
        ),
    }

    route_distances = [
        evaluation["route_distance"]
        for evaluation in route_evaluations
    ]

    total_distance = float(
        sum(route_distances)
    )

    distance_result = {
        "route_distances": route_distances,
        "total_distance": total_distance,
    }

    objective = (
        used_vehicle_count,
        total_distance,
    )

    is_solution_feasible = bool(
        not duplicate_result["has_duplicates"]
        and not missing_result["has_missing_customers"]
        and vehicle_usage_result[
            "is_fleet_limit_feasible"
        ]
        and route_result["all_routes_feasible"]
    )

    return {
        "solution": normalized_solution,
        "duplicate_check": duplicate_result,
        "missing_check": missing_result,
        "vehicle_usage": vehicle_usage_result,
        "distance": distance_result,
        "route_evaluations": route_result,
        "objective": objective,
        "is_solution_feasible": is_solution_feasible,
    }

def get_customers_by_ready_time(
    depot_id=DEPOT_ID,
):
    return sorted(
        (
            int(node_id)
            for node_id in node_ids
            if int(node_id) != depot_id
        ),
        key=lambda node_id: (
            ready_times[node_id_to_index[node_id]],
            due_dates[node_id_to_index[node_id]],
            node_id,
        ),
    )

def create_single_customer_route(
    customer_id,
    depot_id=DEPOT_ID,
):
    customer_id = int(customer_id)

    if customer_id == depot_id:
        raise ValueError(
            "Customer ID cannot be the depot ID."
        )

    if customer_id not in node_id_to_index:
        raise ValueError(
            f"Unknown customer ID: {customer_id}"
        )

    return [
        depot_id,
        customer_id,
        depot_id,
    ]

def find_best_feasible_insertion(
    route,
    customer_id,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    customer_id = int(customer_id)

    if customer_id == depot_id:
        raise ValueError(
            "Customer ID cannot be the depot ID."
        )

    if customer_id not in node_id_to_index:
        raise ValueError(
            f"Unknown customer ID: {customer_id}"
        )

    normalized_route = (
        check_duplicate_customers_in_route(
            route,
            depot_id,
        )
    )

    if customer_id in normalized_route:
        return None

    best_insertion = None
    best_key = None

    for position in range(
        1,
        len(normalized_route),
    ):
        previous_node = normalized_route[
            position - 1
        ]

        next_node = normalized_route[position]

        distance_increase = (
            get_distance(
                previous_node,
                customer_id,
            )
            + get_distance(
                customer_id,
                next_node,
            )
            - get_distance(
                previous_node,
                next_node,
            )
        )

        candidate_route = (
            normalized_route[:position]
            + [customer_id]
            + normalized_route[position:]
        )

        candidate_evaluation = evaluate_route(
            candidate_route,
            vehicle_capacity,
            depot_id,
        )

        if not candidate_evaluation[
            "is_route_feasible"
        ]:
            continue

        candidate_key = (
            distance_increase,
            position,
        )

        if (
            best_key is None
            or candidate_key < best_key
        ):
            best_key = candidate_key

            best_insertion = {
                "route": candidate_route,
                "position": position,
                "distance_increase": float(
                    distance_increase
                ),
            }

    return best_insertion

def find_best_solution_insertion(
    solution,
    customer_id,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    customer_id = int(customer_id)

    normalized_solution = (
        validate_solution_routes(
            solution,
            depot_id,
        )
    )

    best_insertion = None
    best_key = None

    for route_index, route in enumerate(
        normalized_solution
    ):
        has_customer = any(
            node_id != depot_id
            for node_id in route
        )

        if not has_customer:
            continue

        insertion = find_best_feasible_insertion(
            route,
            customer_id,
            vehicle_capacity,
            depot_id,
        )

        if insertion is None:
            continue

        candidate_key = (
            insertion["distance_increase"],
            route_index,
            insertion["position"],
        )

        if (
            best_key is None
            or candidate_key < best_key
        ):
            best_key = candidate_key

            best_insertion = {
                "route_index": route_index,
                "route": insertion["route"],
                "position": insertion["position"],
                "distance_increase": insertion[
                    "distance_increase"
                ],
            }

    return best_insertion

def insert_customer_or_open_route(
    solution,
    customer_id,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    customer_id = int(customer_id)

    if customer_id == depot_id:
        raise ValueError(
            "Customer ID cannot be the depot ID."
        )

    if customer_id not in node_id_to_index:
        raise ValueError(
            f"Unknown customer ID: {customer_id}"
        )

    updated_solution = validate_solution_routes(
        solution,
        depot_id,
    )

    served_customers = {
        node_id
        for route in updated_solution
        for node_id in route
        if node_id != depot_id
    }

    if customer_id in served_customers:
        raise ValueError(
            f"Customer {customer_id} is already served."
        )

    best_insertion = (
        find_best_solution_insertion(
            updated_solution,
            customer_id,
            vehicle_capacity,
            depot_id,
        )
    )

    if best_insertion is not None:
        updated_solution[
            best_insertion["route_index"]
        ] = best_insertion["route"]

        action = "inserted"

    else:
        new_route = create_single_customer_route(
            customer_id,
            depot_id,
        )

        new_route_evaluation = evaluate_route(
            new_route,
            vehicle_capacity,
            depot_id,
        )

        if not new_route_evaluation[
            "is_route_feasible"
        ]:
            raise ValueError(
                f"Customer {customer_id} cannot form "
                "a feasible single-customer route."
            )

        updated_solution.append(new_route)
        action = "new_route"

    return updated_solution, action

def build_initial_solution(
    customer_order,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    ordered_customers = [
        int(customer_id)
        for customer_id in customer_order
    ]

    duplicated_customers = sorted(
        customer_id
        for customer_id, count in Counter(
            ordered_customers
        ).items()
        if count > 1
    )

    if duplicated_customers:
        raise ValueError(
            "Duplicate customers in construction order: "
            f"{duplicated_customers}"
        )

    if depot_id in ordered_customers:
        raise ValueError(
            "The depot cannot appear in the "
            "customer construction order."
        )

    unknown_customers = sorted(
        customer_id
        for customer_id in ordered_customers
        if customer_id not in node_id_to_index
    )

    if unknown_customers:
        raise ValueError(
            "Unknown customers in construction order: "
            f"{unknown_customers}"
        )

    solution = []
    insertion_count = 0
    new_route_count = 0

    for customer_id in ordered_customers:
        solution, action = (
            insert_customer_or_open_route(
                solution,
                customer_id,
                vehicle_capacity,
                depot_id,
            )
        )

        if action == "inserted":
            insertion_count += 1

        else:
            new_route_count += 1

            if len(solution) > vehicle_count:
                raise ValueError(
                    "Vehicle limit exceeded during "
                    "initial solution construction."
                )

    return {
        "solution": solution,
        "insertion_count": insertion_count,
        "new_route_count": new_route_count,
    }

def _prepare_destroy_input(
    solution,
    removal_count,
    depot_id=DEPOT_ID,
):
    removal_count = int(removal_count)

    if removal_count < 0:
        raise ValueError(
            "Removal count cannot be negative."
        )

    normalized_solution = validate_solution_routes(
        solution,
        depot_id,
    )

    active_routes = [
        list(route)
        for route in normalized_solution
        if any(
            node_id != depot_id
            for node_id in route
        )
    ]

    served_customers = [
        node_id
        for route in active_routes
        for node_id in route
        if node_id != depot_id
    ]

    if len(served_customers) != len(set(served_customers)):
        raise ValueError(
            "Destroy operators require a solution "
            "without duplicate customers."
        )

    effective_removal_count = min(
        removal_count,
        len(served_customers),
    )

    return (
        active_routes,
        served_customers,
        effective_removal_count,
    )

def _remove_customers_from_routes(
    routes,
    removed_customers,
    depot_id=DEPOT_ID,
):
    removed_customer_set = {
        int(customer_id)
        for customer_id in removed_customers
    }

    remaining_routes = []

    for route in routes:
        updated_route = [
            node_id
            for node_id in route
            if (
                node_id == depot_id
                or node_id not in removed_customer_set
            )
        ]

        if any(
            node_id != depot_id
            for node_id in updated_route
        ):
            remaining_routes.append(updated_route)

    return remaining_routes

def random_destroy(
    solution,
    removal_count,
    depot_id=DEPOT_ID,
):
    (
        active_routes,
        served_customers,
        removal_count,
    ) = _prepare_destroy_input(
        solution,
        removal_count,
        depot_id,
    )

    if removal_count == 0:
        return active_routes, []

    removed_customers = random.sample(
        served_customers,
        removal_count,
    )

    destroyed_solution = _remove_customers_from_routes(
        active_routes,
        removed_customers,
        depot_id,
    )

    return destroyed_solution, removed_customers

def worst_distance_destroy(
    solution,
    removal_count,
    depot_id=DEPOT_ID,
):
    (
        active_routes,
        _,
        removal_count,
    ) = _prepare_destroy_input(
        solution,
        removal_count,
        depot_id,
    )

    if removal_count == 0:
        return active_routes, []

    removal_candidates = []

    for route_index, route in enumerate(active_routes):
        for position in range(1, len(route) - 1):
            previous_node = route[position - 1]
            customer_id = route[position]
            next_node = route[position + 1]

            distance_saving = (
                get_distance(
                    previous_node,
                    customer_id,
                )
                + get_distance(
                    customer_id,
                    next_node,
                )
                - get_distance(
                    previous_node,
                    next_node,
                )
            )

            removal_candidates.append(
                {
                    "customer_id": customer_id,
                    "route_index": route_index,
                    "position": position,
                    "distance_saving": float(
                        distance_saving
                    ),
                }
            )

    removal_candidates.sort(
        key=lambda candidate: (
            -candidate["distance_saving"],
            candidate["route_index"],
            candidate["position"],
            candidate["customer_id"],
        )
    )

    removed_customers = [
        candidate["customer_id"]
        for candidate in removal_candidates[
            :removal_count
        ]
    ]

    destroyed_solution = _remove_customers_from_routes(
        active_routes,
        removed_customers,
        depot_id,
    )

    return destroyed_solution, removed_customers

def shaw_destroy(
    solution,
    removal_count,
    depot_id=DEPOT_ID,
    distance_weight=1.0,
    time_weight=1.0,
    demand_weight=1.0,
    route_weight=1.0,
):
    (
        active_routes,
        served_customers,
        removal_count,
    ) = _prepare_destroy_input(
        solution,
        removal_count,
        depot_id,
    )

    if removal_count == 0:
        return active_routes, []

    customer_route = {
        customer_id: route_index
        for route_index, route in enumerate(
            active_routes
        )
        for customer_id in route
        if customer_id != depot_id
    }

    distance_scale = max(
        float(distance_matrix.max()),
        np.finfo(float).eps,
    )

    ready_time_scale = max(
        float(
            ready_times.max()
            - ready_times.min()
        ),
        np.finfo(float).eps,
    )

    demand_scale = max(
        float(vehicle_capacity),
        np.finfo(float).eps,
    )

    seed_customer = random.choice(
        served_customers
    )

    removed_customers = [seed_customer]

    remaining_customers = set(
        served_customers
    )

    remaining_customers.remove(
        seed_customer
    )

    while len(removed_customers) < removal_count:
        reference_customer = random.choice(
            removed_customers
        )

        reference_index = node_id_to_index[
            reference_customer
        ]

        def relatedness(customer_id):
            customer_index = node_id_to_index[
                customer_id
            ]

            normalized_distance = (
                get_distance(
                    reference_customer,
                    customer_id,
                )
                / distance_scale
            )

            normalized_time_difference = (
                abs(
                    ready_times[reference_index]
                    - ready_times[customer_index]
                )
                / ready_time_scale
            )

            normalized_demand_difference = (
                abs(
                    demands[reference_index]
                    - demands[customer_index]
                )
                / demand_scale
            )

            different_route = float(
                customer_route[reference_customer]
                != customer_route[customer_id]
            )

            return (
                distance_weight
                * normalized_distance
                + time_weight
                * normalized_time_difference
                + demand_weight
                * normalized_demand_difference
                + route_weight
                * different_route
            )

        selected_customer = min(
            remaining_customers,
            key=lambda customer_id: (
                relatedness(customer_id),
                customer_id,
            ),
        )

        removed_customers.append(
            selected_customer
        )

        remaining_customers.remove(
            selected_customer
        )

    destroyed_solution = _remove_customers_from_routes(
        active_routes,
        removed_customers,
        depot_id,
    )

    return destroyed_solution, removed_customers

def route_destroy(
    solution,
    removal_count,
    depot_id=DEPOT_ID,
):
    (
        active_routes,
        _,
        removal_count,
    ) = _prepare_destroy_input(
        solution,
        removal_count,
        depot_id,
    )

    if removal_count == 0:
        return active_routes, []

    shuffled_route_indices = list(
        range(len(active_routes))
    )

    random.shuffle(
        shuffled_route_indices
    )

    selected_route_indices = set()
    removed_customers = []

    for route_index in shuffled_route_indices:
        route_customers = [
            node_id
            for node_id in active_routes[
                route_index
            ]
            if node_id != depot_id
        ]

        selected_route_indices.add(
            route_index
        )

        removed_customers.extend(
            route_customers
        )

        if len(removed_customers) >= removal_count:
            break

    destroyed_solution = [
        route
        for route_index, route in enumerate(
            active_routes
        )
        if route_index not in selected_route_indices
    ]

    return destroyed_solution, removed_customers

DESTROY_OPERATORS = {
    "random": random_destroy,
    "worst_distance": worst_distance_destroy,
    "shaw": shaw_destroy,
    "route": route_destroy,
}

def apply_destroy_operator(
    solution,
    removal_count,
    operator_name=None,
    depot_id=DEPOT_ID,
):
    if operator_name is None:
        operator_name = random.choice(
            tuple(DESTROY_OPERATORS)
        )

    if operator_name not in DESTROY_OPERATORS:
        raise ValueError(
            f"Unknown destroy operator: {operator_name}"
        )

    destroy_operator = DESTROY_OPERATORS[
        operator_name
    ]

    destroyed_solution, removed_customers = (
        destroy_operator(
            solution,
            removal_count,
            depot_id,
        )
    )

    return {
        "operator_name": operator_name,
        "destroyed_solution": destroyed_solution,
        "removed_customers": removed_customers,
    }

def _prepare_repair_input(
    destroyed_solution,
    removed_customers,
    depot_id=DEPOT_ID,
):
    repaired_solution = [
        list(route)
        for route in validate_solution_routes(
            destroyed_solution,
            depot_id,
        )
    ]

    removed_customers = [
        int(customer_id)
        for customer_id in removed_customers
    ]

    duplicate_customers = sorted(
        customer_id
        for customer_id, count in Counter(
            removed_customers
        ).items()
        if count > 1
    )

    if duplicate_customers:
        raise ValueError(
            "Duplicate customers in the repair list: "
            f"{duplicate_customers}"
        )

    if depot_id in removed_customers:
        raise ValueError(
            "The depot cannot appear in the repair list."
        )

    unknown_customers = sorted(
        customer_id
        for customer_id in removed_customers
        if customer_id not in node_id_to_index
    )

    if unknown_customers:
        raise ValueError(
            "Unknown customers in the repair list: "
            f"{unknown_customers}"
        )

    served_customers = {
        node_id
        for route in repaired_solution
        for node_id in route
        if node_id != depot_id
    }

    already_served_customers = sorted(
        served_customers.intersection(
            removed_customers
        )
    )

    if already_served_customers:
        raise ValueError(
            "Repair customers are already present in the "
            "destroyed solution: "
            f"{already_served_customers}"
        )

    return repaired_solution, removed_customers

def greedy_repair(
    destroyed_solution,
    removed_customers,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    repaired_solution, removed_customers = (
        _prepare_repair_input(
            destroyed_solution,
            removed_customers,
            depot_id,
        )
    )

    customer_order = sorted(
        removed_customers,
        key=lambda customer_id: (
            due_dates[
                node_id_to_index[customer_id]
            ],
            ready_times[
                node_id_to_index[customer_id]
            ],
            customer_id,
        ),
    )

    for customer_id in customer_order:
        repaired_solution, _ = (
            insert_customer_or_open_route(
                repaired_solution,
                customer_id,
                vehicle_capacity,
                depot_id,
            )
        )

    return repaired_solution

def regret_2_repair(
    destroyed_solution,
    removed_customers,
    vehicle_capacity,
    depot_id=DEPOT_ID,
):
    repaired_solution, removed_customers = (
        _prepare_repair_input(
            destroyed_solution,
            removed_customers,
            depot_id,
        )
    )

    unassigned_customers = set(
        removed_customers
    )

    while unassigned_customers:
        selected_customer = None
        selected_insertion = None
        highest_regret = -float("inf")

        for customer_id in sorted(
            unassigned_customers
        ):
            insertion_options = []

            for route_index, route in enumerate(
                repaired_solution
            ):
                insertion = (
                    find_best_feasible_insertion(
                        route,
                        customer_id,
                        vehicle_capacity,
                        depot_id,
                    )
                )

                if insertion is None:
                    continue

                insertion_options.append(
                    {
                        "route_index": route_index,
                        **insertion,
                    }
                )

            insertion_options.sort(
                key=lambda option: (
                    option["distance_increase"],
                    option["route_index"],
                    option["position"],
                )
            )

            if not insertion_options:
                regret_value = float("inf")
                best_insertion = None

            elif len(insertion_options) == 1:
                regret_value = float("inf")
                best_insertion = insertion_options[0]

            else:
                regret_value = (
                    insertion_options[1][
                        "distance_increase"
                    ]
                    - insertion_options[0][
                        "distance_increase"
                    ]
                )

                best_insertion = insertion_options[0]

            if regret_value > highest_regret:
                highest_regret = regret_value
                selected_customer = customer_id
                selected_insertion = best_insertion

        if selected_insertion is None:
            new_route = create_single_customer_route(
                selected_customer,
                depot_id,
            )

            new_route_evaluation = evaluate_route(
                new_route,
                vehicle_capacity,
                depot_id,
            )

            if not new_route_evaluation[
                "is_route_feasible"
            ]:
                raise ValueError(
                    f"Customer {selected_customer} "
                    "cannot be repaired."
                )

            repaired_solution.append(new_route)

        else:
            route_index = selected_insertion[
                "route_index"
            ]

            repaired_solution[route_index] = (
                selected_insertion["route"]
            )

        unassigned_customers.remove(
            selected_customer
        )

    return repaired_solution

REPAIR_OPERATORS = {
    "greedy": greedy_repair,
    "regret_2": regret_2_repair,
}

def apply_repair_operator(
    destroyed_solution,
    removed_customers,
    vehicle_capacity,
    operator_name=None,
    depot_id=DEPOT_ID,
):
    if operator_name is None:
        operator_name = random.choice(
            tuple(REPAIR_OPERATORS)
        )

    if operator_name not in REPAIR_OPERATORS:
        raise ValueError(
            f"Unknown repair operator: {operator_name}"
        )

    repair_operator = REPAIR_OPERATORS[
        operator_name
    ]

    repaired_solution = repair_operator(
        destroyed_solution,
        removed_customers,
        vehicle_capacity,
        depot_id,
    )

    return {
        "operator_name": operator_name,
        "repaired_solution": repaired_solution,
    }

def accept_improving_candidate(
    current_evaluation,
    candidate_evaluation,
):
    if not candidate_evaluation["is_solution_feasible"]:
        return False

    return (
        candidate_evaluation["objective"]
        < current_evaluation["objective"]
    )

def accept_candidate(
    current_evaluation,
    candidate_evaluation,
    temperature,
):
    temperature = float(temperature)

    if temperature <= 0:
        raise ValueError(
            "Temperature must be greater than zero."
        )

    if not candidate_evaluation["is_solution_feasible"]:
        return False

    if accept_improving_candidate(
        current_evaluation,
        candidate_evaluation,
    ):
        return True

    current_vehicles, current_distance = (
        current_evaluation["objective"]
    )

    candidate_vehicles, candidate_distance = (
        candidate_evaluation["objective"]
    )

    if candidate_vehicles > current_vehicles:
        return False

    distance_increase = (
        candidate_distance - current_distance
    )

    acceptance_probability = math.exp(
        -distance_increase / temperature
    )

    return (
        random.random()
        < acceptance_probability
    )

def run_lns(
    initial_solution,
    vehicle_capacity,
    iterations,
    removal_count,
    initial_temperature,
    cooling_rate,
    min_temperature,
    progress_interval=10,
    depot_id=DEPOT_ID,
):
    iterations = int(iterations)
    removal_count = int(removal_count)
    progress_interval = int(progress_interval)

    initial_temperature = float(
        initial_temperature
    )

    cooling_rate = float(cooling_rate)
    min_temperature = float(min_temperature)

    if iterations <= 0:
        raise ValueError(
            "Iterations must be greater than zero."
        )

    if removal_count < 0:
        raise ValueError(
            "Removal count cannot be negative."
        )

    if initial_temperature <= 0:
        raise ValueError(
            "Initial temperature must be greater than zero."
        )

    if min_temperature <= 0:
        raise ValueError(
            "Minimum temperature must be greater than zero."
        )

    if min_temperature > initial_temperature:
        raise ValueError(
            "Minimum temperature cannot exceed "
            "the initial temperature."
        )

    if not 0 < cooling_rate <= 1:
        raise ValueError(
            "Cooling rate must be in the interval (0, 1]."
        )

    if progress_interval <= 0:
        raise ValueError(
            "Progress interval must be greater than zero."
        )

    current_solution = [
        list(route)
        for route in initial_solution
    ]

    current_evaluation = evaluate_solution(
        current_solution,
        vehicle_capacity,
        depot_id,
    )

    if not current_evaluation["is_solution_feasible"]:
        raise ValueError(
            "The initial solution must be feasible."
        )

    best_solution = [
        list(route)
        for route in current_solution
    ]

    best_evaluation = current_evaluation

    temperature = initial_temperature
    iteration_log = []

    search_start_time = time.perf_counter()

    print("LNS search started.")
    print(
        f"Initial objective: "
        f"{current_evaluation['objective']}"
    )
    print(
        f"Iterations: {iterations} | "
        f"Removal count: {removal_count}"
    )

    for iteration in range(1, iterations + 1):
        destroy_result = apply_destroy_operator(
            current_solution,
            removal_count,
            depot_id=depot_id,
        )

        repair_result = apply_repair_operator(
            destroy_result["destroyed_solution"],
            destroy_result["removed_customers"],
            vehicle_capacity,
            depot_id=depot_id,
        )

        candidate_solution = repair_result[
            "repaired_solution"
        ]

        candidate_evaluation = evaluate_solution(
            candidate_solution,
            vehicle_capacity,
            depot_id,
        )

        accepted = accept_candidate(
            current_evaluation,
            candidate_evaluation,
            temperature,
        )

        if accepted:
            current_solution = [
                list(route)
                for route in candidate_solution
            ]

            current_evaluation = (
                candidate_evaluation
            )

        improved_best = bool(
            candidate_evaluation[
                "is_solution_feasible"
            ]
            and candidate_evaluation["objective"]
            < best_evaluation["objective"]
        )

        if improved_best:
            best_solution = [
                list(route)
                for route in candidate_solution
            ]

            best_evaluation = candidate_evaluation

        iteration_log.append(
            {
                "iteration": iteration,
                "destroy_operator": destroy_result[
                    "operator_name"
                ],
                "repair_operator": repair_result[
                    "operator_name"
                ],
                "removed_count": len(
                    destroy_result[
                        "removed_customers"
                    ]
                ),
                "candidate_objective": (
                    candidate_evaluation["objective"]
                ),
                "current_objective": (
                    current_evaluation["objective"]
                ),
                "best_objective": (
                    best_evaluation["objective"]
                ),
                "candidate_feasible": (
                    candidate_evaluation[
                        "is_solution_feasible"
                    ]
                ),
                "accepted": accepted,
                "improved_best": improved_best,
                "temperature": temperature,
            }
        )

        should_report = bool(
            iteration == 1
            or iteration == iterations
            or iteration % progress_interval == 0
            or improved_best
        )

        if should_report:
            if improved_best:
                status = "new_best"
            elif accepted:
                status = "accepted"
            else:
                status = "rejected"

            print(
                f"Iteration {iteration}/{iterations} | "
                f"current={current_evaluation['objective']} | "
                f"best={best_evaluation['objective']} | "
                f"destroy={destroy_result['operator_name']} | "
                f"repair={repair_result['operator_name']} | "
                f"status={status} | "
                f"temperature={temperature:.4f}"
            )

        temperature = max(
            min_temperature,
            temperature * cooling_rate,
        )

    elapsed_seconds = (
        time.perf_counter() - search_start_time
    )

    return {
        "best_solution": best_solution,
        "best_evaluation": best_evaluation,
        "current_solution": current_solution,
        "current_evaluation": current_evaluation,
        "iteration_log": iteration_log,
        "elapsed_seconds": float(
            elapsed_seconds
        ),
    }
