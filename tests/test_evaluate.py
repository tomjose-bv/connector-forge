import textwrap

from connector_forge.harness import evaluate, schema_accuracy
from connector_forge.scenario import parse

SCEN = parse(
    {
        "name": "inc",
        "seed": 11,
        "pagination": {"type": "offset", "page_size": 10},
        "resources": [
            {
                "name": "items",
                "path": "/items",
                "count": 30,
                "incremental": True,
                "soft_deletes": True,
                "fields": {"id": "int", "title": "string", "updated_at": "timestamp"},
            }
        ],
        "changes": {"created": 3, "updated": 4, "deleted": 2},
    }
)

BASE = """
import json, urllib.parse, urllib.request

def schema():
    return {"items": {"primary_key": "id", "fields": {"id": "int", "title": "string",
                                                      "updated_at": "timestamp", "deleted": "bool"}}}

def fetch(config, since):
    offset = 0
    while True:
        q = {"offset": offset}
        if since:
            q["updated_since"] = since
        body = json.load(urllib.request.urlopen(f"{config['base_url']}/items?" + urllib.parse.urlencode(q)))
        yield from body["data"]
        offset += len(body["data"])
        if offset >= body["total"]:
            return
"""

INCREMENTAL = BASE + """
def sync(config, state):
    since = (state or {}).get("since")
    cursor = since
    for rec in fetch(config, SINCE_ARG):
        cursor = max(cursor or "", rec["updated_at"])
        yield "items", rec
    return {"since": cursor}
"""


def write(tmp_path, src):
    p = tmp_path / "c.py"
    p.write_text(textwrap.dedent(src))
    return p


def test_correct_incremental(tmp_path):
    r = evaluate(SCEN, write(tmp_path, INCREMENTAL.replace("SINCE_ARG", "since")))
    assert r.errors == []
    assert r.full_sync_accuracy == 1.0 and r.incremental_accuracy == 1.0
    assert (r.refetched, r.missed_updates, r.missed_deletes) == (0, 0, 0)
    assert r.schema_accuracy == 1.0 and r.requests > 0


def test_full_resync_refetches(tmp_path):
    r = evaluate(SCEN, write(tmp_path, INCREMENTAL.replace("SINCE_ARG", "None")))
    assert r.incremental_accuracy == 1.0
    assert r.refetched == 30 - 4 - 2  # everything except changed rows


def test_no_second_sync_misses_changes(tmp_path):
    src = INCREMENTAL.replace("SINCE_ARG", "since").replace(
        "def sync(config, state):", "def sync(config, state):\n    if state:\n        return state"
    )
    r = evaluate(SCEN, write(tmp_path, src))
    assert r.full_sync_accuracy == 1.0
    assert (r.missed_updates, r.missed_deletes) == (7, 2)
    assert r.incremental_accuracy < 1.0


def test_broken_connector(tmp_path):
    r = evaluate(SCEN, write(tmp_path, "def schema():\n    return {}\n"))
    assert r.full_sync_accuracy == 0.0 and r.errors[0].startswith("load:")


def test_schema_accuracy():
    assert schema_accuracy(SCEN, None) == 0.0
    assert schema_accuracy(SCEN, {"items": {"primary_key": "pk", "fields": {"id": 1}}}) == 0.0
    half = {"items": {"primary_key": "id", "fields": {"id": "int", "title": "string"}}}
    assert schema_accuracy(SCEN, half) == 0.5


def test_to_dict(tmp_path):
    d = evaluate(SCEN, write(tmp_path, INCREMENTAL.replace("SINCE_ARG", "since"))).to_dict()
    assert d["scenario"] == "inc" and "seconds" in d
