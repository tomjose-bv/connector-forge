import json
import urllib.error
import urllib.request
from urllib.parse import urlencode

import pytest

from connector_forge.mock_api import MockAPI
from connector_forge.scenario import parse


def scen(**over):
    d = {
        "name": "t",
        "seed": 3,
        "pagination": {"type": "offset", "page_size": 10},
        "resources": [
            {
                "name": "items",
                "path": "/items",
                "count": 25,
                "incremental": True,
                "soft_deletes": True,
                "fields": {"id": "int", "title": "string", "updated_at": "timestamp"},
            }
        ],
        "changes": {"created": 2, "updated": 3, "deleted": 1},
    }
    d.update(over)
    return parse(d)


def get(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, json.loads(r.read()), dict(r.headers)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read()), dict(e.headers)


def drain(api, style):
    """Fetch every record with the given pagination style."""
    out, base = [], f"{api.url}/items"
    if style == "offset":
        off = 0
        while True:
            _, body, _ = get(f"{base}?offset={off}")
            out += body["data"]
            off += len(body["data"])
            if off >= body["total"]:
                return out
    if style == "page":
        page = 1
        while True:
            _, body, _ = get(f"{base}?page={page}")
            out += body["data"]
            if page >= body["total_pages"]:
                return out
            page += 1
    if style == "cursor":
        url = base
        while True:
            _, body, _ = get(url)
            out += body["data"]
            if not body["next_cursor"]:
                return out
            url = f"{base}?cursor={body['next_cursor']}"
    url = base
    while url:
        _, body, headers = get(url)
        out += body
        link = headers.get("Link", "")
        url = link[1: link.index(">")] if link else None
    return out


@pytest.mark.parametrize("style", ["offset", "page", "cursor", "link"])
def test_pagination(style):
    with MockAPI(scen(pagination={"type": style, "page_size": 10})) as api:
        recs = drain(api, style)
    assert sorted(r["id"] for r in recs) == list(range(1, 26))


def test_incremental_and_phases():
    with MockAPI(scen()) as api:
        first = drain(api, "offset")
        cutoff = max(r["updated_at"] for r in first)
        api.set_phase("changed")
        _, body, _ = get(f"{api.url}/items?" + urlencode({"updated_since": cutoff}))
    assert body["total"] == 6  # 2 created + 3 updated + 1 soft-deleted
    assert sum(r["deleted"] for r in body["data"]) == 1


def test_api_key_and_bearer():
    s = scen(auth={"type": "api_key", "header": "X-Key", "secret": "k"})
    with MockAPI(s) as api:
        assert get(f"{api.url}/items")[0] == 401
        assert get(f"{api.url}/items", {"X-Key": "k"})[0] == 200
    with MockAPI(scen(auth={"type": "bearer", "secret": "tok"})) as api:
        assert get(f"{api.url}/items", {"Authorization": "Bearer bad"})[0] == 401
        assert get(f"{api.url}/items", {"Authorization": "Bearer tok"})[0] == 200


def test_oauth_client_credentials():
    s = scen(auth={"type": "oauth_client_credentials", "client_id": "cid", "secret": "cs"})
    with MockAPI(s) as api:

        def token(secret):
            form = urlencode({"grant_type": "client_credentials", "client_id": "cid", "client_secret": secret})
            req = urllib.request.Request(f"{api.url}/oauth/token", data=form.encode(), method="POST")
            try:
                with urllib.request.urlopen(req, timeout=5) as r:
                    return json.loads(r.read())["access_token"]
            except urllib.error.HTTPError as e:
                return e.code

        assert token("wrong") == 401
        tok = token("cs")
        assert get(f"{api.url}/items", {"Authorization": f"Bearer {tok}"})[0] == 200
        assert get(f"{api.url}/items", {"Authorization": "Bearer cs"})[0] == 401


def test_rate_limit():
    with MockAPI(scen(rate_limit={"requests": 2, "per_seconds": 60, "retry_after": 30})) as api:
        codes = [get(f"{api.url}/items")[0] for _ in range(4)]
        _, _, headers = get(f"{api.url}/items")
        assert codes[:2] == [200, 200] and codes[2] == 429
        assert headers["Retry-After"] == "30"
        assert api.rate_violations == 2  # requests 4 and 5 ignored Retry-After
        assert len(api.log) == 5


def test_not_found_and_bad_param():
    with MockAPI(scen()) as api:
        assert get(f"{api.url}/nope")[0] == 404
        assert get(f"{api.url}/items?offset=-1")[0] == 400
