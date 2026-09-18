# Milestone 7 — Decision dashboard

The Vietnamese dashboard shows OSM distance and estimated driving time before
and after, active / affected / actually rerouted vehicles, remaining customers,
backend optimization runtime, and a qualified feasibility status. The compact
timeline records initial solution, movement, acknowledged incident, solve start,
and applied result, with simulation elapsed times. It keeps the latest eight
events; reset or a newly prepared simulation starts a new timeline.

Initial comparisons sum all initial/final road geometries. Dynamic comparisons
freeze **the entire fleet's remaining road work at request time**, under the same
incident revision. The current edge's untraveled fraction is included. The after
value substitutes only applied suffixes; unaffected and failed routes retain
their original contribution. Comparisons stay frozen while vehicle and customer
counts update live. This avoids comparing full original routes with short
remaining routes, or treating elapsed movement as optimization savings.

Distance is road kilometers, not the original Euclidean objective. Travel time
is summed vehicle driving minutes, not fleet makespan or ETA; waiting and service
are excluded. Missing edge times use the existing 30 km/h estimate. A blocked
path displays “Bị chặn” instead of a fabricated duration or saving.

Active vehicles are assigned routes not yet completed, including paused or
blocked vehicles. Affected vehicles have acknowledged incident edges in their
remaining work at the most recent request. Rerouted vehicles count only applied
results with different edge sequences or customer order; merely invoking LNS
does not increase this count. Remaining customers exclude completed services.
Runtime is backend `total_seconds` initially and `elapsed_seconds` dynamically,
including adapter/routing work. Partial failures never display fleet feasibility.

Reporting is a read-only module in `frontend/dashboard.js`. No changes were made
to LNS, the dynamic optimization adapter, road routing, or simulation logic.
The static Euclidean metrics remain available in a collapsed disclosure.

## Verification

Run `python server.py --port 8009`, open http://127.0.0.1:8009/, optimize, start
vehicles, and report a future-road incident. Watch the dashboard and timeline.
Pause/resume preserves events. Reset clears the previous decision comparison.

```powershell
python -m unittest discover -s tests -q
$env:LNS_TEST_URL='http://127.0.0.1:8009'
node --test tests/test_dashboard.cjs tests/test_dynamic_pipeline.cjs tests/test_simulation.cjs tests/test_map_frontend.cjs
```

55 Python tests and 21 Node tests passed. The Milestone 6 real-map scenario now
also asserts dashboard snapshots, runtime, affected/rerouted counts, application
events, and zero active vehicles / remaining customers at completion. Targeted
tests cover fractional edge progress, blocked baselines, unchanged solutions,
partial failure, reset, timeline limits, and distance/time units.

Changed: `frontend/app.js`, `frontend/index.html`, `frontend/style.css`,
`server.py` (serves dashboard.js), `tests/test_dynamic_pipeline.cjs`.
Added: `frontend/dashboard.js`, `tests/test_dashboard.cjs`, this report.
Work stops after Milestone 7.
