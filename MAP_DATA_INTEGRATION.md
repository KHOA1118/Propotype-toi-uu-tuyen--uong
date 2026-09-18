# Milestone 2.5 — Real Map Data Integration

Implemented: raw OSM → streaming parser → normalized directed network → read-only
backend APIs and GeoJSON. No vehicle simulation, incidents, routing algorithm,
map UI implementation or LNS mathematical changes were added in this milestone.

## Dataset inspection

Original source: `D:\dự án startup\hcm_map4.osm`.
Format: UTF-8 OSM XML 0.6; WGS84 / EPSG:4326 latitude and longitude in degrees.
File size: 11,898,698 bytes. Original and working-copy SHA-256 both equal:
`a8f1c6a74e6fb1eb0d952a3d34d6794ec6d630283be21a699824cf1597eb89fa`.

| Measure | Complete dataset |
|---|---:|
| Raw nodes | 41,580 |
| Raw ways | 7,430 |
| Raw relations | 353 |
| Highway-tagged ways | 3,717 |
| Highway-referenced normalized nodes | 14,450 |
| Nodes used by directed edges | 14,383 |
| Physical linear segments | 15,916 |
| Directed edges | 28,563 |
| Area ways retained but excluded from edges | 6 |
| Duplicate primitive IDs / edge IDs | 0 / 0 |
| Missing way→node references | 0 |
| Edges with estimated travel time | 3,572 |
| Edges with unknown travel time | 24,991 |
| Zero-length edges | 0 |
| Turn-restriction relations | 94 |
| Incomplete turn-restriction relations | 8 |
| Missing relation-member references | 13,689 |

The declared export bounds are latitude 10.743–10.77387 and longitude
106.69879–106.74505. Complete referenced highway geometry extends to latitude
10.7336609–10.7783828 and longitude 106.6920857–106.754099. We keep these
outlying referenced nodes, rather than clipping and breaking roads.
The 67 highway nodes without normalized edges belong only to excluded area
geometry; their way geometry and tags remain available.

Road node IDs are OSM node IDs. An OSM way is an ordered node-reference list,
not a single graph edge. Consecutive references create physical segments.
OSM does not supply standalone IDs for these segments, so deterministic IDs
are generated from way ID, segment index and travel direction.

Observed highway classes include residential, service, primary, secondary,
tertiary, trunk and links, living_street, unclassified, track, road, busway,
footway, steps, pedestrian, path, elevator, construction and proposed.
This is a geographic network inventory, **not a truck-accessible routing graph**.

## Road attributes and direction policy

All tags on retained highway ways and their referenced nodes are preserved.
Useful tags include name/translations, highway class, lanes, surface, oneway,
maxspeed, access, motor_vehicle, hgv, maxweight, maxheight, maxwidth, bridge,
tunnel, layer, service, junction and conditional restrictions. No individual
road/node is hardcoded. Editor user names/UIDs are not included in normalized data.

- `oneway=yes/true/1`: forward arc only; `oneway=-1`: reverse arc only.
- `oneway=no/false/0`: both arcs, even when a roundabout tag is present.
- Without explicit oneway, roundabouts and motorways imply forward direction.
- Other ways default to two directions, marked `default_bidirectional`.
- Unknown/reversible/alternating direction values retain the way but create
  no static arcs; the exclusion reason is reported.
- `area=yes` highway polygons are preserved as ways, not invented linear roads.
- Parallel ways and repeated segments remain distinct. Geometric crossings are
  not merged unless they share an OSM node ID; bridge/tunnel/layer tags survive.
- Mode-specific and conditional rules are retained but not evaluated yet.

In this file, 752 highway ways have explicit oneway tags (644 yes, 108 no).
There are 11 roundabouts. Relations remain intact, including restriction tags
and member roles. Missing references in relations are reported, not discarded.
Most refer outside this bounded extract; eight restriction relations are also
incomplete. `present_in_source` and `present_in_network` distinguish absent
source objects from source objects intentionally outside the highway network.
No turn restrictions are enforced yet; metadata declares `routing_ready=false`.

## Distance and time policy

