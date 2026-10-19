# Progress

## Done

- Plan written (PLAN.md). Local repo created with personal git identity.
- M1.1 Project skeleton: pyproject, src layout, `scripts/setup.py` (creates `.venv`), MIT
  license, README stub, smoke tests (2 passing).
- M1.2 Scenario format: `scenario.py` (dataclasses, YAML load, validation), example
  `scenarios/dev/contacts_offset_apikey.yaml`. 14 tests passing.

## Next step

Milestone 1, step 3: synthetic data. `src/connector_forge/data.py`: from a Scenario, generate
deterministic records per resource (seeded; ids, names, emails, ISO timestamps, nested
objects), plus `apply_changes()` producing the post-change dataset (created/updated/deleted,
soft deletes, drift renames/adds). Ground truth = this dataset. Tests for determinism and
change counts.
