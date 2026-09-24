# LNS logistics prototype — Milestone 8

A local Vietnamese presentation demo using the supplied HCM OpenStreetMap
network and the original Python LNS engine. Click **Run Demo Scenario** for the
complete sequence: initial routes, moving vehicles, hidden congestion detected through telemetry,
real re-optimization, updated roads, before/after metrics and return to depot.

## Setup (Windows PowerShell)

Use Python 3.10+ and a current browser. From this project directory:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:PORT = '8013'
.\.venv\Scripts\python.exe server.py
```

Open http://127.0.0.1:8013/ and click **Tối Ưu** (Run Demo Scenario). Keep the tab visible
for the presentation. Allow roughly three minutes plus initial loading.
**Dừng demo** stops playback; running the demo again creates a fresh session.
Manual optimization and incident controls are available outside demo playback.

### Preview cannot connect

Keep the server process running while using Web Preview. Opening a URL alone
does not start this Python application. If port 8013 refuses connections, run
the command above again and check `http://127.0.0.1:8013/health` for HTTP 200.
Use the same port in the browser and server; without `PORT` or `--port`, the
server defaults to 8000. `.env.example` is documentation, not automatically loaded.

The default bind is `0.0.0.0`; `HOST` or `--host` can override it. For loopback-only
development, use `--host 127.0.0.1`. Leave `API_BASE_URL` empty for this combined
frontend/backend setup. Render continues to supply its own `PORT`.

The raw map is required at `data/raw/hcm_map4.osm` and is tracked in Git through
an explicit `.gitignore` exception. Include it in every deployment. If missing,
copy the supplied file there (do not edit it), or run:

```powershell
.\.venv\Scripts\python.exe server.py --port 8009 --map-data 'D:\dự án startup\hcm_map4.osm'
```

The predefined fixture validates the map SHA256. Other maps need a separately
validated scenario. No map tiles, GPS, API keys or online map service are used.
After dependencies and the raw map are available, the demo works locally offline.

On this machine the already-installed runtime can be used directly:

```powershell
& 'C:\Users\Khoa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' server.py --port 8009
```

Stop the server with Ctrl+C. Restart it after backend edits, then reload the
browser. An old server can serve new frontend files but lack their API endpoints;
if Run Demo reports “Not found”, restart the server. If the port is occupied,
stop your previous instance or use `--port 8010` and open that matching URL.
Map loading failures expose a retry button. Failed demo stages show an error and
allow a fresh run; there is no mock optimization fallback.

## What is deterministic

`data/presentation_scenario.json` stores fixed geographic inputs, LNS seed,
fleet settings, map hash, hotspot timing and validation metadata. It contains no precomputed
solutions or savings. Every run invokes real initial LNS and real dynamic LNS.
Hidden congestion is injected at 5 simulated seconds. Known costs stay unchanged
until two consecutive 500 ms telemetry intervals observe speed at or below 50%.
The event then progresses DETECTED → REOPTIMIZING → ROUTES_UPDATED. A single
process worker runs the real LNS while the browser polls every 300 ms and keeps
vehicles and map interaction active. Affected vehicles commit their current edge
and may wait at its end for a safe replacement; the fleet clock never freezes.
Actual wall-clock runtime varies; no result is applied before the server returns.
The fleet then completes all deliveries and returns to depot.

## Validation

Python tests require NumPy. Node.js 22+ is needed only for JavaScript tests;
use a current Node release for the same browser-compatible APIs.
Start the server first, then in another PowerShell window:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -q
$env:LNS_TEST_URL='http://127.0.0.1:8013'
node --test tests/*.cjs
```

Some provenance tests use the original files on D: and skip when those external
files are absent. The full-map and presentation tests require the supplied map.
The presentation test repeats the fixed scenario with different frame sizes and
checks hidden-event isolation, telemetry, real solver calls, feasibility, continuous
positions, and every vehicle returning to depot.

## Architecture and limitations

`server.py` serves the frontend and APIs. `lns/core.py` remains the original
algorithm; `lns/adapter.py` converts solver inputs/outputs. The road layer handles
OSM parsing, directed paths and incident costs. `frontend/simulation.js` owns
movement; `dashboard.js` reads metrics; `presentation.js` controls demo timing.
The new `/api/presentation-scenario` endpoint supplies the frozen inputs.
`POST /api/jobs/initial` and `POST /api/reoptimize` return HTTP 202 with a
`job_id`; poll `GET /api/jobs/{job_id}` for queued/running/completed/failed.
Completed responses contain `result`. `/api/traffic/inject` changes physical
conditions only; `/api/traffic/telemetry` detects and publishes the known cost.
`/api/traffic/applied` acknowledges the matching successful revision.

Both demo initial and dynamic optimization use directed OSM travel seconds,
with 30 km/h estimates where OSM time is missing. The compatibility endpoint
`/api/optimize` still accepts external matrices and defaults to Euclidean costs
when omitted; it is not the presentation path. Core LNS operators are unchanged.
Dashboard time is summed vehicle driving time, not fleet makespan; before/after
uses the same remaining-work snapshot and incident costs. These are modeled
savings, not measured operational results. Customers stay on their original vehicle.

Remaining prototype limits: no enforced turn restrictions/truck dimensions;
no live traffic or GPS; in-memory single-browser simulation state; sequential
local HTTP server; no public deployment/authentication. A vehicle already inside
a blocked edge cannot teleport out. Tight windows may be conservatively rejected.
Keep the presentation tab visible; background throttling can alter wall-clock
pacing. Demo mode is deterministic on the tested runtime/input, not a guarantee
of identical timings across machines or dependency versions.

See [MILESTONE_8.md](MILESTONE_8.md), [MILESTONE_7.md](MILESTONE_7.md),
[MILESTONE_6.md](MILESTONE_6.md), and [REAL_LNS_VERIFICATION.md](REAL_LNS_VERIFICATION.md)
for historical implementation details. See DEMO_REFINEMENT.md for the current
scenario and behavior, which supersede older demo timing descriptions.

## Manual deployment (combined Python service)

Do not upload only `dist/`: that is an optional static export and cannot run LNS
or the API. Deploy the complete project on a Python web service, from its root.

- Build: `pip install -r requirements.txt && python tools/build.py`
- Start: `python server.py`
- Health check: `/health`
- Python: 3.12.10 as configured in `render.yaml`; Node is only required for tests.
- `HOST=0.0.0.0`; the platform supplies `PORT` (defaults to 8000 locally).
- Leave `API_BASE_URL` and `ALLOWED_ORIGINS` empty for same-origin hosting.
- `MAP_DATA` is optional; default: `data/raw/hcm_map4.osm` relative to the project.
- Keep `frontend/`, `lns/`, all `road_network/` modules (including `context.py`),
  `deployment_config.py`, `server.py`, `tools/build.py`, `requirements.txt`,
  `data/presentation_scenario.json`, `data/example_request.json`, and the raw map.
- The build checks the original OSM checksum and creates `dist/` assets; the
  server reads `frontend/` and normalizes the raw OSM in memory. No processed
  network file is required. `.env` files are not loaded automatically.
- If deploying from Git, include new/untracked source files and your latest
  edits in the commit before pushing; deployment cannot see local-only files.

This is a small presentation prototype: one HTTP process and one solver worker,
in-memory sessions, no authentication or rate limiting. Run one service instance;
restarts discard sessions. Public high-traffic production requires additional
operational hardening. Free-host cold starts and resource limits should be checked
on the chosen host before presenting. `/health` checks liveness; also open the map
and complete one demo after deployment to check data and solver readiness.
