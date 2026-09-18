# Milestone 5 — Traffic incident reporting

Implemented flow: user selects a directed road segment or a vehicle's current edge, selects the incident type, submits to the backend, and the acknowledged session state updates simulation movement and map markings. Reporting never calls the optimizer or regenerates route geometry.

## Rules

| Incident | Effect on selected directed edge | Map |
| --- | --- | --- |
| congestion | Travel time ×3; remaining traversal runs at one-third baseline speed | Amber |
| accident | Travel time ×6; remaining traversal runs at one-sixth baseline speed | Amber |
| road_blockage | Unavailable; vehicles already on the edge stop in place, approaching vehicles stop at its start | Red |

These are explicit prototype rules, not measured traffic predictions. Service stops and unaffected edges keep their original timing. Events take effect prospectively when the browser receives backend acknowledgement; positions never jump backwards. When several reports affect one edge, the maximum slowdown applies and blockage takes precedence. Factors do not compound. Reports affect only the submitted directed edge, not its reverse edge.

The normalized dataset remains immutable. Each browser page creates an independent simulation session with an `edge_overrides` overlay. Known baseline travel times are multiplied in seconds. Unknown times remain null; the simulation applies the factor to its existing presentation duration rather than inventing an OSM travel-time measurement. A blocked edge has `available: false`, `status: blocked`, and `travel_time: null`.

## API and state

- `POST /api/simulation` with `{source_sha256}` creates an in-memory session.
- `POST /api/incidents` with `{session_id, type, edge_id, vehicle_id?}` validates and stores an active report, then returns the updated session.
- `GET /api/simulation?session_id=...` reads the stored session back.
- State includes `session_id`, source SHA256, revision, incident history (ID, type, edge, optional reporting vehicle, active status, UTC timestamp), and effective directed-edge overrides.
- Invalid types, unknown edges/sessions, invalid reporting vehicle IDs and stale map versions return errors without changing stored state.

The browser chooses an edge from the displayed routes, defaulting to the suggested hotspot. Vehicle context captures its current edge at submission time. A vehicle at depot or servicing has no current moving edge and produces a clear instruction to select a road instead. Vehicle context is client-reported prototype metadata; the backend does not independently track live vehicle positions.

Simulation now has separate per-vehicle progress clocks. An incident only consumes extra time on affected segments and does not slow the entire fleet. Reset, before/after switching, and manual Optimize preserve session incidents. Reset returns vehicles to depot; reloading creates a clean session. Reports are in server memory only and disappear on server restart. There is no resolve/delete workflow in this milestone. A blocked vehicle remains stopped; completion is not falsely reported while it is blocked.

## Verification

- Python: **49/49 passed**, including incident API/readback, session isolation, validation, strongest-effect rules, unchanged raw map and existing LNS audit.
- Simulation: **8/8 passed**, including unaffected movement, prospective slowdown, blocked approach/in-edge position, pause/reset persistence and frame-size independence.
- Live network/API: **8/8 passed**, including a real OSM vehicle-context blockage, backend readback and unchanged route geometry.
- Browser: reported congestion on `osm:220972652:8:f` (revision 1, amber). Reported accident from Vehicle 1's current edge (revision 2). Reported blockage on that edge (revision 3, red). Vehicles 1 and 6 stopped at identical unchanged coordinates after Resume; other vehicles advanced. No browser console errors observed.

## Run / demonstrate

Run `python server.py --port 8007` and open `http://127.0.0.1:8007`.

1. Optimize, select the suggested shared segment, choose **Kẹt xe**, and click **Gửi báo cáo**.
2. Confirm the server acknowledgement, active incident list and amber road marking.
3. Start the fleet. Pause while a vehicle is moving; select **Xe 1 · đoạn hiện tại** and **Chặn đường**, then submit.
4. Resume: affected vehicles stop; others continue on the same routes.
5. Reset retains reports. Reload to start a clean incident-free session.

Test commands: `python -m unittest discover -s tests`; `node --test tests/test_simulation.cjs`; set `LNS_TEST_URL=http://127.0.0.1:8007` then `node --test tests/test_map_frontend.cjs`.

Files: new `road_network/incidents.py` and `tests/test_incidents.py`; updated `server.py`, `frontend/simulation.js`, `frontend/app.js`, `frontend/index.html`, `frontend/style.css`, simulation/live tests and documentation. No core LNS edits, dynamic rerouting, or Milestone 6 work.
