# connector-forge: plan

A local AI agent that turns an API's documentation into a tested data connector, and repairs
it when the API changes, plus an evaluation harness that measures how well it does that.
Everything runs on one machine: Ollama for the model, DuckDB for the warehouse.

## Architecture

```
scenario YAML ──► mock API (localhost) ◄── connector code runs here (sandboxed)
      │                                            ▲
      ▼                                            │ writes and fixes
  API docs ──► agent (Ollama) ── tools ──► guard ──┘
                                   │
                    harness: sync → DuckDB → compare with ground truth → metrics
```

- **Mock API server:** Python standard library (`http.server`), synthetic data generated from
  a seed. Each scenario YAML sets:
  - auth: API key, bearer token, or OAuth client credentials
  - pagination: offset, page number, cursor, or Link header
  - rate limits: 429 responses with Retry-After
  - incremental syncs by `updated_at`
  - soft deletes
  - nested JSON
  - schema drift: a field renamed or added after the first sync
- **Connector contract:** a Python module with `schema()` and `sync(state)`, which yields
  records and returns the next state. The harness loads the records into DuckDB.
- **Agent tools:** `read_docs`, `probe_api` (GET to the mock API only), `write_connector`,
  `run_tests` (runs a sync, returns a short diff report against the ground truth), `submit`.
- **Guard:** blocks other hosts, file writes outside the sandbox and excess calls; every call
  is logged.
- **Sandbox:** generated code runs in a subprocess with a timeout and network limited to
  localhost. The README must say this is a safety measure for a local demo, not a security
  boundary.

## Agent variants

1. `reference`: hand-written connectors, no AI. Proves the harness; target 100%.
2. `prompt`: one attempt from the docs.
3. `probe`: may call the mock API before writing.
4. `graph`: fixed plan of steps: probe → write → test → fix, up to N rounds.
5. `graph+repair`: also re-syncs after the API changes and fixes the connector itself.

## Scenarios and metrics

- About 16 development scenarios plus 5 held-out ones. The held-out scenarios are fixed in
  their own commit before any agent is written.
- Metrics:
  - full-sync row accuracy, matched by primary key
  - incremental correctness: no duplicates, misses or missed deletes
  - schema accuracy
  - rate-limit compliance
  - recovery after API changes
  - rounds needed, tokens and time
  - calls blocked by the guard

## Milestones (each split into small committed steps)

1. Mock API, scenario format, harness and the `reference` connectors.
2. Sandbox, guard, agent tools, and the `prompt` and `probe` agents.
3. The `graph` agent with its test-and-fix loop.
4. Schema drift and `graph+repair`.
5. Real runs over three seeds, README with results, CI, v0.1.0 release (ask before pushing).

## Stack

Python 3.12, duckdb, pyyaml, pytest. Ollama with `qwen2.5-coder:3b` (optional
`qwen2.5-coder:7b`). No web framework.
