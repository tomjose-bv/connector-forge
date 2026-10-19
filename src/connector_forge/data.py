"""Deterministic synthetic data for a scenario. The generated dataset is the ground truth."""

from __future__ import annotations

import copy
import random
from datetime import datetime, timedelta, timezone
from typing import Any

from connector_forge.scenario import Resource, Scenario

BASE_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)
CHANGE_TIME = BASE_TIME + timedelta(days=60)

FIRST = ["Ada", "Ben", "Cleo", "Dev", "Eli", "Fay", "Gus", "Hana", "Ivo", "Jun", "Kai", "Lea"]
LAST = ["Abel", "Brook", "Cruz", "Dahl", "Ekko", "Frost", "Gale", "Holm", "Iyer", "Juno"]
WORDS = ["alpha", "beta", "gamma", "delta", "omega", "lumen", "nova", "pixel", "quartz", "zephyr"]

# resource name -> {primary key -> record}
Dataset = dict[str, dict[Any, dict[str, Any]]]


def iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _value(rng: random.Random, typ: Any, when: datetime) -> Any:
    if isinstance(typ, dict):
        return {k: _value(rng, t, when) for k, t in typ.items()}
    if typ == "int":
        return rng.randint(0, 10_000)
    if typ == "float":
        return round(rng.uniform(0, 1000), 2)
    if typ == "bool":
        return rng.random() < 0.5
    if typ == "name":
        return f"{rng.choice(FIRST)} {rng.choice(LAST)}"
    if typ == "email":
        return f"{rng.choice(FIRST).lower()}.{rng.randint(1, 9999)}@example.com"
    if typ == "timestamp":
        return iso(when)
    return f"{rng.choice(WORDS)}-{rng.randint(1, 999)}"


def _pk(res: Resource, n: int) -> Any:
    return n if res.fields[res.primary_key] == "int" else f"{res.name[:3]}_{n:05d}"


def _record(rng: random.Random, res: Resource, n: int, when: datetime) -> dict[str, Any]:
    rec = {k: _value(rng, t, when) for k, t in res.fields.items()}
    rec[res.primary_key] = _pk(res, n)
    if res.soft_deletes:
        rec["deleted"] = False
    return rec


def generate(scenario: Scenario) -> Dataset:
    rng = random.Random(scenario.seed)
    out: Dataset = {}
    for res in scenario.resources:
        recs = {}
        for n in range(1, res.count + 1):
            when = BASE_TIME + timedelta(minutes=rng.randint(0, 30 * 24 * 60))
            rec = _record(rng, res, n, when)
            recs[rec[res.primary_key]] = rec
        out[res.name] = recs
    return out


def apply_changes(scenario: Scenario, data: Dataset) -> Dataset:
    """Return a new dataset with the scenario's created/updated/deleted records applied."""
    rng = random.Random(scenario.seed + 1)
    out = copy.deepcopy(data)
    ch = scenario.changes
    for res in scenario.resources:
        recs = out[res.name]
        tick = iter(range(1_000_000))

        def now() -> datetime:
            return CHANGE_TIME + timedelta(seconds=next(tick))

        live = sorted((k for k, r in recs.items() if not r.get("deleted")), key=str)
        picked = rng.sample(live, min(len(live), ch.updated + ch.deleted))
        to_update, to_delete = picked[: ch.updated], picked[ch.updated :]
        for pk in to_update:
            rec = recs[pk]
            for k, t in res.fields.items():
                if k not in (res.primary_key, "updated_at") and not isinstance(t, dict):
                    rec[k] = _value(rng, t, now())
                    break
            if "updated_at" in rec:
                rec["updated_at"] = iso(now())
        for pk in to_delete:
            if res.soft_deletes:
                recs[pk]["deleted"] = True
                if "updated_at" in recs[pk]:
                    recs[pk]["updated_at"] = iso(now())
            else:
                del recs[pk]
        start = res.count + 1
        for n in range(start, start + ch.created):
            rec = _record(rng, res, n, now())
            recs[rec[res.primary_key]] = rec
    return out


def apply_drift(scenario: Scenario, data: Dataset) -> Dataset:
    """Return a new dataset with the scenario's schema drift (renames, added fields) applied."""
    rng = random.Random(scenario.seed + 2)
    out = copy.deepcopy(data)
    for res_name, renames in scenario.drift.rename.items():
        for rec in out[res_name].values():
            for old, new in renames.items():
                if old in rec:
                    rec[new] = rec.pop(old)
    for res_name, added in scenario.drift.add.items():
        for rec in out[res_name].values():
            for k, t in added.items():
                rec[k] = _value(rng, t, CHANGE_TIME)
    return out
