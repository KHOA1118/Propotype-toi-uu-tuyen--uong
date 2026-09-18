# Milestone 8 — Demo mode and prototype polish

`Run Demo Scenario` loads `data/presentation_scenario.json`, creates a fresh
incident session, computes the initial solution with real LNS, previews the
roads, and starts the six vehicles. It reports the predefined accident on
`osm:290409207:0:f` at 8 simulated seconds, displays its ×6 travel-time impact,
starts real dynamic LNS at 9 seconds and applies the returned result at 9.5
simulated seconds. Updated polylines fade in, metrics and a short computed
summary appear, and every vehicle continues to depot. There is a stop control
and a new run always resets the incident session.

The fixture stores 24 customer inputs, fleet settings, seed, map hash and the
event only. No optimized routes or savings are stored. Input selection was
curated for a clear presentation, but all displayed results are computed live.
The presentation clock is held while awaiting incident acknowledgement and
after 0.5 simulated seconds of movement while LNS is pending. This is a declared
presentation timing policy, not a real-time GPS feed; wall-clock runtime varies.

The original LNS engine, adapter, road-cost model and simulation implementation
were not changed. Original engine SHA256 remains
`2504b679c60089bbf87d1f6d55717bd0d3804c90e104872d143aba5396134fed`.

## Polish

- Prominent one-click demo and stop buttons; conflicting manual controls lock
  during the sequence and are restored on completion or stop.
- Stage-specific loading/error messages, bounded fetches, map retry control,
  cancellation checks and fresh-session replay.
- Stronger incident-edge highlight and a brief updated-route fade that respects
  reduced-motion preference.
- Raw JSON editor/output removed from visible presentation UI. Internal hidden
  fields retain compatibility with the existing frontend flow.
- Responsive header/dashboard spacing. Static Euclidean details stay collapsed.
- README rewritten with current startup, raw-map requirements, tests, offline
  behavior and the need to restart the backend after edits.

## Verification

All 55 Python tests and all 23 Node tests passed. The added presentation scenario
test performs two complete API/LNS/simulation runs at 17 ms and 50 ms frame sizes,
verifies identical orders and metrics, actual solver calls, feasibility,
continuous positions, and zero remaining customers/active vehicles at the end.
The final isolated browser run also completed without JavaScript errors: all
six vehicles returned, active vehicles and remaining customers both reached
zero, and Run Demo Scenario became enabled again for replay.
It also verifies that the summary does not invent savings for worse or blocked
results. The browser one-click run showed the complete decision timeline and
two rerouted vehicles with approximately 87 seconds (1.5%) less estimated total
remaining driving time. Distance increases in this time-minimizing scenario;
the dashboard displays that tradeoff rather than claiming every metric improves.

Use the updated local server at http://127.0.0.1:8009/. A stale Milestone 7 server
on that port was found serving new UI files without the new endpoint, producing
“Not found”; it was restarted with the current code.

## Remaining non-critical prototype limitations

- Existing OSM time estimates and missing-speed fallback at 30 km/h; no live GPS
  or traffic detection. Turn restrictions and truck dimensions are not modeled.
- Initial LNS remains Euclidean; dynamic LNS explicitly minimizes road seconds.
  Improvements describe modeled driving time, not observed business savings.
- Single-process local server and in-memory browser/session state; no deployment,
  authentication or multi-operator synchronization is supplied.
- Keep the tab visible. Browser throttling changes wall-clock animation pacing;
  simulated event times stay fixed. Runtime/dependency versions may affect timing.
- Current blocked-edge and conservative time-window limitations from Milestone 6
  remain. The scripted incident is an accident, not a total blockage.

Changed: `frontend/app.js`, `frontend/index.html`, `frontend/style.css`,
`server.py`, `README.md`. Added: `frontend/presentation.js`,
`data/presentation_scenario.json`, `tests/test_presentation.cjs`, this document.
No major features were added beyond Milestone 8.
