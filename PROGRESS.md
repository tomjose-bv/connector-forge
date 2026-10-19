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

- M1.9 5 held-out scenarios in `scenarios/heldout/`, committed on their own before any
  agent code exists. 77 tests passing.

- M1.10 Reference connectors for the 5 held-out scenarios in
  `connectors/reference/heldout/` (never to be shown to agents); all perfect. 83 tests.

- M1.11 CLI `connector-forge eval --set dev|heldout --variant reference [--scenario X]
  [--out file.json]` (table + JSON with machine/date). Employer-terms checks clean (tree and
  history). 84 tests passing (~12 s).
- **Milestone 1 done.**
- M2.1 `docs.py` renders a Markdown API reference per scenario (auth, pagination, rate
  limits, resources, fields, example with placeholders). Pre-drift schema only; no secrets
  or ground-truth values. 106 tests passing. Work is on local branch `dev`; push one
  milestone per day to main after asking.
- M2.2 Sandbox: `sandbox.py` + `_sandbox_runner.py` (subprocess, timeout, temp workdir,
  audit-hook guard for network/DNS/file writes/processes, blocked-call log).
  `evaluate(sandbox=True)`, Report.blocked. All 21 reference connectors perfect in the
  sandbox. README section. 116 tests passing.

## Ideas for later

- Business-question agent platform: added to PLAN.md under "Future direction".

## Next step

Milestone 2, step 3: agent tools + guard. `src/connector_forge/tools.py`: a ToolBox for one
scenario run with read_docs(), probe_api(path, params) (GET to the mock API only, with auth
handled by the toolbox, response truncated), write_connector(code) (saved in the run dir),
run_tests() (sandboxed evaluate, short diff report), submit(). Guard: per-tool call limits,
only mock-API paths, every call logged. Tests without a model.