There are no direct distance/travel-time fields on the inspected highway ways.
Distances are derived with a haversine calculation between each consecutive
OSM coordinate pair, using mean Earth radius 6,371,008.8 meters. Curvature is
represented by the full chain of original nodes; no way endpoint shortcut is used.

Numeric `maxspeed` is interpreted as km/h; explicit mph is converted. Directional
`maxspeed:forward/backward` overrides the common value for its direction.
`travel_time = distance / (speed_limit_kph / 3.6)` is marked
`travel_time_source=maxspeed_estimate`. It is not observed traffic speed or an
accurate truck ETA. No road-class fallback speed is invented. Missing, symbolic,
nonpositive or unsupported speed limits produce `travel_time=null` and retain
the raw tag. Generic speed limits do not resolve hgv-specific restrictions.

Every emitted distance and non-null time is finite and nonnegative. Coordinates
must be finite, latitude within ±90 and longitude within ±180. Zero-length
geometry is permitted and counted (none in the complete supplied dataset).

## Normalized structure

Top-level JSON: `metadata`, `nodes`, `edges`, `ways`, `relations`, `validation`.
Nodes, edges, ways and relations are dictionaries keyed by their string IDs.
String IDs avoid JavaScript integer precision loss. IDs are unique per OSM
primitive type; a node and a way may legally have the same numeric ID.

Actual example node:

```json
{"id":"5780672141","lat":10.7486321,"lon":106.7347218,"tags":{}}
```

Actual example directed edge (distance rounded here only):

```json
{
  "id":"osm:32576407:0:f",
  "from_node":"5780672141",
  "to_node":"366374203",
  "distance":63.70436245368493,
  "travel_time":null,
  "base_travel_time":null,
  "status":"unassessed",
  "way_id":"32576407",
  "segment_index":0,
  "direction":"forward",
  "direction_source":"default_bidirectional",
  "speed_limit_kph":null,
  "travel_time_source":"unknown"
}
```

`f` follows the way's original node order; `r` is the reverse arc. Extra road
attributes live in `ways[edge.way_id].tags`, avoiding duplication per segment.
`base_travel_time` is separate from the future effective cost. Initial status
`unassessed` means vehicle/legal access has not been evaluated; it does not
assert that footways, private roads, proposed roads or hgv=no roads are usable.
The source checksum identifies this network version. Segment indices are stable
for this raw snapshot, not guaranteed across later OSM geometry edits.

## Raw/processed separation and running

The original D: file was read, never edited. A byte-identical working copy is at
`data/raw/hcm_map4.osm`. Derived files are in `data/processed/`:

- `network.json`: complete normalized network.
- `roads.geojson`: one feature per physical linear segment.
- `map_load_report.json`: statistics, source fingerprint and performance measures.

Raw and derived data are ignored by Git; parsing code, tests and this report are
tracked normally. On another checkout, supply the same dataset or a configured
source path. The preparation tool refuses to write into the raw source directory.

```powershell
python -m road_network.prepare --source 'data/raw/hcm_map4.osm' --output-dir data/processed
python server.py
```

Or point the backend directly at the unchanged original:

```powershell
python server.py --map-data 'D:\dự án startup\hcm_map4.osm'
```

Use the bundled Python path in README.md if Python is not on PATH.
Network loading is lazy and cached in memory. A source size/mtime change triggers
validation and reloading. Failed reloads are returned as errors, not stale data.
The server derives from the configured raw source, not an unchecked processed file.

## Read-only API

| Endpoint | Response |
|---|---|
| `GET /api/network/metadata` | CRS, units, source hash, bounds, statistics, policies |
| `GET /api/network` | Full normalized nodes/edges/ways/relations and validation report |
| `GET /api/network/geojson` | LineString FeatureCollection for physical segments |

GeoJSON coordinates use **[longitude, latitude]**, and every feature includes
its `edge_ids`, way ID, segment index, directions, name, highway class and distance.
Reverse arcs do not cause duplicate drawn road geometry. GeoJSON does not include
all detailed tags; join via way/edge IDs in the full network if needed.

Malformed data returns 422; missing/unconfigured source returns 503. No client
can select arbitrary filesystem paths. There is no POST/PATCH incident endpoint.
The existing `/api/optimize` API is unchanged and remains independent.

