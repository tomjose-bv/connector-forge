"""Reference connector for scenario `accounts_link_apikey_ratelimit`.

Accounts with Link pagination, an API key and a strict rate limit.
Reference implementation (no model involved), standard library only.
Implements the connector contract in harness.py.
"""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

RESOURCES = {'accounts': {'path': '/accounts',
              'primary_key': 'id',
              'incremental': True,
              'fields': {'id': 'int',
                         'company': 'string',
                         'plan': 'string',
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
    return {"X-Api-Token": config["credentials"]["secret"]}


def _next_link(header):
    for part in (header or "").split(","):
        url, _, rel = part.partition(";")
        if 'rel="next"' in rel:
            return url.strip()[1:-1]
    return None


def _pages(config, headers, path, params):
    url = f"{config['base_url']}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params)
    while url:
        body, resp_headers = _request(url, headers)
        yield body
        url = _next_link(resp_headers.get("Link"))


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
