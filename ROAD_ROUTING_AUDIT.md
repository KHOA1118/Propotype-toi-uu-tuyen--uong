# Road geometry correction and LNS cost audit

## Audit before changes

1. `frontend/map-data.js::demoScenario` selected existing OSM node IDs and assigned delivery IDs 0–10. `toRequest` projected their geographic coordinates to local Cartesian meters.
2. There was no nearest-node snapping for arbitrary customer locations. Default coordinates were already those of chosen OSM nodes.
3. `frontend/app.js::renderMap` built a polyline from the LNS stop IDs and their projected coordinates.
4. Yes: those were straight stop-to-stop segments; no road path search occurred.
5. LNS used Euclidean distance, not OSM distance.
6. The normalized graph is directed. Two-way roads have separate forward/reverse edges; one-way roads retain their permitted direction.
7. Every normalized edge has `distance` in meters. `travel_time` is seconds or null; the full dataset has 3,572 estimated-time edges and 24,991 unknown-time edges. These times derive from speed limits, not measured traffic. `status` is also retained; it is not a numeric routing weight.

## Implemented flow

`POST /api/optimize → existing LNS → stop sequences → POST /api/network/routes → RoadRouter → directed Dijkstra paths → frontend polylines`

The routing request contains `stops: [{id, lat, lon}]`, `routes` and optional `initial_routes`. Every supplied location is snapped by minimum haversine distance to a node incident to an eligible road edge. The original lat/lon remain unchanged. The response stores `snapped_stops: [{id, lat, lon, nearest_osm_node_id, snapped_lat, snapped_lon, snap_distance_m}]`.

Each geometry contains the original `stop_sequence`, ordered OSM `node_ids`, exact directed `edge_ids`, leg boundaries, `[longitude, latitude]` coordinates, road `distance_m` and selected `cost`. Source SHA256 ties the geometry to the loaded map. The frontend draws only this returned geometry; it does not connect original stop coordinates to the snapped road by artificial segments. Original locations remain the marker positions, and selection shows nearest-node ID and snap offset.

The eligible graph includes conventional motor-road highway classes, preserves edge direction and excludes explicit no/private access, vehicle, motor_vehicle and hgv tags as well as blocked edges. It does not infer connectivity from visual line intersections. Nodes must share actual OSM IDs to connect.

If every eligible edge has a finite positive travel time, Dijkstra uses seconds. Otherwise it uses length consistently across the graph. This dataset uses **distance**. Mixing meters with seconds or favoring only the small time-covered subgraph would give misleading results.

Depot reachability is checked in both directions for every customer before returning geometry. An unreachable location or leg returns HTTP 422 and an explicit error. The frontend clears route overlays on failure; there is no straight-line fallback.

The previous demo's stop 1, OSM `10875088784`, failed this directed reachability test. `/api/network/routing-profile` exposes nodes mutually reachable from a central demo depot so newly generated demo orders are valid. This changes generated demo locations only. Submitted customer coordinates are never moved to a different connected component to conceal failure. The original disconnected scenario remains an automated error regression test.

## LNS matrix audit after geometry correction

`lns/adapter.py::_solve`, lines 167–168, remains unchanged:

```python
distances = np.asarray(dataset['distance_matrix'], dtype=float) if 'distance_matrix' in dataset else np.linalg.norm(coords[:, None, :] - coords[None, :, :], axis=2)
travel = np.asarray(dataset['travel_time_matrix'], dtype=float) if 'travel_time_matrix' in dataset else distances / dataset['travel_speed']
```

The browser still supplies X/Y from original geographic coordinates, with no road matrices. Therefore the LNS objective is still number of used vehicles followed by Euclidean total distance. Its time-window feasibility still uses the existing distance/speed model, not actual road travel time. The UI labels that objective explicitly and separately shows OSM kilometers per route. A geometrically valid road route is not a certification that its road travel times satisfy the LNS time windows.

To change costs later, construct asymmetric all-pairs matrices between snapped stop nodes, in exactly the API `instance.nodes` order, and provide `distance_matrix` in meters and `travel_time_matrix` in seconds. Reject unreachable pairs instead of inventing finite costs. Establish an explicit speed policy for missing times, and use the same path-selection policy for matrices and displayed geometry. If choosing fastest paths, their length matrix should describe those same paths; independently minimizing both matrices can describe different physical trips.

No rewrite of destroy, repair or SA acceptance is intended. Different input matrices will affect insertion costs, route ranking and feasibility. Audit operators with asymmetric matrices and re-test construction, capacity, windows and depot returns. Supplying a time matrix affects time feasibility; minimizing time instead of the existing distance objective would be a separate, explicit model decision.

The authoritative imported engine is `lns/core.py`, extracted from the user's original `base_vrp+lns_(refined).py`; this repository does not contain a file named `LNS.py`. Neither engine nor adapter was edited for this task. Engine SHA256 remains `2504b679c60089bbf87d1f6d55717bd0d3804c90e104872d143aba5396134fed`. Original-function equivalence tests pass.

## Validation and limits

- Python suite: **46/46 passed**.
- Node/live API suite: **7/7 passed**. Checks every returned edge and coordinate against the complete real normalized dataset for both initial and final solutions.
- Tests cover coordinate preservation, snapping, one-way detours, disconnected returns, coincident stops, parallel edges, access filtering, invalid IDs/coordinates, consistent time-weight selection and real LNS integration.
- Browser confirmed road-following polylines. Default final routes contain 607, 305 and 566 OSM nodes, with road lengths approximately 21.27, 10.03 and 26.46 km.
- Turn-restriction relations, conditional access, vehicle height/weight/width and approach-side constraints are **not enforced**. Paths are valid in the directed eligible graph; this is not yet a complete legal truck navigator. The UI states this limitation.
- Nearest-node snapping can have a large offset for out-of-coverage input; the offset is reported, with no invented access road. No maximum snap radius is imposed yet.
- The router builds per-request shortest-path trees. This is sufficient for the 11-stop prototype; larger instances need bounded caching and spatial indexing.

Run `python server.py --port 8001`, open `http://127.0.0.1:8001`, click Optimize, compare before/after, and select a customer. Run Python tests with `python -m unittest discover -s tests`. For live Node tests use `LNS_TEST_URL=http://127.0.0.1:8001` in your shell environment, then `node --test tests/test_map_frontend.cjs` (default test URL is port 8002).

Changed: `road_network/routing.py`, `server.py`, `frontend/map-data.js`, `frontend/app.js`, `frontend/index.html`, `tests/test_routing.py`, `tests/test_map_frontend.cjs`, and documentation. Raw/normalized map data and original LNS logic are unchanged. No vehicle animation or incident handling was implemented.
