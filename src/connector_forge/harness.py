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
from dataclasses import asdict, dataclass, field
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

    def clear(self, resource: str) -> None:
        self.con.execute(f'DELETE FROM "{self._table(resource)}"')

    def rows(self, resource: str) -> dict[str, dict[str, Any]]:
        if resource not in self._tables:
            return {}
        return {pk: json.loads(data) for pk, data in self.con.execute(f'SELECT pk, data FROM "{resource}"').fetchall()}


@dataclass
class SyncResult:
    state: Any
    records: int
    error: str | None = None
    keys: list[tuple[str, str]] = field(default_factory=list)  # (resource, pk) per yielded record


def run_sync(connector: ModuleType, scenario: Scenario, config: dict, state: Any, wh: Warehouse) -> SyncResult:
    """Run one sync, upserting each record by the scenario's primary key."""
    pks = {r.name: r.primary_key for r in scenario.resources}
    keys: list[tuple[str, str]] = []
    try:
        gen = connector.sync(config, state)
        while True:
            resource, record = next(gen)
            if resource not in pks:
                raise ValueError(f"unknown resource {resource!r}")
            wh.upsert(resource, record[pks[resource]], record)
            keys.append((resource, str(record[pks[resource]])))
    except StopIteration as stop:
        return SyncResult(stop.value, len(keys), keys=keys)
    except Exception as e:  # connector bugs are results, not harness crashes
        return SyncResult(state, len(keys), f"{type(e).__name__}: {e}", keys)


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


def schema_accuracy(scenario: Scenario, declared: Any, drifted: bool = False) -> float:
    """Mean over resources of field-name Jaccard similarity; 0 for a resource with a wrong primary key."""
    if not isinstance(declared, dict):
        return 0.0
    scores = []
    for res in scenario.resources:
        fields = scenario.fields_after_drift(res) if drifted else res.fields
        want = set(fields) | ({"deleted"} if res.soft_deletes else set())
        got = declared.get(res.name)
        if not isinstance(got, dict) or got.get("primary_key") != res.primary_key:
            scores.append(0.0)
            continue
        names = set(got.get("fields") or {})
        scores.append(len(want & names) / len(want | names))
    return sum(scores) / len(scores)


def _total_accuracy(scores: dict[str, ResourceScore]) -> float:
    matched = sum(s.matched for s in scores.values())
    denom = sum(s.expected + s.extra for s in scores.values())
    return matched / denom if denom else 1.0


@dataclass
class Report:
    scenario: str
    connector: str
    full_sync_accuracy: float
    incremental_accuracy: float
    refetched: int  # unchanged records fetched again by the second sync
    missed_updates: int  # created or updated records wrong after the second sync
    missed_deletes: int  # soft-deleted records not marked deleted after the second sync
    schema_accuracy: float
    rate_limited: int  # 429 responses
    rate_violations: int  # requests sent before Retry-After elapsed
    requests: int
    seconds: float
    errors: list[str]
    blocked: int = 0  # calls blocked by the sandbox guard
    details: dict[str, Any] = field(default_factory=dict)  # per-phase, per-resource counts and a diff sample

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _incremental_truth(scenario: Scenario, before: Dataset, after: Dataset) -> Dataset:
    """What a correct connector can see after sync 2: hard deletes on incremental resources are invisible."""
    out = {}
    for res in scenario.resources:
        recs = dict(after[res.name])
        if res.incremental:
            for pk, rec in before[res.name].items():
                recs.setdefault(pk, rec)
        out[res.name] = recs
    return out


