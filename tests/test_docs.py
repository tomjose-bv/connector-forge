from pathlib import Path

import pytest

from connector_forge.data import generate
from connector_forge.docs import render
from connector_forge.scenario import load

ROOT = Path(__file__).resolve().parent.parent
FILES = sorted((ROOT / "scenarios").rglob("*.yaml"))


def _names(fields, prefix=""):
    for k, t in fields.items():
        yield prefix + k
        if isinstance(t, dict):
            yield from _names(t, prefix + k + ".")


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_docs_cover_scenario(path):
    s = load(path)
    doc = render(s)
    for r in s.resources:
        assert f"GET {r.path}`" in doc
        for f in _names(r.fields):
            assert f"`{f}`" in doc
        assert ("updated_since" in doc) or not r.incremental
        assert ("deleted: true" in doc) == any(x.soft_deletes for x in s.resources)
    if s.auth.type == "api_key":
        assert s.auth.header in doc
    if s.auth.type == "oauth_client_credentials":
        assert "/oauth/token" in doc
    if s.rate_limit:
        assert "Retry-After" in doc and str(s.rate_limit.requests) in doc
    # never leak secrets or drifted fields
    assert s.auth.secret not in doc
    for renames in s.drift.rename.values():
        for new in renames.values():
            assert new not in doc


def test_docs_have_no_ground_truth_values():
    s = load(ROOT / "scenarios/dev/contacts_offset_apikey.yaml")
    doc = render(s)
    rec = next(iter(generate(s)["contacts"].values()))
    assert rec["email"] not in doc and rec["name"] not in doc
