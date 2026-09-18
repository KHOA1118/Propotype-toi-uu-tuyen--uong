# Milestone 4: vehicle simulation

One vehicle is created for every route in the selected before/after plan. `frontend/simulation.js` owns playback state independently of the optimizer response. It copies node positions into a deterministic timeline, validates directed edge continuity, and traverses the exact edge order returned by the road router. It never changes LNS data or route assignments.

Start begins at the depot, Pause freezes elapsed time, Resume continues from that time, and Reset returns every vehicle to its depot without recalculating routes. Changing before/after plans or requesting a new optimization cancels the old animation and prepares a new timeline. Hidden tabs automatically pause and require Resume.

Each vehicle snapshot includes vehicle/route index, latitude/longitude, current zero-based segment index, edge ID, next stop, progress and activity (ready, moving, servicing, completed). At completion segment index equals edge count and edge ID is null. Vehicle markers and the sidebar expose the current state. Coincident vehicles naturally overlap on shared roads; the sidebar still lists every vehicle.

Timing is a presentation model: all vehicles use one common speed calculated so the longest route completes in approximately 180 seconds, including a one-second pause per customer. It does not represent real driving speed, actual traffic time, or LNS time-window validation. Interpolation follows each OSM edge between its endpoint coordinates, never skipping directly between customers. Results depend on elapsed simulation time, not frame count. Shorter routes finish earlier; the simulation completes only when all vehicles return.

## Verification

- Python: 46/46 tests passed, including original LNS function equivalence.
- Simulation unit tests: 5/5 passed (multiple vehicles, interpolation/order, customer dwell, pause/resume/reset, frame independence, invalid geometry/time, zero-length routes).
- Live network/API tests: 7/7 passed, including a full 180-second six-vehicle run with 100 ms steps checking positions and assigned edge IDs against the real road graph, depot completion and unchanged input geometry.
- Browser: six vehicle markers; Start advances; Pause positions remain identical between observations; Resume continues; Reset returns all six to segment zero at the depot while retaining all six route overlays; before/after switching resets playback. No console errors observed.

## Run and verify manually

`python server.py --port 8006`, then open `http://127.0.0.1:8006`.

1. Click **Tối ưu tuyến** and wait for road routes.
2. Click **Bắt đầu**, watch road-following markers and segment counters.
3. Click **Tạm dừng**, then **Tiếp tục**. Positions freeze and resume.
4. Click **Đặt lại**. All vehicles return to the depot and the LNS result stays intact.
5. Run until completion (about three minutes) to see all vehicles return.

Tests: `python -m unittest discover -s tests`, `node --test tests/test_simulation.cjs`; for live API tests set `LNS_TEST_URL=http://127.0.0.1:8006` and run `node --test tests/test_map_frontend.cjs`.

Files changed: `frontend/simulation.js` (new), `frontend/app.js`, `frontend/index.html`, `frontend/style.css`, `server.py` (static module mapping only), `tests/test_simulation.cjs` (new), `tests/test_map_frontend.cjs`, README and this report. No LNS engine changes, incidents or rerouting.