def evaluate(scenario: Scenario, connector_path: str | Path, sandbox: bool = False, timeout: float = 120.0) -> Report:
    """Full sync, then an incremental sync after the API data changes; score both.

    With `sandbox=True` the connector runs in a guarded subprocess (see sandbox.py).
    """
    import time

    from connector_forge.mock_api import MockAPI

    errors: list[str] = []
    details: dict[str, Any] = {}
    wh = Warehouse()
    started = time.monotonic()
    with MockAPI(scenario) as api:
        try:
            if sandbox:
                from connector_forge.sandbox import SandboxConnector

                connector = SandboxConnector.for_url(connector_path, api.url, timeout)
            else:
                connector = load_connector(connector_path)
            declared = connector.schema()
        except Exception as e:
            connector, declared = None, None
            errors.append(f"load: {type(e).__name__}: {e}")
        before, after = api.datasets["initial"], api.datasets["changed"]
        config = config_for(scenario, api.url)
        state = None
        full = inc = {}
        keys2: list[tuple[str, str]] = []
        if connector is not None:
            r1 = run_sync(connector, scenario, config, None, wh)
            if r1.error:
                errors.append(f"sync 1: {r1.error}")
            full = compare(scenario, before, wh)
            details["full"] = _detail(scenario, before, wh, full)
            state = r1.state
            api.set_phase("changed")
            for res in scenario.resources:
                if not res.incremental:
                    wh.clear(res.name)  # full-refresh resources are replaced on every sync
            r2 = run_sync(connector, scenario, config, state, wh)
            if r2.error:
                errors.append(f"sync 2: {r2.error}")
            keys2 = r2.keys
        truth2 = _incremental_truth(scenario, before, after)
        inc = compare(scenario, truth2, wh) if connector is not None else {}
        if inc:
            details["incremental"] = _detail(scenario, truth2, wh, inc)
        rate_limited = sum(1 for e in api.log if e.status == 429)
        violations, requests = api.rate_violations, len(api.log)
        blocked = len(getattr(connector, "blocked", []))

    refetched = missed_updates = missed_deletes = 0
    for res in scenario.resources:
        if not res.incremental:
            continue
        old = {str(k): _norm(v) for k, v in before[res.name].items()}
        new = {str(k): _norm(v) for k, v in after[res.name].items()}
        got = wh.rows(res.name)
        refetched += sum(1 for r, pk in keys2 if r == res.name and pk in new and old.get(pk) == new[pk])
        for pk, rec in new.items():
            if old.get(pk) != rec and got.get(pk) != rec:
                if rec.get("deleted") is True:
                    missed_deletes += 1
                else:
                    missed_updates += 1

    return Report(
        scenario=scenario.name,
        connector=str(connector_path),
        full_sync_accuracy=_total_accuracy(full) if full else 0.0,
        incremental_accuracy=_total_accuracy(inc) if inc else 0.0,
        refetched=refetched,
        missed_updates=missed_updates,
        missed_deletes=missed_deletes,
        schema_accuracy=schema_accuracy(scenario, declared),
        rate_limited=rate_limited,
        rate_violations=violations,
        requests=requests,
        seconds=round(time.monotonic() - started, 3),
        errors=errors,
        blocked=blocked,
        details=details,
    )


def _detail(scenario: Scenario, truth: Dataset, wh: Warehouse, scores: dict[str, ResourceScore]) -> dict[str, Any]:
    """Counts per resource, plus one example of a mismatched record (field-level)."""
    out = {}
    for res in scenario.resources:
        sc = scores[res.name]
        d: dict[str, Any] = asdict(sc)
        if sc.mismatched:
            got = wh.rows(res.name)
            for pk, rec in truth[res.name].items():
                want, have = _norm(rec), got.get(str(pk))
                if have is not None and have != want:
                    diffs = []
                    for k in sorted(set(want) | set(have)):
                        if want.get(k, "<absent>") != have.get(k, "<absent>"):
                            diffs.append(f"{k}: expected {str(want.get(k, '<absent>'))[:60]!s}, got {str(have.get(k, '<absent>'))[:60]!s}")
                    d["example"] = f"{res.primary_key}={pk}: " + "; ".join(diffs[:4])
                    break
        out[res.name] = d
    return out


@dataclass
class DriftReport:
    """A fresh full sync after the API's schema drifted, scored against the drifted ground truth."""

    scenario: str
    connector: str
    accuracy: float
    schema_accuracy: float
    rate_violations: int
    requests: int
    seconds: float
    errors: list[str]
    blocked: int = 0
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_drift(scenario: Scenario, connector_path: str | Path, sandbox: bool = False, timeout: float = 120.0) -> DriftReport:
    import time

    from connector_forge.mock_api import MockAPI

    errors: list[str] = []
    wh = Warehouse()
    started = time.monotonic()
    scores: dict[str, ResourceScore] = {}
    details: dict[str, Any] = {}
    with MockAPI(scenario) as api:
        api.set_phase("drifted")
        truth = api.dataset
        try:
            if sandbox:
                from connector_forge.sandbox import SandboxConnector

                connector = SandboxConnector.for_url(connector_path, api.url, timeout)
            else:
                connector = load_connector(connector_path)
            declared = connector.schema()
        except Exception as e:
            connector, declared = None, None
            errors.append(f"load: {type(e).__name__}: {e}")
        if connector is not None:
            r = run_sync(connector, scenario, config_for(scenario, api.url), None, wh)
            if r.error:
                errors.append(f"sync: {r.error}")
            scores = compare(scenario, truth, wh)
            details["drifted"] = _detail(scenario, truth, wh, scores)
        violations, requests = api.rate_violations, len(api.log)
        blocked = len(getattr(connector, "blocked", []))
    return DriftReport(
        scenario=scenario.name,
        connector=str(connector_path),
        accuracy=_total_accuracy(scores) if scores else 0.0,
        schema_accuracy=schema_accuracy(scenario, declared, drifted=True),
        rate_violations=violations,
        requests=requests,
        seconds=round(time.monotonic() - started, 3),
        errors=errors,
        blocked=blocked,
        details=details,
    )
