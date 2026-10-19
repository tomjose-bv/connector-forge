# Progress

## Done

- Plan written (PLAN.md). Local repo created with personal git identity.
- M1.1 Project skeleton: pyproject, src layout, `scripts/setup.py` (creates `.venv`), MIT
  license, README stub, smoke tests (2 passing).

## Next step

Milestone 1, step 2: scenario format. `src/connector_forge/scenario.py` with a dataclass
loaded from YAML (name, seed, auth, pagination, rate_limit, incremental, soft_deletes,
nested, drift, resources with fields + primary key) and validation; one example scenario in
`scenarios/dev/`; tests for load + validation errors.
