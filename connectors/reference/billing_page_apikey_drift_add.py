"""Reference connector for scenario `billing_page_apikey_drift_add`.

Subscriptions; a new field appears after the first sync.
Reference implementation (no model involved), standard library only.
Implements the connector contract in harness.py.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

RESOURCES = {'subscriptions': {'path': '/subscriptions',
                   'primary_key': 'id',
                   'incremental': True,
                   'fields': {'id': 'int',
                              'plan': 'string',
                              'seats': 'int',
                              'updated_at': 'timestamp'}}}


def schema():
    return {name: {"primary_key": r["primary_key"], "fields": r["fields"]} for name, r in RESOURCES.items()}


def _request(url, headers, data=None):
    """Send a request, waiting out 429 responses as Retry-After asks."""
    while True:
        req = urllib.request.Request(url, headers=headers, data=data)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read()), resp.headers
        except urllib.error.HTTPError as e:
            if e.code != 429:
                raise
            time.sleep(float(e.headers.get("Retry-After", "1")) + 0.05)


def _auth_headers(config):
    return {"X-API-Key": config["credentials"]["secret"]}


def _pages(config, headers, path, params):
    page = 1
    while True:
        query = urllib.parse.urlencode({**params, "page": page})
        body, _ = _request(f"{config['base_url']}{path}?{query}", headers)
        yield body["data"]
        if page >= body["total_pages"]:
            return
        page += 1


def sync(config, state):
    state = dict(state or {})
    headers = _auth_headers(config)
    for name, r in RESOURCES.items():
        since = state.get(name)
        params = {"updated_since": since} if r["incremental"] and since else {}
        for page in _pages(config, headers, r["path"], params):
            for record in page:
                if r["incremental"]:
                    since = max(since or "", record["updated_at"])
                yield name, record
        if r["incremental"]:
            state[name] = since
    return state
