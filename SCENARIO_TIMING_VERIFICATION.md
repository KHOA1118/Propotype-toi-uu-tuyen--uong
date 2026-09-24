# Vehicle 2 / Vehicle 5 scenario verification

The deterministic input search selected configuration seed 44 instead of 42.
LNS still assigns customers and builds every route. No algorithm, frontend,
simulation, telemetry, routing or job implementation was changed for this task.
Uncommitted frontend redesign changes belong to the preceding task.

## Timing evidence

Measured using the real frontend Simulation and backend telemetry/LNS APIs,
with 50 ms simulation steps, the existing 700 ms detection display delay and
500 ms simulated solver-response delay. Completion is the first completed
snapshot (up to one frame of observation resolution); browser timing may vary.

| Measurement | Previous | New |
| --- | ---: | ---: |
| Vehicle 2 returns to depot | 96,600 ms | 132,100 ms |
| Vehicle 5 returns to depot | 99,600 ms | 104,250 ms |
| Detection timestamp | 84,500 ms | 88,500 ms |
| Detecting vehicle | 5 | 5 |
| Vehicle 2 active at detection | yes | yes |
| Vehicle 2 progress at detection | 87.50% | 67.02% |
| Vehicle 2 finishes after Vehicle 5 | no | yes, by 27,850 ms |

The old scenario already detected congestion before Vehicle 2 finished, but
Vehicle 2 had little work left and returned before Vehicle 5. The new input
leaves Vehicle 2 visibly delivering throughout detection and after Vehicle 5
returns, without artificial delays or predefined output routes.

## Input and constraints

- 24 customers, 6 vehicles, capacity 40, demand 10 per customer, demand 0 at depot.
- Feasible real initial LNS: [4, 4, 4, 4, 4, 4] customers per vehicle;
  every customer served exactly once.
- Depot and customer 1 unchanged; customer IDs 2–24 use newly sampled real OSM
  nodes. Full old/new mapping: `changed_input_locations` in the validation JSON.
- Same incident edge: `osm:1218673270:6:r` (366439129 → 366473777).
  Initial users now 1, 4, 5, previously 1, 5, 6.
- Factor 3, injection at 5 s, telemetry every 500 ms, threshold 50%, two abnormal
  intervals. Physical state stays separate from optimizer-known costs.
- Existing overlap/corridor acceptance criteria preserved.

## Files changed in this task

- `tools/design_root_scenario.py`: input-only search, geometric prefilters,
  actual end-to-end timing acceptance before writing fixtures; CLI node/server
  and seed-range options. Search tried 42, 43, 44 and accepted 44.
- `tools/validate_presentation.cjs`: reusable real Simulation/backend validator;
  explicit solver-delay parameter is for tests, never production behavior.
- `data/presentation_scenario.json`: generated seed-44 input fixture.
- `data/scenario_validation.json`: generated timing, overlap, previous baseline
  and location-change evidence. No fabricated measurements.
- `tests/test_presentation.cjs`: feasibility/counts/capacity, vehicle 5 detection,
  vehicle 2 active progress and completion-order assertions; unchanged routes
  and unpublished costs before detection; lifecycle and evidence validation.
- This report.

## Commands and results

```powershell
python tools/design_root_scenario.py --node <path-to-node> --base-url http://127.0.0.1:8013
node tools/validate_presentation.cjs data/presentation_scenario.json
python -m unittest discover -s tests -q
$env:LNS_TEST_URL='http://127.0.0.1:8013'
node --test tests/test_presentation.cjs
node --test tests/*.cjs
git diff --check
```

Full Python suite: 64/64 passed. Full Node suite: 26/26 passed.
Timing regression covers 17/50/100 ms frames and 0/500/2500 ms solver delays.
The 50 ms / 500 ms run reproduces the generated completion evidence exactly.
Premature reoptimization remains rejected; routes stay identical and known
revision/costs stay unchanged until detection. Replacement routes preserve
positions and served customers, and the fleet completes all deliveries.

Lifecycle: INACTIVE → ACTIVE_UNDETECTED → DETECTED → REOPTIMIZING → ROUTES_UPDATED.

Manual check: run `python server.py --port 8013`, open the local preview and
click **Chạy kịch bản mẫu**. Around 88.5 s Vehicle 5 confirms the slowdown;
around 104.3 s it is back while Vehicle 2 remains active until about 132.1 s.

Browser verification after restart: detection at 88.5 s, reoptimization started
at 89.2 s and applied at 89.9 s. At 119.7 s Vehicle 5 was at the depot while
Vehicle 2 was still returning (segment 409/446). All vehicles finished at
149.8 s, with 0 customers remaining and no JavaScript console errors.
