from pathlib import Path

import pytest

from connector_forge.harness import evaluate
from connector_forge.scenario import load

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "connectors" / "reference"
SETS = {"dev": REF, "heldout": REF / "heldout"}
CASES = [(name, p) for name, d in SETS.items() for p in sorted(d.glob("[!_]*.py"))]


@pytest.mark.parametrize("set_name, path", CASES, ids=lambda x: x.stem if isinstance(x, Path) else x)
def test_reference_connector_is_perfect(set_name, path):
    r = evaluate(load(ROOT / "scenarios" / set_name / f"{path.stem}.yaml"), path)
    assert r.errors == []
    assert r.full_sync_accuracy == 1.0
    assert r.incremental_accuracy == 1.0
    assert (r.missed_updates, r.missed_deletes, r.refetched) == (0, 0, 0)
    assert r.schema_accuracy == 1.0
    assert r.rate_violations == 0


@pytest.mark.parametrize("set_name", SETS)
def test_every_scenario_has_a_reference_connector(set_name):
    scenarios = {p.stem for p in (ROOT / "scenarios" / set_name).glob("*.yaml")}
    assert scenarios == {p.stem for p in SETS[set_name].glob("[!_]*.py")}
