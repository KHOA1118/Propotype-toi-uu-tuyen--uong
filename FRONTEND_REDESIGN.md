# Frontend redesign verification — 2026-09-22

## Scope and files

- `frontend/index.html`: one primary demo action, five SVG KPI badges, map-first
  layout, six decision metrics in a 3×2 grid, comparison chart, existing six
  operational panels. Removed `run` / `run-form`, preserved other operational IDs.
- `frontend/style.css`: replaced successive theme overrides with one light design
  system, responsive grids, map sizing, focus/disabled/reduced-motion states.
- `frontend/app.js`: safe loading state after removal of the old button; renders
  KPI/chart values from the existing dashboard snapshots; display-only map styles.
  The travel KPI explicitly switches to remaining-route time after reoptimization.
- `road_network/context.py`: optional display-only OSM way features.
- `road_network/store.py`, `server.py`: cache/expose these features at
  `GET /api/network/context`, separate from the normalized routing graph.
- `tests/test_context.py`: real feature parsing and exact network, route, objective,
  and road-geometry equality before/after loading context with real LNS.
- `tests/business-metrics.test.cjs`: absent data and genuine cost increases remain
  honest: no fabricated savings, correct units, negative savings and scope labels.
- `tests/test_road_network.py`: drain the malformed-data response and serial server,
  then collect the failed XML iterator before deleting its temporary file on
  Windows. All existing API error assertions remain. Production loader unchanged.

No edits to LNS, adapters, cost matrices, routing, simulation, telemetry,
presentation lifecycle, dashboard state, customer ownership, workers or polling.

## Validation

- `python -m unittest discover -s tests -q`: 64/64 passed on final run.
- `LNS_TEST_URL=http://127.0.0.1:8013 node --test tests/*.cjs`: 25/25 passed.
- `node --check frontend/app.js` and `git diff --check`: passed.
- Browser: initial optimization, six moving vehicles, hidden congestion detected
  at about 84.5 s, real reoptimization, applied routes and depot completion.
  Final: 24 customers served, 0 remaining, 0 active vehicles, 3 affected,
  2 rerouted, estimated remaining travel reduced by 61.6 seconds.
- Browser demo completed at 149.6 simulation seconds; console had no errors.
- Verified zoom, pan (transform changed with drag), fit, customer selection,
  OSM attribution and removal of the old optimization DOM elements.
- Visually checked 1366×768, 1920×1080 and 390×844. Viewport override reset.
- Context endpoint/DOM: 170 real features (27 water, 143 green).

## Semantics and limits

The before/after chart shares the dashboard's comparison scope. After an incident,
both values represent remaining work at the request snapshot under the same
incident costs, not completed fleet totals. Rerouted vehicles are measured against
the plan at that snapshot, so the comparison baseline is zero. Live vehicle and
remaining-customer counts continue updating independently. Missing costs use an
em dash, never invented numbers. Savings may be negative.

Context rendering supports complete simple OSM ways (closed areas and river/canal
lines); it does not assemble relation multipolygons/holes. Missing or incomplete
features are omitted. If the optional endpoint fails, the neutral road map stays
usable. No basemap tiles, invented landscape, or external mapping dependency.

The malformed-map test initially intermittently hit Windows file locking. The
test cleanup above resolves that fixture lifecycle without expanding this task
into production-parser changes. Existing prototype constraints (estimated speeds,
fixed demo, approximate map context) remain.

## Manual check

Run `python server.py --port 8013`, visit `http://127.0.0.1:8013/`, and click
**Chạy kịch bản mẫu**. Leave it running until all vehicles return. Check the
incident highlight, updated routes, KPI cards, comparison scope and timeline.
Use zoom/fit, drag the map and select a customer; scroll below for operational
panels. The separate optimization form is intentionally no longer present.
