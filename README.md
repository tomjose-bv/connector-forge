# connector-forge

A local AI agent that turns an API's documentation into a tested data connector and repairs it
when the API changes, plus an evaluation harness that measures how well it does that.
Everything runs on one machine: Ollama for the model, DuckDB for the warehouse.

Status: early development.

## Setup

```
python scripts/setup.py
.venv\Scripts\python -m pytest -q      # Windows
.venv/bin/python -m pytest -q          # macOS/Linux
```
