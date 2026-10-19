# Progress

## Done

- Plan written (PLAN.md). Local repo created with personal git identity.
- M1.1 Project skeleton: pyproject, src layout, `scripts/setup.py` (creates `.venv`), MIT
  license, README stub, smoke tests (2 passing).
- M1.2 Scenario format: `scenario.py` (dataclasses, YAML load, validation), example
  `scenarios/dev/contacts_offset_apikey.yaml`. 14 tests passing.
- M1.3 Synthetic data: `data.py` (`generate`, `apply_changes` with soft/hard deletes,
  `apply_drift`). Deterministic per seed. 18 tests passing.
- M1.4 Mock API: `mock_api.py` (`MockAPI` context manager; api_key/bearer/OAuth client
  credentials; offset/page/cursor/link pagination; `updated_since`; 429 + Retry-After with
  violation count; request log; phases initial/changed/drifted). 27 tests passing.
- Ollama model `qwen2.5-coder:3b` pulled.
- M1.5 Harness core: `harness.py` (connector contract in docstring, `load_connector`,
  `config_for`, DuckDB `Warehouse` with upsert by pk, `run_sync` capturing connector errors,
  `compare` → matched/missing/mismatched/extra/accuracy). 32 tests passing.

- M1.6 `harness.evaluate()` → `Report`: full-sync and incremental accuracy, refetched,
  missed updates/deletes, schema accuracy (field Jaccard, pk must match), 429s, rate
  violations, requests, seconds, errors. Non-incremental resources are full-refreshed on
  sync 2; hard deletes on incremental resources count as invisible. 38 tests passing.

- M1.7 16 dev scenarios in `scenarios/dev/` (all auth types × all pagination styles, rate
  limits, soft deletes, nested JSON, string pk, multi-resource, full refresh, drift
  rename/add) + load test for every scenario file. 55 tests passing.

- M1.8a Reference connectors for 4 scenarios (one per pagination style) in
  `connectors/reference/`, self-contained, stdlib only + `tests/test_reference.py` asserting
  perfect scores. 59 tests passing.

- M1.8b Reference connectors for all 16 dev scenarios, all scoring 1.0 on every metric with
  0 rate violations (rate-limited scenarios do hit a 429 each). 72 tests passing (~17 s).

## Next step

Milestone 1, step 9: held-out scenarios, in their own commit before any agent exists.
5 YAML files in `scenarios/heldout/` with combinations not in the dev set (e.g. cursor +
api_key + rate limit + nested; link + oauth + soft deletes; multi-resource page + bearer;
string pk incremental; offset + oauth + drift rename). No reference connectors are written
for them yet (step 10 adds them, kept out of any agent prompt).
