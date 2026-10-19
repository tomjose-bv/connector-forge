from pathlib import Path

import pytest

from connector_forge.scenario import ScenarioError, load, parse

ROOT = Path(__file__).resolve().parent.parent


def base(**over):
    data = {
        "name": "t",
        "seed": 1,
        "resources": [{"name": "r", "path": "/r", "count": 3, "fields": {"id": "int"}}],
    }
    data.update(over)
    return data


def test_load_example():
    s = load(ROOT / "scenarios/dev/contacts_offset_apikey.yaml")
    assert s.auth.type == "api_key"
    assert s.resource("contacts").incremental


def test_defaults():
    s = parse(base())
    assert s.pagination.type == "offset" and s.auth.type == "none" and s.rate_limit is None


@pytest.mark.parametrize(
    "over, msg",
    [
        ({"auth": {"type": "magic"}}, "auth.type"),
        ({"pagination": {"type": "scroll"}}, "pagination.type"),
        ({"bogus": 1}, "unknown keys"),
        ({"resources": []}, "non-empty"),
        ({"resources": [{"name": "r", "path": "/r", "count": 1, "fields": {"id": "uuid"}}]}, "unknown type"),
        ({"resources": [{"name": "r", "path": "/r", "count": 1, "fields": {"x": "int"}}]}, "primary_key"),
        ({"resources": [{"name": "r", "path": "/r", "count": 1, "fields": {"id": "int"}, "incremental": True}]}, "updated_at"),
        ({"drift": {"rename": {"nope": {"a": "b"}}}}, "unknown resource"),
        ({"pagination": {"type": "offset", "extra": 1}}, "pagination"),
    ],
)
def test_validation(over, msg):
    with pytest.raises(ScenarioError, match=msg):
        parse(base(**over))


def test_missing_key():
    with pytest.raises(ScenarioError, match="seed"):
        parse({"name": "t", "resources": []})
