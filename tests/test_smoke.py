import connector_forge
from connector_forge.cli import main


def test_version():
    assert connector_forge.__version__


def test_cli_runs():
    assert main([]) == 0


def test_cli_eval_one_scenario(tmp_path, capsys):
    import json
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    out = tmp_path / "r.json"
    code = main(["eval", "--root", str(root), "--scenario", "events_link_none", "--out", str(out)])
    assert code == 0
    data = json.loads(out.read_text())
    assert data["meta"]["machine"] and data["reports"][0]["full_sync_accuracy"] == 1.0
    assert "events_link_none" in capsys.readouterr().out


def test_cli_agent_with_fake_llm(tmp_path):
    import argparse
    import json
    from pathlib import Path

    from connector_forge.cli import cmd_agent
    from connector_forge.llm import FakeLLM

    root = Path(__file__).resolve().parent.parent
    ref = (root / "connectors/reference/events_link_none.py").read_text()
    args = argparse.Namespace(root=str(root), set="dev", scenario=["events_link_none"], variant="prompt",
                              model="fake", seed=1, temperature=0.0, out=str(tmp_path / "run"))
    assert cmd_agent(args, llm=FakeLLM([f"```python\n{ref}```"])) == 0
    summary = json.loads((tmp_path / "run/summary.json").read_text())
    assert summary["results"][0]["report"]["full_sync_accuracy"] == 1.0
    assert (tmp_path / "run/events_link_none/connector_v1.py").exists()
