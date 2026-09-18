# Milestone 6 — Dynamic LNS re-optimization

Implemented through `POST /api/reoptimize`. No changes to `lns/core.py` or
`lns/adapter.py`. The core SHA256 remains
`2504b679c60089bbf87d1f6d55717bd0d3804c90e104872d143aba5396134fed`.

## Flow and state ownership

1. The browser reports an incident to the existing session API.
2. The backend acknowledges a versioned incident overlay. Raw OSM stays unchanged.
3. `Simulation.beginReoptimization()` snapshots each vehicle's original customers,
   served IDs, remaining IDs, physical model clock, and safe switching node.
4. A moving vehicle finishes only the directed edge it has entered. At an edge
   boundary it may switch immediately. Active customer service finishes first.
   Other customers remain eligible for reordering, on their original vehicle.
5. While the HTTP solve is pending, vehicles keep moving. Affected vehicles wait
   at their switching node if they get there first. Unaffected vehicles continue.
6. `road_network/reoptimization.py` creates a request-local directed network with
   incident costs, computes shortest paths, and invokes `lns.adapter.solve_instance`
   separately for each affected vehicle that still has customers.
7. The existing adapter invokes the original `run_lns`, returning `best_solution`.
8. The browser validates the incident revision, simulation identity, customer
   ownership and response horizon, then replaces only untraveled suffixes.
   Earlier edges, delivery service events, positions and clocks are retained.

Network effects live in `IncidentStore`. Client movement lives in `Simulation`.
The server retains latest snapshots in `simulation_progress` and solver outputs
in `optimization_results`, separately from incident/network state. Initial static
LNS results are not mutated by dynamic solves. All server state is in memory;
the browser remains the authoritative movement clock for this single-host demo.

## Cost model and feasibility

Static `/api/optimize` still uses its previous Euclidean defaults. Dynamic solves
explicitly minimize **directed road travel seconds**. Existing positive OSM edge
times are used; missing times are estimated as distance / (30 km/h). Congestion
and accident multiply those times; blocked directed edges are excluded. Reverse
edges are not implicitly blocked. There is no straight-line fallback.

For one vehicle, node 0 is a virtual start/end matrix boundary: outgoing entries
start at its switching road node; incoming entries finish at the real depot.
Both `distance_matrix` (the engine's legacy objective slot) and
`travel_time_matrix` contain seconds. No destroy, repair, acceptance, schedule,
or feasibility function is changed. Customer coordinates, IDs, demand, windows,
service times, capacity and depot deadline retain their supplied values.

The virtual depot ready time is the current physical model clock plus committed
work and a conservative ten-presentation-second solve allowance. Results older
than that allowance are rejected while moving. Playback tracks physical model
seconds separately from accelerated presentation time, honors customer ready
times, and retains service already in progress. The demo's broad windows make
this allowance practical; tight windows can be conservatively rejected.

The old remaining order seeds real LNS if feasible. If it is infeasible, the
original engine's constructive initializer is tried. Construction failure does
not prove mathematical infeasibility: it is reported, not replaced by a fake
solution. A vehicle with only depot return left uses directed shortest-path
routing, explicitly marked `road-return-only`, without claiming an LNS call.

## API contract

Request: `{session_id, revision, scenario, vehicles}`. Scenario uses existing
geographic stops and fleet/options fields. Each vehicle includes `route_index`,
`assigned`, `served`, `remaining`, `anchor`, `anchor_osm_node_id`, `ready_time`,
`committed_edge_ids`, and `suffix_edge_ids`. Anchor `-1` is an internal road
switching node, not a customer; anchor 0 is depot; a positive anchor is an active
service that must finish. Served + active service + remaining partition ownership.

Response: `{revision, updates, failures, completed_lns_solves, elapsed_seconds,
cost_model, objective, engine}`. Each update has the original vehicle index,
new order, actual directed OSM geometry, solver result and per-vehicle metrics.
`metrics.before` and `metrics.after` compare only the replaceable suffix under
the **same current incident costs**. A blocked old path has `before: null` and
`before_available: false`; no invented numeric saving is displayed.

Failures leave that vehicle's existing plan intact; independent feasible vehicle
updates can still apply. An incident on the edge already entered holds that
vehicle if blocked; the system does not teleport it to the edge's far endpoint.

## Verification and manual demo

Start with `python server.py --port 8008`, then open http://127.0.0.1:8008/.
Click **Tối ưu tuyến**, **Bắt đầu**, choose a future road segment and incident,
then **Gửi báo cáo**. Real dynamic LNS runs automatically on the after view.
The dynamic panel shows seconds before/after; JSON includes actual LNS results.
Pause/resume does not reset progress. **Tái tối ưu phần còn lại** retries after
a failure. Reset deliberately starts the currently displayed full plan again,
including its delivered prefix, with incidents still active. Reload clears the
demo session. Reports in the before view do not automatically re-optimize it.

Run all tests:

```powershell
python -m unittest discover -s tests -v
$env:LNS_TEST_URL='http://127.0.0.1:8008'
node --test tests/test_simulation.cjs tests/test_map_frontend.cjs tests/test_dynamic_pipeline.cjs
```

The dynamic scenario test uses the complete real map, six vehicles and 24 stops,
serves customers first, reports an accident then a road blockage with a legal
detour, calls real LNS, checks continuous positions and fixed customer ownership,
checks unchanged unaffected plans, and advances every vehicle back to depot.
Backend tests additionally verify actual changed customer order, matrix/objective
agreement, fixed seeds, blocked/unreachable paths, capacity and time violations,
malformed snapshots, stale versions, and the no-customers return case.

Final verification on 2026-09-17: **55/55 Python tests and 18/18 Node tests passed**.
The real-map scenario performed two successful real LNS solves after customers
had already been served, and all six vehicles completed. A separate browser run
showed vehicle 1's remaining cost changing from 1016.8 to 910.8 seconds and
vehicle 3's from 786.7 to 569.7 seconds after an accident; movement continued and
no JavaScript errors were reported. These are observed run results, not fixed
demo output. The core hash and original-function comparison also passed.

Files changed for this milestone: `server.py`, `frontend/app.js`,
`frontend/simulation.js`, `frontend/index.html`, `README.md`; new files:
`road_network/reoptimization.py`, `tests/test_reoptimization.py`,
`tests/test_dynamic_pipeline.cjs`, and this document. No raw map or LNS engine
file was modified.

## Prototype limits

- No turn-restriction or truck-dimension modeling beyond the existing road access
  filter. Missing travel times are estimates, not live observations.
- Per-vehicle LNS preserves cargo ownership; no inter-vehicle exchanges.
- The finite matrix requires directed reachability for every included pair.
  A disconnected pair is rejected even if a special restricted ordering exists.
- Progress snapshots come from the demo browser, not authenticated GPS or an
  authoritative fleet server. The local HTTP server serializes requests.
- Re-optimization cannot recover a vehicle trapped inside a blocked edge.
- There is no promise of strict improvement: feasible genuine results may retain
  the old order, and some reports affect no remaining work.

Work stops at Milestone 6.
