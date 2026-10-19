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

## Next step

Milestone 1, step 6: full evaluation run. `harness.evaluate(scenario, connector_path)`:
sync 1 (initial) → score full-sync accuracy; set phase "changed" → sync 2 with returned state
→ score incremental correctness (final table == truth incl. soft deletes; count duplicates
fetched, missed updates, missed deletes); schema accuracy (connector `schema()` vs scenario
fields); rate-limit violations; request count and time. Return a `Report` dataclass
(+ `to_dict`). Tests with in-test connectors.
