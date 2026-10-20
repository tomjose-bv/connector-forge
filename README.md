# connector-forge

A local AI agent that turns an API's documentation into a tested data connector and repairs it
when the API changes, plus an evaluation harness that measures how well it does that.
Everything runs on one machine: Ollama for the model, DuckDB for the warehouse.

**Status:** milestones 1–3 of 5 done: scenario format, mock API, evaluation harness, reference
connectors, sandbox, guarded agent tools, and three AI agents including `graph`, which tests and
fixes its own connector. Repair after API changes comes next (see [Roadmap](#roadmap)).

## How it works

```
scenario YAML ──► mock API (localhost) ◄── connector code runs here
      │                                            ▲
      ▼                                            │ writes and fixes
  API docs ──► agent (Ollama) ── tools ──► guard ──┘
                                   │
                    harness: sync → DuckDB → compare with ground truth → metrics
```

- **Scenarios** (`scenarios/`): one YAML file describes a synthetic API: auth (API key, bearer
  token, OAuth client credentials), pagination (offset, page number, cursor, Link header),
  rate limits (429 + Retry-After), incremental syncs by `updated_at`, soft deletes, nested
  JSON, string primary keys, several resources, and schema drift. Data is generated from a
  seed, so every run sees the same ground truth. 16 development scenarios and 5 held-out ones.
- **Mock API** (`mock_api.py`): standard-library HTTP server on 127.0.0.1 that serves a
  scenario, then switches to a "changed" phase (created, updated, deleted records) for the
  incremental sync.
- **Connector contract**: a Python module with `schema()` and `sync(config, state)`, a
  generator that yields `(resource, record)` and returns the next state.
- **Harness** (`harness.py`): runs a full sync and an incremental sync, loads records into
  DuckDB by primary key and compares them with the ground truth.

- **API docs** (`docs.py`): a Markdown reference generated from the scenario: auth, pagination,
  rate limits, resources and field types. It is all an agent gets, and never contains
  ground-truth values or secrets.

## Agents

| variant | what it does |
|---|---|
| `reference` | hand-written connectors, no model; proves the harness (scores 1.0 everywhere) |
| `prompt` | one model call from the docs |
| `probe` | may GET a few API pages first, then writes the connector |
| `graph` | fixed plan: probe → write → test → fix, up to 4 rounds; keeps the best version |

Agents act only through tools: `read_docs`, `probe_api` (GET to the mock API, auth added),
`write_connector`, `run_tests` (sandboxed full + incremental sync; the report gives per-resource
row counts and one field-level example of a wrong row, which is what the fix loop works from) and
`submit`. A guard allows only paths on the mock API, limits calls per tool and logs every call.
The model is `qwen2.5-coder:3b` via Ollama on localhost; nothing leaves the machine.

## Sandbox

With `evaluate(..., sandbox=True)` a connector runs in a separate Python process
(`python -I -B`) with a timeout, a temporary working directory and a minimal environment. A
Python audit hook blocks network connections other than the mock API's port, DNS lookups other
than localhost, file writes outside the working directory, and starting processes; each blocked
call is logged and counted.

This is a safety measure for a local demo, not a security boundary: code that uses native
extensions can bypass audit hooks. Don't run untrusted connectors on a machine you care about.

## Metrics

| Metric | Meaning |
|---|---|
| full-sync accuracy | rows matching ground truth by primary key ÷ (expected + extra rows) |
| incremental accuracy | the same, after the API data changes and a second sync runs |
| refetched / missed updates / missed deletes | incremental correctness detail |
| schema accuracy | field-name overlap with the true schema; 0 if the primary key is wrong |
| 429s / rate violations | rate-limit responses, and requests sent before Retry-After elapsed |
| requests, seconds, errors | cost and failures |

The hand-written `reference` connectors (no model involved) score 1.0 on every accuracy metric
with zero rate violations on all 21 scenarios; the test suite checks this on every run.

## Setup

Requires Python 3.12.

```
python scripts/setup.py
.venv\Scripts\python -m pytest -q          # Windows
.venv/bin/python -m pytest -q              # macOS/Linux
```

Run the reference connectors through the harness:

```
.venv\Scripts\connector-forge eval --set dev
.venv\Scripts\connector-forge eval --set heldout --out runs/reference-heldout.json
```

Run an agent (needs [Ollama](https://ollama.com) and `ollama pull qwen2.5-coder:3b`):

```
.venv\Scripts\connector-forge agent --variant probe --set dev --scenario events_link_none
```

Each run directory keeps every connector version the agent wrote and a `result.json`;
`summary.json` records the machine, date, model and seed. Benchmark results come with
milestone 5.

## Roadmap

1. ~~Mock API, scenario format, harness and reference connectors.~~
2. ~~Sandbox, guard, agent tools, and the `prompt` and `probe` agents.~~
3. ~~The `graph` agent with a probe → write → test → fix loop.~~
4. Schema drift and `graph+repair`: the agent repairs its connector after the API changes.
5. Runs over three seeds, results in this README, CI, v0.1.0 release.

## License

MIT