## Complete-file performance and verification

Measured on this machine, 2026-09-16:

- Uninstrumented complete-file parse/normalize: **1.13 s**.
- Tracemalloc retained allocations for an additional load: **35,802,452 bytes
  (34.14 MiB)**; peak: **55,198,783 bytes (52.64 MiB)**.
- These are Python allocations, not whole-process RSS. The OS disk cache was not
  flushed; the second parse is used only to measure allocations.
- Compact processed network JSON: **15,468,661 bytes**; GeoJSON: **5,944,275 bytes**.
- Live API first metadata request including lazy load: **0.887 s**; subsequent
  cached metadata: **0.015 s**. Full network transfer+decode: **0.489 s**;
  GeoJSON preparation+transfer+decode: **0.364 s**. These timings vary by machine.

All three complete-dataset endpoints returned 200. Source and working-copy hashes
match. **38/38 automated tests pass**, including the complete supplied map test
and all 22 existing LNS tests. The full-map test skips only if its ignored raw
file is absent on another machine; it did not skip here.
Tests cover malformed XML/DTD, duplicate IDs, invalid coordinates, missing road
references, incomplete relations, direction rules, estimated/unknown speeds,
edge integrity, parallel segments, GeoJSON order, cache refresh, source immutability,
processed separation and API success/failure behavior.

## Milestone handoff (design only, not implemented here)

**Milestone 3:** Fetch metadata and GeoJSON, fit to `network_bounds`, draw roads
in geographic coordinates, and join edge/way tags for selection details. Display
OSM attribution. Customer/depot locations require an explicit mapping to this
geographic network; never reinterpret existing synthetic X/Y values as lat/lon.
The earlier unfinished frontend files were not changed in this milestone.

**Milestone 5:** Create scenario-owned edge-state overlays keyed by edge ID and
network source hash. Preserve the raw baseline. Once a valid baseline time exists,
compute effective time from `base_travel_time * congestion_factor`; a blockage
should exclude that directed edge from routing. Decide separately whether an
incident affects one or both directions. Unknown/null times require an explicit
speed policy first. Add versioning so cost matrices cannot silently become stale.
No mutation or incident behavior has been implemented now.

**Milestone 6:** First build a vehicle-appropriate routing graph, applying road
class/access/hgv/weight/height restrictions and turn restrictions; resolve incomplete
relations or reject affected routes. Snap depot/customers to appropriate network
positions; compute shortest-path distance/time matrices and retain the matching
path geometry. The routing nodes are OSM IDs, not optimization customer IDs.
Keep a separate mapping to the existing LNS integer customer IDs (OSM IDs often
exceed its current 32-bit customer-ID validation limit).

Pass those matrices, in the customer's `nodes` array order, through the existing
adapter. Recompute affected path costs after future edge-state changes. Detect
unreachable pairs explicitly; the current adapter rejects infinite costs, so do
not silently substitute arbitrary large penalties. Choose compatible time units
for matrices, time windows and service times.

**Current LNS behavior is unchanged:** absent explicit matrices it computes
Euclidean X/Y distance and distance/speed travel time. It can accept caller-provided
matrices, but is not road-network-aware and does not read these map APIs. Its
objective is still vehicle count then distance; changing only the travel-time
matrix affects feasibility, not its objective. Optimizing time, locking vehicle
assignments and supporting vehicles already in motion require later explicit
algorithm changes; none are hidden in this map integration.

## Files added/changed

Added `road_network/__init__.py`, `loader.py`, `store.py`, `prepare.py`,
`tests/test_road_network.py`, and this document. Updated `server.py` only with
read-only network endpoints/source configuration, `.gitignore`, and README link.
No LNS or frontend code was edited for Milestone 2.5.

## Format references

- [OSM XML and WGS84 coordinates](https://wiki.openstreetmap.org/wiki/OSM_XML)
- [OSM oneway semantics](https://wiki.openstreetmap.org/wiki/Key:oneway)
- [OSM maxspeed units](https://wiki.openstreetmap.org/wiki/Key:maxspeed)

Copyright/attribution/license metadata from the original export is preserved in
the network metadata. The road data is not a source of live traffic observations.
