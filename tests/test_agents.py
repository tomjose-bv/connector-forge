from pathlib import Path

from connector_forge.agents import run_probe, run_prompt
from connector_forge.llm import FakeLLM
from connector_forge.scenario import load

ROOT = Path(__file__).resolve().parent.parent
SCEN = load(ROOT / "scenarios/dev/events_link_none.yaml")
REF = (ROOT / "connectors/reference/events_link_none.py").read_text()
FENCED = f"Here is the module:\n```python\n{REF}```\n"


def test_prompt_agent_with_reference_reply(tmp_path):
    llm = FakeLLM([FENCED])
    r = run_prompt(SCEN, llm, tmp_path)
    assert r.error is None and r.llm_calls == 1
    assert r.report["full_sync_accuracy"] == 1.0 and r.report["incremental_accuracy"] == 1.0
    assert "/events" in llm.seen[0][1]["content"] and "Contract" in llm.seen[0][0]["content"]
    assert [c["tool"] for c in r.tool_log] == ["read_docs", "write_connector", "run_tests", "submit"]


def test_prompt_agent_without_code(tmp_path):
    r = run_prompt(SCEN, FakeLLM(["I cannot do that."]), tmp_path)
    assert r.report is None and "no Python code" in r.error


def test_probe_agent_probes_then_writes(tmp_path):
    llm = FakeLLM(["PROBE /events?page=1\nPROBE /events?page=2", FENCED])
    r = run_probe(SCEN, llm, tmp_path)
    assert r.report["full_sync_accuracy"] == 1.0
    probes = [c for c in r.tool_log if c["tool"] == "probe_api"]
    assert len(probes) == 2 and all(c["ok"] for c in probes)
    assert "status: 200" in llm.seen[1][-1]["content"]


def test_probe_agent_turn_limit_forces_code(tmp_path):
    llm = FakeLLM(["PROBE /events"] * 3 + ["still thinking", FENCED])
    r = run_probe(SCEN, llm, tmp_path, max_turns=3)
    assert r.llm_calls == 5 and r.report["full_sync_accuracy"] == 1.0
    assert "No more probes" in llm.seen[-1][-1]["content"]


def test_probe_limit_is_guarded(tmp_path):
    llm = FakeLLM(["\n".join(["PROBE /events"] * 5), FENCED])
    r = run_probe(SCEN, llm, tmp_path, max_probes=2)
    assert sum(1 for c in r.tool_log if c["tool"] == "probe_api") == 2
