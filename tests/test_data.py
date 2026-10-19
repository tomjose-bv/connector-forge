from connector_forge.data import apply_changes, apply_drift, generate
from connector_forge.scenario import parse


def scen(**over):
    d = {
        "name": "t",
        "seed": 7,
        "resources": [
            {
                "name": "users",
                "path": "/users",
                "count": 30,
                "incremental": True,
                "soft_deletes": True,
                "fields": {"id": "int", "email": "email", "updated_at": "timestamp", "addr": {"city": "string"}},
            },
            {"name": "tags", "path": "/tags", "count": 10, "fields": {"key": "string", "n": "int"}, "primary_key": "key"},
        ],
        "changes": {"created": 4, "updated": 5, "deleted": 3},
        "drift": {"rename": {"users": {"email": "email_address"}}, "add": {"tags": {"color": "string"}}},
    }
    d.update(over)
    return parse(d)


def test_deterministic():
    s = scen()
    assert generate(s) == generate(s)
    assert generate(s) != generate(scen(seed=8))


def test_shapes():
    d = generate(scen())
    assert len(d["users"]) == 30 and len(d["tags"]) == 10
    u = d["users"][1]
    assert u["deleted"] is False and isinstance(u["addr"], dict)
    assert all(isinstance(k, str) for k in d["tags"])


def test_changes_soft_and_hard_deletes():
    s = scen()
    before = generate(s)
    after = apply_changes(s, before)
    assert before == generate(s)  # input untouched
    users = after["users"]
    assert len(users) == 34
    assert sum(r["deleted"] for r in users.values()) == 3
    changed = [k for k in before["users"] if users[k] != before["users"][k]]
    assert len(changed) == 8
    assert all(users[k]["updated_at"] > before["users"][k]["updated_at"] for k in changed)
    assert len(after["tags"]) == 10 - 3 + 4  # hard deletes


def test_drift():
    s = scen()
    d = apply_drift(s, generate(s))
    u = d["users"][1]
    assert "email_address" in u and "email" not in u
    assert all("color" in r for r in d["tags"].values())
