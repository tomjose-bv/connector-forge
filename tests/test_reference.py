from pathlib import Path

import pytest

from connector_forge.harness import evaluate
from connector_forge.scenario import load

ROOT = Path(__file__).resolve().parent.parent
CONNECTORS = sorted((ROOT / "connectors" / "reference").glob("[!_]*.py"))


@pytest.mark.parametrize("path", CONNECTORS, ids=lambda p: p.stem)
def test_reference_connector_is_perfect(path):
    r = evaluate(load(ROOT / "scenarios" / "dev" / f"{path.stem}.yaml"), path)
    assert r.errors == []
    assert r.full_sync_accuracy == 1.0
    assert r.incremental_accuracy == 1.0
    assert (r.missed_updates, r.missed_deletes, r.refetched) == (0, 0, 0)
    assert r.schema_accuracy == 1.0
    assert r.rate_violations == 0
