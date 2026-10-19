from pathlib import Path

from connector_forge.scenario import load
from connector_forge.tools import ToolBox

ROOT = Path(__file__).resolve().parent.parent


def box(tmp_path, name="tickets_cursor_oauth", **kw):
    return ToolBox(load(ROOT / f"scenarios/dev/{name}.yaml"), tmp_path / "run", **kw)


def test_read_docs_and_probe_with_oauth(tmp_path):
    with box(tmp_path) as tb:
        assert "/oauth/token" in tb.call("read_docs")
        out = tb.call("probe_api", {"path": "/tickets"})
        assert out.startswith("status: 200") and "next_cursor" in out
        assert "more records (page had 15)" in out


def test_link_header_hides_base_url(tmp_path):
    with box(tmp_path, "events_link_none") as tb:
        out = tb.call("probe_api", {"path": "/events", "params": {"page": 1}})
        assert "<base_url>/events?page=2" in out and "127.0.0.1" not in out


def test_guard_blocks_other_hosts_and_limits(tmp_path):
    with box(tmp_path, limits={"probe_api": 2, "read_docs": 1}) as tb:
        assert "blocked" in tb.call("probe_api", {"path": "http://example.com/"})
        assert "blocked" in tb.call("probe_api", {"path": "//example.com/x"})
        tb.call("read_docs")
        assert "call limit" in tb.call("read_docs")
        assert "unknown" in tb.call("delete_everything")
        assert tb.blocked == 4 and len(tb.log) == 5


def test_probe_disabled_for_prompt_agent(tmp_path):
    with box(tmp_path, allow_probe=False) as tb:
        assert "disabled" in tb.call("probe_api", {"path": "/tickets"})


def test_write_run_submit(tmp_path):
    ref = (ROOT / "connectors/reference/tickets_cursor_oauth.py").read_text()
    with box(tmp_path) as tb:
        assert "no connector" in tb.call("run_tests")
        assert "syntax error" in tb.call("write_connector", {"code": "def sync(:\n"})
        assert tb.call("write_connector", {"code": ref}) == "saved version 2"
        out = tb.call("run_tests")
        assert "ALL CHECKS PASSED" in out, out
        assert tb.call("submit") == "submitted"
        assert "already submitted" in tb.call("run_tests")
    assert (tmp_path / "run/connector_v1.py").exists() and tb.connector_path.read_text() == ref


def test_run_tests_reports_failure(tmp_path):
    bad = "def schema():\n    return {}\ndef sync(config, state):\n    raise ValueError('boom')\n    yield\n"
    with box(tmp_path) as tb:
        tb.call("write_connector", {"code": bad})
        out = tb.call("run_tests")
    assert "SOME CHECKS FAILED" in out and "boom" in out
