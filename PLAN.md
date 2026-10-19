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

## Future direction (after v0.1.0, roughly v5–v6)

An agent that starts from a business question instead of an API. A user describes a problem
in plain language ("revenue dipped last quarter, what happened?" or "marketing spend spiked
last month"). The agent:

1. **Clarifies the question:** which metric, which period, compared with what.
2. **Asks which apps hold the data** (CRM, ads, billing, analytics) and proposes connections.
3. **Builds and tests the connectors** with connector-forge, and loads the data into DuckDB.
4. **Models the metrics:** joins sources into a few definitions such as revenue and spend
   by channel, campaign, region and week.
5. **Diagnoses the change:** breaks the delta down by dimension, ranks the contributors and
   explains them with evidence (queries and numbers), not guesses.

Evaluated the same way as the connector work: a synthetic multi-app business with a planted
root cause (for example one campaign overspending in one region). Scores: did the agent ask
for the right sources, connect them correctly, and find the planted cause.

Open questions: real SaaS APIs need real OAuth apps and terms-of-use review; holding user
credentials would make this a hosted product with security obligations; multi-step analysis
likely needs a stronger local model than the 3B one used for connector code.

### Path there

The goal is an agent that diagnoses metric changes with evidence and is benchmarked, not a
hosted platform for customers. Diagnosis is the hardest and least crowded part, so build it
first, without live connectors:

1. **Diagnosis on DuckDB (first):** a synthetic business (orders, ad spend, billing, web
   traffic) generated from a seed, with one planted cause per scenario (for example one
   campaign overspending in one region). The agent gets a question and the loaded tables and
   must find the cause. Every claim in its answer must cite the SQL query and the numbers
   behind it.
2. **Clarifying questions:** the agent must pin down the metric, period and comparison before
   querying; scenarios include vague questions with a scripted user who answers.
3. **Source selection:** the data starts behind mock APIs (connector-forge scenarios); the
   agent must ask for and connect only the sources the question needs.
4. **End to end:** question → clarify → connect → model → diagnose, all local.

Scores: planted cause found (yes/no and rank), unsupported claims (claims without a
backing query), right sources chosen, clarifying questions asked, steps, tokens and time.

This lives in a separate repo that uses connector-forge as a library, so connector-forge stays
a focused, finished tool.
