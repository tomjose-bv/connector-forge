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


DRIFT_CASES = [(name, p) for name, d in SETS.items() for p in sorted((d / "drifted").glob("[!_]*.py"))]


@pytest.mark.parametrize("set_name, path", DRIFT_CASES, ids=lambda x: x.stem if isinstance(x, Path) else x)
def test_drifted_reference_is_perfect_and_original_is_not(set_name, path):
    from connector_forge.harness import evaluate_drift

    s = load(ROOT / "scenarios" / set_name / f"{path.stem}.yaml")
    fixed = evaluate_drift(s, path)
    assert fixed.errors == [] and fixed.accuracy == 1.0 and fixed.schema_accuracy == 1.0
    stale = evaluate_drift(s, SETS[set_name] / path.name)
    assert stale.accuracy == 1.0  # the reference passes records through unchanged
    assert stale.schema_accuracy < 1.0  # but its declared schema is now out of date


def test_every_drift_scenario_has_a_drifted_reference():
    want = {(n, f.stem) for n in SETS for f in (ROOT / "scenarios" / n).glob("*.yaml") if load(f).has_drift}
    assert want == {(n, p.stem) for n, p in DRIFT_CASES}
