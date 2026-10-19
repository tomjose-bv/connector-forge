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
