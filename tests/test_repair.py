from pathlib import Path

from connector_forge.agents import run_graph, run_graph_repair
from connector_forge.llm import FakeLLM
from connector_forge.scenario import load

ROOT = Path(__file__).resolve().parent.parent
NAME = "support_link_bearer_drift_rename"
SCEN = load(ROOT / f"scenarios/dev/{NAME}.yaml")
REF = (ROOT / f"connectors/reference/{NAME}.py").read_text()
FIXED = (ROOT / f"connectors/reference/drifted/{NAME}.py").read_text()
# A connector that copies named fields breaks on the rename (assignee -> assignee_email).
MAPPED = REF.replace(
    "yield name, record",
    "yield name, {k: record[k] for k in r['fields'] if k != 'deleted'}",
)


def fenced(code):
    return f"```python\n{code}```"


def test_graph_records_drift_before(tmp_path):
    r = run_graph(SCEN, FakeLLM([fenced(REF)]), tmp_path)
    assert r.drift_before["accuracy"] == 1.0 and r.drift_before["schema_accuracy"] < 1.0
    assert r.drift_after is None


def test_repair_fixes_schema_after_rename(tmp_path):
    llm = FakeLLM([fenced(REF), "PROBE /conversations", fenced(FIXED)])
    r = run_graph_repair(SCEN, llm, tmp_path)
    assert r.variant == "graph+repair"
    assert r.drift_before["schema_accuracy"] < 1.0
    assert r.drift_after["accuracy"] == 1.0 and r.drift_after["schema_accuracy"] == 1.0
    repair_prompt = llm.seen[1][1]["content"]
    assert "API has changed" in repair_prompt and "SOME CHECKS FAILED" in repair_prompt
    probe = [c for c in r.tool_log if c["tool"] == "probe_api"]
    assert probe and "assignee_email" in probe[0]["result"]  # probes see the drifted API
    assert (tmp_path / "repair/connector.py").read_text() == FIXED


def test_repair_reports_broken_sync(tmp_path):
    llm = FakeLLM([fenced(MAPPED), fenced(FIXED)])
    r = run_graph_repair(SCEN, llm, tmp_path)
    assert r.report["full_sync_accuracy"] == 1.0  # fine before the drift
    assert r.drift_before["errors"] and "KeyError" in r.drift_before["errors"][0]
    assert r.drift_after["accuracy"] == 1.0


def test_repair_keeps_original_when_fixes_are_worse(tmp_path):
    llm = FakeLLM([fenced(REF), "no code", "still no code", "nothing"])
    r = run_graph_repair(SCEN, llm, tmp_path, repair_rounds=3)
    assert r.drift_after == r.drift_before
    assert (tmp_path / "repair/connector.py").read_text() == REF


def test_no_drift_scenario_skips_repair(tmp_path):
    scen = load(ROOT / "scenarios/dev/events_link_none.yaml")
    ref = (ROOT / "connectors/reference/events_link_none.py").read_text()
    r = run_graph_repair(scen, FakeLLM([fenced(ref)]), tmp_path)
    assert r.drift_before is None and r.drift_after is None and r.llm_calls == 1
