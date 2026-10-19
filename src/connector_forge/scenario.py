"""Scenario format: one YAML file describes a synthetic API and how it behaves."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AUTH_TYPES = {"none", "api_key", "bearer", "oauth_client_credentials"}
PAGINATION_TYPES = {"offset", "page", "cursor", "link"}
SCALAR_TYPES = {"int", "float", "bool", "string", "name", "email", "timestamp"}


class ScenarioError(ValueError):
    """Raised when a scenario file is invalid."""


@dataclass(frozen=True)
class Auth:
    type: str = "none"
    header: str = "X-API-Key"
    secret: str = "test-secret"
    client_id: str = "client"


@dataclass(frozen=True)
class Pagination:
    type: str = "offset"
    page_size: int = 25


@dataclass(frozen=True)
class RateLimit:
    requests: int
    per_seconds: float
    retry_after: int = 1


@dataclass(frozen=True)
class Resource:
    name: str
    path: str
    count: int
    fields: dict[str, Any]
    primary_key: str = "id"
    incremental: bool = False
    soft_deletes: bool = False


@dataclass(frozen=True)
class Changes:
    """Changes applied to the data between the first and second sync."""

    created: int = 0
    updated: int = 0
    deleted: int = 0


@dataclass(frozen=True)
class Drift:
    """Schema changes applied after the first sync: {resource: {old: new}} and {resource: {field: type}}."""

    rename: dict[str, dict[str, str]] = field(default_factory=dict)
    add: dict[str, dict[str, str]] = field(default_factory=dict)


@dataclass(frozen=True)
class Scenario:
    name: str
    seed: int
    resources: tuple[Resource, ...]
    auth: Auth = Auth()
    pagination: Pagination = Pagination()
    rate_limit: RateLimit | None = None
    changes: Changes = Changes()
    drift: Drift = Drift()
    description: str = ""

    def resource(self, name: str) -> Resource:
        for r in self.resources:
            if r.name == name:
                return r
        raise KeyError(name)

    @property
    def has_drift(self) -> bool:
        return bool(self.drift.rename or self.drift.add)

    def fields_after_drift(self, res: Resource) -> dict[str, Any]:
        """Top-level fields of a resource once the drift is applied (renames keep their order)."""
        renames = self.drift.rename.get(res.name, {})
        fields = {renames.get(k, k): t for k, t in res.fields.items()}
        fields.update(self.drift.add.get(res.name, {}))
        return fields


def _check_fields(where: str, fields: Any) -> None:
    if not isinstance(fields, dict) or not fields:
        raise ScenarioError(f"{where}: fields must be a non-empty mapping")
    for name, typ in fields.items():
        if isinstance(typ, dict):
            _check_fields(f"{where}.{name}", typ)
        elif typ not in SCALAR_TYPES:
            raise ScenarioError(f"{where}.{name}: unknown type {typ!r}")


def _build(cls, where: str, data: Any):
    if data is None:
        return cls()
    if not isinstance(data, dict):
        raise ScenarioError(f"{where}: must be a mapping")
    try:
        return cls(**data)
    except TypeError as e:
        raise ScenarioError(f"{where}: {e}") from None


def parse(data: dict[str, Any]) -> Scenario:
    if not isinstance(data, dict):
        raise ScenarioError("scenario must be a mapping")
    for key in ("name", "seed", "resources"):
        if key not in data:
            raise ScenarioError(f"missing required key: {key}")
    known = {"name", "seed", "resources", "auth", "pagination", "rate_limit", "changes", "drift", "description"}
    unknown = set(data) - known
    if unknown:
        raise ScenarioError(f"unknown keys: {sorted(unknown)}")

    auth = _build(Auth, "auth", data.get("auth"))
    if auth.type not in AUTH_TYPES:
        raise ScenarioError(f"auth.type must be one of {sorted(AUTH_TYPES)}")
    pagination = _build(Pagination, "pagination", data.get("pagination"))
    if pagination.type not in PAGINATION_TYPES:
        raise ScenarioError(f"pagination.type must be one of {sorted(PAGINATION_TYPES)}")
    if pagination.page_size < 1:
        raise ScenarioError("pagination.page_size must be >= 1")
    rate_limit = None
    if data.get("rate_limit") is not None:
        rate_limit = _build(RateLimit, "rate_limit", data["rate_limit"])

    if not isinstance(data["resources"], list) or not data["resources"]:
        raise ScenarioError("resources must be a non-empty list")
    resources = []
    for i, raw in enumerate(data["resources"]):
        r = _build(Resource, f"resources[{i}]", raw)
        _check_fields(f"resources[{i}].fields", r.fields)
        if r.primary_key not in r.fields:
            raise ScenarioError(f"resources[{i}]: primary_key {r.primary_key!r} not in fields")
        if r.incremental and r.fields.get("updated_at") != "timestamp":
            raise ScenarioError(f"resources[{i}]: incremental needs an updated_at timestamp field")
        resources.append(r)
    names = [r.name for r in resources]
    if len(set(names)) != len(names):
        raise ScenarioError("resource names must be unique")

    drift = _build(Drift, "drift", data.get("drift"))
    for res in (*drift.rename, *drift.add):
        if res not in names:
            raise ScenarioError(f"drift: unknown resource {res!r}")
    for res_name, renames in drift.rename.items():
        r = resources[names.index(res_name)]
        for old in renames:
            if old not in r.fields or old in (r.primary_key, "updated_at"):
                raise ScenarioError(f"drift: cannot rename {res_name}.{old}")

    return Scenario(
        name=str(data["name"]),
        seed=int(data["seed"]),
        resources=tuple(resources),
        auth=auth,
        pagination=pagination,
        rate_limit=rate_limit,
        changes=_build(Changes, "changes", data.get("changes")),
        drift=drift,
        description=str(data.get("description", "")),
    )


def load(path: str | Path) -> Scenario:
    import yaml

    with open(path, encoding="utf-8") as f:
        return parse(yaml.safe_load(f))
