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

## Next step

Milestone 1, step 7: development scenarios. Write ~16 YAML files in `scenarios/dev/` covering
the auth × pagination matrix, rate limits, soft deletes, nested JSON, string primary keys,
multiple resources, and drift (rename/add). Add a test that every file in `scenarios/` loads
and that names match filenames. (Held-out set comes in its own later commit, step 9.)
