# Milestone 3 — real HCM map visualization

**Update:** straight-line overlays have now been replaced by directed OSM shortest-path geometry. The historical verification below describes the earlier version. See [ROAD_ROUTING_AUDIT.md](ROAD_ROUTING_AUDIT.md) for the current behavior, connected demo, snapping, 53-test verification and unchanged LNS cost model.

Implemented only map visualization and its connection to the existing optimizer.

## Data flow

`hcm_map4.osm → Milestone 2.5 loader → GET /api/network → SVG road layer`

`mapped delivery scenario → frontend/map-data.js → POST /api/optimize → existing adapter/core → response → route and marker overlay`

The frontend draws 3,711 non-area highway ways from the normalized network. They share the same geographic projection as the depot and customer markers. Reverse directed edges are not drawn twice. Road paths are batched by highway class to keep the SVG small. No external tiles, CDN, or mock road network are used. OSM attribution and the source filename, node/edge counts, and SHA256 (hover over the source) are displayed.

## Demo stops and mathematical boundary

The dataset contains roads, not delivery orders. A deterministic selection places a demo depot near the extent center and spreads ten demo customers across eligible real road nodes. These are illustrative delivery locations, not verified business addresses or Bến Thành. Delivery IDs 0–10 remain separate from string OSM IDs. The editable scenario references `osm_node_id`; missing references and duplicate IDs are rejected.

The frontend converts geographic coordinates into local equirectangular X/Y meters using the network extent center and Earth radius 6,371,000 m. Existing LNS computes Euclidean distances using those coordinates. Capacity is 40, demand is 10 per customer, fleet limit is 3, demo speed is 1 m/s, and service time is 1 second. Time windows are deliberately broad. The adapter, original engine, raw dataset, and normalized loader are unchanged.

Colored overlays represent the backend's ordered stop sequences as straight connections. They do not assert road-following navigation or truck accessibility. Computing shortest paths, applying full access/turn restrictions and feeding road-cost matrices into LNS remains future work. No vehicle animation, incidents, or dynamic rerouting were added.

## Files

- `frontend/map-data.js`: geographic projection, deterministic mapped demo scenario, API conversion, response-to-map binding validation.
- `frontend/app.js`: load normalized network, draw roads, optimize and update overlays, point details, before/after and map controls.
- `frontend/index.html`, `frontend/style.css`: geographic map layers, attribution, provenance and model explanation.
- `server.py`: serve the additional JS module; existing optimization endpoints unchanged.
- `tests/test_map_frontend.cjs`: six tests against the real network and live optimization API.
- This report and README entry.

## Verification (2026-09-16)

- Python: `python -m unittest discover -s tests -v` — **38/38 passed**, including original-function equivalence and real LNS audit.
- Live frontend integration: start `python server.py --port 8001`, then `node --test tests/test_map_frontend.cjs` — **6/6 passed**. Override the test URL with `LNS_TEST_URL` if using another port.
- Browser verified real road geometry, 11 markers, three differently styled routes, Optimize response redraw, before/after changes, keyboard/customer selection, zoom/fit, invalid-input error and successful retry. No browser console errors were reported.
- Default scenario: initial Euclidean distance **33,431.13 m**, optimized **27,211.48 m**, three routes, ten customers served once. Observed LNS search approximately **0.04–0.05 s**, not a production performance guarantee.

## Manual verification

1. Run `python server.py --port 8001` from the project directory (install requirements first if needed).
2. Open `http://127.0.0.1:8001`. Confirm `hcm_map4.osm`, 14,450 nodes and 28,563 directed edges appear below the real road drawing.
3. Click **Tối ưu tuyến (Optimize)**. Three colored visit-order overlays appear and objective metrics update.
4. Compare **Trước tối ưu / Sau tối ưu**. Click a marker or choose a customer in the list to inspect its geographic coordinates, OSM ID, demand, time window and assigned route.
5. Use zoom and fit; highlight a route in the sidebar.
6. Optionally enter an unknown `osm_node_id` in the scenario and optimize: an error appears with no invented geographic fallback. Restore it and retry.

The entire network is fetched once (~16.8 MB uncompressed); rendering is suitable for this fixed local prototype. Public hosting may later benefit from compressed responses and geometry-only payloads. Missing map data disables Optimize and shows an actionable error. The raw OSM file is git-ignored and must be provisioned separately on another machine.
