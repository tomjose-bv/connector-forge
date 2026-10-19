import textwrap

import pytest

from connector_forge.harness import Warehouse, compare, config_for, load_connector, run_sync
from connector_forge.mock_api import MockAPI
from connector_forge.scenario import parse

SCEN = parse(
    {
        "name": "t",
        "seed": 5,
        "auth": {"type": "bearer", "secret": "tok"},
        "pagination": {"type": "offset", "page_size": 7},
        "resources": [
            {"name": "items", "path": "/items", "count": 20, "fields": {"id": "int", "meta": {"tag": "string"}}}
        ],
    }
)

GOOD = """
import json, urllib.request

def schema():
    return {"items": {"primary_key": "id", "fields": {"id": "int", "meta": {"tag": "string"}}}}

def sync(config, state):
    headers = {"Authorization": "Bearer " + config["credentials"]["secret"]}
    offset = 0
    while True:
        req = urllib.request.Request(f"{config['base_url']}/items?offset={offset}", headers=headers)
        body = json.load(urllib.request.urlopen(req))
        for rec in body["data"]:
            yield "items", rec
        offset += len(body["data"])
        if offset >= body["total"]:
            return {"done": True}
"""

FIRST_PAGE_ONLY = GOOD.replace("if offset >= body[\"total\"]:", "if True:")


def connector(tmp_path, src, name="conn"):
    p = tmp_path / f"{name}.py"
    p.write_text(textwrap.dedent(src))
    return load_connector(p)


def run(conn):
    wh = Warehouse()
    with MockAPI(SCEN) as api:
        result = run_sync(conn, SCEN, config_for(SCEN, api.url), None, wh)
        truth = api.dataset
    return result, compare(SCEN, truth, wh)["items"]


def test_good_connector_scores_100(tmp_path):
    result, score = run(connector(tmp_path, GOOD))
    assert result.error is None and result.state == {"done": True} and result.records == 20
    assert score.accuracy == 1.0 and score.matched == 20


def test_partial_connector(tmp_path):
    _, score = run(connector(tmp_path, FIRST_PAGE_ONLY))
    assert score.matched == 7 and score.missing == 13
    assert score.accuracy == pytest.approx(7 / 20)


def test_connector_error_is_reported(tmp_path):
    src = GOOD.replace('"Bearer "', '"Nope "')
    result, score = run(connector(tmp_path, src))
    assert "HTTPError" in result.error and score.matched == 0


def test_mismatch_and_extra():
    wh = Warehouse()
    with MockAPI(SCEN) as api:
        truth = api.dataset
    for pk, rec in truth["items"].items():
        wh.upsert("items", pk, rec | {"meta": {"tag": "x"}} if pk == 1 else rec)
    wh.upsert("items", 999, {"id": 999})
    s = compare(SCEN, truth, wh)["items"]
    assert (s.matched, s.mismatched, s.extra) == (19, 1, 1)


def test_missing_functions(tmp_path):
    with pytest.raises(ImportError, match="sync"):
        connector(tmp_path, "def schema():\n    return {}\n", "bad")
