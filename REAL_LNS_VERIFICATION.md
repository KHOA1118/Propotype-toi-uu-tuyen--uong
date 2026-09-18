# REAL LNS VERIFICATION — Milestone 2

Date: 2026-09-16. Verdict: **PASS** for the local Milestone 2 integration.

| Check | Result |
|---|---|
| Real LNS called | YES |
| Mock solver present in production optimization path | NO |
| Feasibility checks | PASS |
| Data conversion | PASS |
| Mathematical/algorithm code modified | NO |
| Automated tests passed | 22/22; no skips on this machine |
| Safe to commit | YES for the audited Milestone 2 backend, tests and documentation |

## Execution proof

1. `server.py`, `Handler.do_POST`, line 52 calls `solve_instance(**payload)`.
2. `lns/adapter.py`, `solve_instance`, line 141 validates the caller data and
   creates a serialized, isolated solve through `_solve`, line 158.
3. `_solve` loads the actual `lns/core.py` and initializes the global arrays
   used by its original functions. The search call is at adapter line 192.
4. Real search starts at `lns/core.py::run_lns`, line 1967. Initial construction
   and feasibility evaluation also execute original engine functions before it.
5. That same function returns at core line 2187, including `best_solution`,
   `best_evaluation`, current solution/evaluation, iteration log and elapsed time.
6. Adapter line 198 takes routes directly from `result['best_solution']`;
   objectives and detailed schedules come from `best_evaluation`.
7. `Handler.do_POST`, line 60 returns the adapter result as JSON.

The audit uses Python call/return profiling inside the real HTTP handler thread.
It observes the code filename, function name, actual global arrays at search
entry and the actual returned object. It does not substitute an optimization
function. A 12-iteration request produced exactly one `run_lns` call and 12
calls each to destroy selection, repair selection and SA acceptance.

The API routes, objective, route details and search duration were compared
against the captured engine return object and matched exactly. Both
`solve_mock` and `mock_instance` were patched to raise immediately if called;
the real HTTP request still succeeded. Static inspection confirms the server
imports neither utility. Missing `instance` returns 400, not a mock result.

## Original-code comparison and every modification category

Original file: `D:\base_vrp+lns_(refined).py`.
SHA-256 remains:
`c5c88788e111b3654af819a965b5259d1a743bd3994e42ae337a3321525bc7ed`.

- **Original file modifications: none.** It remains untouched.
- **Original function-body modifications: none.** All 54 extracted functions
  match both the original source text and parsed AST. Both destroy/repair
  registries match the original AST.
- **Refactoring/extraction:** the existing Milestone 1 extraction moved those
  unchanged functions/registries into `lns/core.py`; retained required imports
  and depot ID 0; added a module description; excluded Colab mounting,
  notebook data loading/validation, top-level execution, plots and reports.
- **Integration:** the separate adapter now supplies request-specific arrays,
  ID mapping and fleet configuration; isolates the random generator with the
  same Python random mechanism; captures notebook stdout under a lock;
  validates input and serializes real results. HTTP handling is in `server.py`.
- **Configuration:** adapter defaults are 30 iterations and removal count 3
  for the small demo; original notebook defaults were 100 and 20. Both are
  configurable through the API. SA defaults remain 100 / 0.995 / 0.01.
- **Mathematical/algorithm changes: none.** Objective ordering, SA probability,
  cooling, neighborhood operators, insertion, capacity, schedules and depot
  return checks are unchanged. There was nothing mathematical to revert.
- **This audit's code fix:** only the adapter checks whether the returned
  result can be encoded as finite JSON. Individually finite costs can overflow
  when summed. That case now returns HTTP 400 instead of dropping the connection.
  No clamping, cost adjustment or alternative optimization is performed.

## Data conversion and independent feasibility checks

The tests observe actual engine inputs, rather than trusting echoed JSON:

- Sparse IDs `[71, 0, 23]` remain intact; depot is second in the input array.
- ID-to-index mapping, X/Y coordinates, fleet count, capacity, demands,
  ready times, due dates and service times exactly match caller input.
- Explicit asymmetric distance and travel-time matrices preserve their values
  and node-array ordering. Separate tests verify Euclidean derivation and speed.
- A nonzero depot start time, waiting, exact customer deadline and nonzero
  service durations are retained. One checked schedule has arrival times
  `[4, 6, 15, 20]` and waits `[0, 4, 0, 0]`.
- An independent test evaluator recomputes route loads, distances, arrivals,
  waiting, service start/departure and depot return directly from request data.
  It does not call the LNS evaluation functions.
- Every customer appears exactly once, all route IDs exist, depot endpoints
  are correct, fleet/capacity limits hold, service begins within each window,
  and vehicles return within the depot deadline.
- API objective vehicle count and distance agree with independently calculated
  values and the actual engine return value. Best objective does not worsen
  relative to the initial objective in tested runs.

## Requests and test coverage

Run: `python -m unittest discover -s tests -v`.
Final result: **22 tests passed, 0 failures, 0 errors, 0 skipped**.

Fixed seeds `0`, `7`, `42`, `2147483647` each ran twice through HTTP for
20 iterations; routes/objectives repeated for each seed and passed independent
feasibility checks. Different seeds need not produce different optima.

Coverage also includes:

- The first 10 customers plus depot from supplied Homberger `C1_10_1.TXT`,
  with original demands, time windows and service durations.
- One-customer instances and coincident coordinates/zero distances.
- Default initialization and caller-provided feasible initial routes.
- Rejected overcapacity routes, late customer service and late depot return.
- Duplicate/missing/unknown IDs, invalid route coverage and missing fields.
- Malformed JSON, unsupported options, invalid temperatures/cooling, booleans
  passed as numbers, invalid matrix sizes/diagonals, negative and infinite costs.
- Request size limits, unknown endpoints, internal errors, client disconnects,
  recovery, instance isolation and changed data producing changed costs.
- Aggregate numeric overflow returns a JSON error instead of disconnecting.

## Known limitations and commit boundary

- This establishes real algorithm execution and tested integration correctness;
  it does not prove global optimality or correctness for every possible instance.
- The full 1,000-customer search is not benchmarked; the UI timeout does not
  cancel Python computation. The local server is synchronous and serial.
- Depot ID must be 0; a shared capacity applies to the fleet. The request limits
  remain 1,000 customers, 100 iterations and 32 MiB. Infinite/unreachable costs
  are rejected rather than treated as road closures.
- Greedy initialization can fail for a feasible instance. A 422 construction
  error is not an infeasibility proof; feasible initial routes can be provided.
- Existing objective still minimizes vehicle count, then distance. It does not
  minimize travel time; assignments can change between vehicles.
- Original source/ZIP comparison tests skip on machines lacking the D: files;
  neither skipped in this verification.
- No production deployment or traffic/dynamic behavior is certified here.
- Frontend edits from the previously requested, interrupted Milestone 3 remain
  in the workspace. They were not continued or changed during this audit and
  are not included in the Milestone 2 commit verdict. Review/stage only intended
  files; no commit was created by this audit.

Audit changes: `lns/adapter.py` (overflow guard),
`tests/test_real_lns_audit.py` (eight additional tests), this report.
