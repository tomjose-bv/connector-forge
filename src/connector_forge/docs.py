"""Render a scenario's API reference as Markdown. This is the only description agents get.

The docs describe the API as it is before any schema drift, and never include ground-truth
records: examples use type placeholders.
"""

from __future__ import annotations

import json
from typing import Any

from connector_forge.scenario import Resource, Scenario

PLACEHOLDER = {
    "int": 0,
    "float": 0.0,
    "bool": False,
    "string": "<string>",
    "name": "<full name>",
    "email": "<email>",
    "timestamp": "2026-01-01T00:00:00Z",
}


def _example(fields: dict[str, Any]) -> dict[str, Any]:
    return {k: _example(t) if isinstance(t, dict) else PLACEHOLDER[t] for k, t in fields.items()}


def _field_rows(fields: dict[str, Any], prefix: str = "") -> list[str]:
    rows = []
    for k, t in fields.items():
        if isinstance(t, dict):
            rows.append(f"| `{prefix}{k}` | object | |")
            rows += _field_rows(t, f"{prefix}{k}.")
        else:
            rows.append(f"| `{prefix}{k}` | {t} | |")
    return rows


def _auth(s: Scenario) -> str:
    a = s.auth
    if a.type == "none":
        return "No authentication is required."
    if a.type == "api_key":
        return (
            f"Send the API key in the `{a.header}` header on every request:\n\n"
            f"```\n{a.header}: <api key>\n```\n\n"
            "The key is `config[\"credentials\"][\"secret\"]`."
        )
    if a.type == "bearer":
        return (
            "Send a static bearer token on every request:\n\n"
            "```\nAuthorization: Bearer <token>\n```\n\n"
            "The token is `config[\"credentials\"][\"secret\"]`."
        )
    return (
        "OAuth 2.0 client credentials. Request a token with a form-encoded POST:\n\n"
        "```\nPOST /oauth/token\nContent-Type: application/x-www-form-urlencoded\n\n"
        "grant_type=client_credentials&client_id=<client id>&client_secret=<client secret>\n```\n\n"
        "Response: `{\"access_token\": \"...\", \"token_type\": \"bearer\", \"expires_in\": 3600}`.\n"
        "Then send `Authorization: Bearer <access_token>` on every request.\n"
        "The client id is `config[\"credentials\"][\"client_id\"]` and the client secret is "
        "`config[\"credentials\"][\"secret\"]`."
    )


def _pagination(s: Scenario) -> str:
    n = s.pagination.page_size
    kind = s.pagination.type
    if kind == "offset":
        return (
            f"Offset pagination. Query parameters: `offset` (default 0) and `limit` (default and maximum {n}).\n"
            "Response body: `{\"data\": [...records], \"total\": <number of matching records>}`.\n"
            "Increase `offset` by the number of records received until `offset >= total`."
        )
    if kind == "page":
        return (
            f"Page-number pagination. Query parameter: `page` (starts at 1). Pages hold {n} records.\n"
            "Response body: `{\"data\": [...records], \"page\": <page>, \"total_pages\": <count>}`.\n"
            "Request pages until `page >= total_pages`."
        )
    if kind == "cursor":
        return (
            f"Cursor pagination. Pages hold {n} records.\n"
            "Response body: `{\"data\": [...records], \"next_cursor\": <string or null>}`.\n"
            "Pass `cursor=<next_cursor>` to get the next page; stop when `next_cursor` is null.\n"
            "Keep other query parameters (such as `updated_since`) on every page."
        )
    return (
        f"Link-header pagination. Query parameter: `page` (starts at 1). Pages hold {n} records.\n"
        "The response body is a JSON array of records. When there is a next page, the response has a\n"
        "header `Link: <absolute url>; rel=\"next\"`; request that URL as is. No Link header means the last page."
    )


def _resource(r: Resource) -> str:
    lines = [f"### {r.name}", "", f"`GET {r.path}`", "", f"Primary key: `{r.primary_key}`.", ""]
    if r.incremental:
        lines += [
            "Incremental: pass `updated_since=<ISO 8601 timestamp>` to get only records with",
            "`updated_at` strictly later than it. Results are ordered by `updated_at`, then primary key.",
            "",
        ]
    else:
        lines += ["No incremental filter: every sync must read all records.", ""]
    fields = dict(r.fields)
    if r.soft_deletes:
        fields["deleted"] = "bool"
        lines += [
            "Soft deletes: deleted records stay in the API with `deleted: true` and a new `updated_at`.",
            "",
        ]
    lines += ["| field | type | |", "|---|---|---|", *_field_rows(fields), ""]
    lines += ["Example record:", "", "```json", json.dumps(_example(fields), indent=2), "```", ""]
    return "\n".join(lines)


def render(s: Scenario) -> str:
    parts = [
        f"# {s.name} API",
        "",
        s.description,
        "",
        "Base URL: `config[\"base_url\"]`. All responses are JSON. Timestamps are UTC ISO 8601 "
        "(`YYYY-MM-DDTHH:MM:SSZ`).",
        "",
        "## Authentication",
        "",
        _auth(s),
        "",
        "## Pagination",
        "",
        _pagination(s),
        "",
        "## Rate limits",
        "",
    ]
    if s.rate_limit:
        rl = s.rate_limit
        parts.append(
            f"At most {rl.requests} requests per {rl.per_seconds:g} seconds. Over the limit the API returns\n"
            "`429 Too Many Requests` with a `Retry-After` header (seconds). Wait that long before the next\n"
            "request; requests sent earlier are rejected again and counted as violations."
        )
    else:
        parts.append("No rate limit is enforced, but a 429 with `Retry-After` must still be honoured.")
    parts += ["", "## Resources", ""]
    parts += [_resource(r) for r in s.resources]
    return "\n".join(parts).rstrip() + "\n"
