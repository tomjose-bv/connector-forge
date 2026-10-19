# Progress

## Done

- Plan written (PLAN.md). Local repo created with personal git identity.
- M1.1 Project skeleton: pyproject, src layout, `scripts/setup.py` (creates `.venv`), MIT
  license, README stub, smoke tests (2 passing).
- M1.2 Scenario format: `scenario.py` (dataclasses, YAML load, validation), example
  `scenarios/dev/contacts_offset_apikey.yaml`. 14 tests passing.
- M1.3 Synthetic data: `data.py` (`generate`, `apply_changes` with soft/hard deletes,
  `apply_drift`). Deterministic per seed. 18 tests passing.

## Next step

Milestone 1, step 4: mock API server. `src/connector_forge/mock_api.py`: stdlib
`ThreadingHTTPServer` on 127.0.0.1:0 serving a scenario's dataset: auth (api_key header,
bearer, OAuth client credentials via POST /oauth/token), the 4 pagination styles,
`updated_since` filter for incremental resources, rate limit (429 + Retry-After), request
log. `MockAPI(scenario)` context manager with `.url`, `.set_phase("changed"|"drifted")`.
Tests using urllib against a live instance.
