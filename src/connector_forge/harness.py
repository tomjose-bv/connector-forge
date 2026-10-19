"""Evaluation harness: run a connector against the mock API, load into DuckDB, compare.

Connector contract: a Python module with

    def schema() -> dict[str, dict]
        # {resource: {"primary_key": "id", "fields": {name: type}}}
    def sync(config: dict, state: dict | None) -> Generator[tuple[str, dict], None, dict]
        # yields (resource, record); its return value is the next state

`config` holds `base_url` and `credentials` (the scenario's auth settings).
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any

from connector_forge.data import Dataset
from connector_forge.scenario import Scenario


def load_connector(path: str | Path) -> ModuleType:
    path = Path(path)
    spec = importlib.util.spec_from_file_location(f"connector_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load connector from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for name in ("schema", "sync"):
        if not callable(getattr(module, name, None)):
            raise ImportError(f"connector {path.name} has no {name}() function")
    return module


def config_for(scenario: Scenario, base_url: str) -> dict[str, Any]:
    a = scenario.auth
    return {
        "base_url": base_url,
        "credentials": {"type": a.type, "header": a.header, "secret": a.secret, "client_id": a.client_id},
    }


def _norm(record: Any) -> Any:
    return json.loads(json.dumps(record, sort_keys=True, default=str))


class Warehouse:
    """DuckDB tables with one row per primary key: (pk VARCHAR, data JSON)."""

    def __init__(self, path: str = ":memory:"):
        import duckdb

        self.con = duckdb.connect(path)
        self._tables: set[str] = set()

    def _table(self, resource: str) -> str:
        if not resource.isidentifier():
            raise ValueError(f"bad resource name: {resource!r}")
        if resource not in self._tables:
            self.con.execute(f'CREATE TABLE IF NOT EXISTS "{resource}" (pk VARCHAR PRIMARY KEY, data JSON)')
            self._tables.add(resource)
        return resource

    def upsert(self, resource: str, pk: Any, record: dict[str, Any]) -> None:
        t = self._table(resource)
        self.con.execute(
            f'INSERT OR REPLACE INTO "{t}" VALUES (?, ?)', [str(pk), json.dumps(record, default=str)]
        )

    def rows(self, resource: str) -> dict[str, dict[str, Any]]:
        if resource not in self._tables:
            return {}
        return {pk: json.loads(data) for pk, data in self.con.execute(f'SELECT pk, data FROM "{resource}"').fetchall()}


@dataclass
class SyncResult:
    state: Any
    records: int
    error: str | None = None


def run_sync(connector: ModuleType, scenario: Scenario, config: dict, state: Any, wh: Warehouse) -> SyncResult:
    """Run one sync, upserting each record by the scenario's primary key."""
    pks = {r.name: r.primary_key for r in scenario.resources}
    count = 0
    gen = connector.sync(config, state)
    try:
        while True:
            resource, record = next(gen)
            if resource not in pks:
                raise ValueError(f"unknown resource {resource!r}")
            wh.upsert(resource, record[pks[resource]], record)
            count += 1
    except StopIteration as stop:
        return SyncResult(stop.value, count)
    except Exception as e:  # connector bugs are results, not harness crashes
        return SyncResult(state, count, f"{type(e).__name__}: {e}")


@dataclass
class ResourceScore:
    expected: int
    matched: int
    missing: int
    mismatched: int
    extra: int

    @property
    def accuracy(self) -> float:
        denom = self.expected + self.extra
        return self.matched / denom if denom else 1.0


def compare(scenario: Scenario, truth: Dataset, wh: Warehouse) -> dict[str, ResourceScore]:
    """Compare warehouse rows with the ground truth, matched by primary key."""
    out = {}
    for res in scenario.resources:
        want = {str(k): _norm(v) for k, v in truth[res.name].items()}
        got = wh.rows(res.name)
        matched = sum(1 for k, v in want.items() if k in got and got[k] == v)
        missing = sum(1 for k in want if k not in got)
        out[res.name] = ResourceScore(
            expected=len(want),
            matched=matched,
            missing=missing,
            mismatched=len(want) - matched - missing,
            extra=sum(1 for k in got if k not in want),
        )
    return out
