import textwrap
from pathlib import Path

import pytest

from connector_forge.harness import evaluate
from connector_forge.sandbox import SandboxConnector, SandboxError
from connector_forge.scenario import load

ROOT = Path(__file__).resolve().parent.parent
SCEN = ROOT / "scenarios/dev/events_link_none.yaml"
REF = ROOT / "connectors/reference/events_link_none.py"


def write(tmp_path, body):
    p = tmp_path / "c.py"
    p.write_text(textwrap.dedent(body))
    return p


def run_sync(conn, config=None):
    gen = conn.sync(config or {}, None)
    out = []
    try:
        while True:
            out.append(next(gen))
    except StopIteration as stop:
        return out, stop.value


def test_reference_connector_perfect_in_sandbox():
    r = evaluate(load(SCEN), REF, sandbox=True)
    assert r.errors == [] and r.full_sync_accuracy == 1.0 and r.incremental_accuracy == 1.0
    assert r.blocked == 0


def test_records_and_state_roundtrip(tmp_path):
    p = write(tmp_path, """
        def schema():
            return {"r": {"primary_key": "id", "fields": {"id": "int"}}}
        def sync(config, state):
            yield "r", {"id": 1}
            yield "r", {"id": 2}
            return {"n": 2}
    """)
    conn = SandboxConnector(p, port=1)
    assert conn.schema()["r"]["primary_key"] == "id"
    assert run_sync(conn) == ([("r", {"id": 1}), ("r", {"id": 2})], {"n": 2})


@pytest.mark.parametrize(
    "code, event",
    [
        ("import socket; socket.create_connection(('127.0.0.1', 9), timeout=1)", "socket.connect"),
        ("import socket; socket.getaddrinfo('example.com', 80)", "socket.getaddrinfo"),
        ("open(r'%s', 'w')", "open"),
        ("import subprocess; subprocess.run(['cmd'])", "subprocess.Popen"),
        ("import os; os.system('echo hi')", "os.system"),
    ],
)
def test_guard_blocks(tmp_path, code, event):
    if "%s" in code:
        code = code % (tmp_path / "outside.txt")
    p = write(tmp_path, f"""
        def schema():
            return {{}}
        def sync(config, state):
            {code}
            yield "r", {{}}
    """)
    conn = SandboxConnector(p, port=1)
    with pytest.raises(SandboxError, match="blocked by sandbox"):
        run_sync(conn)
    assert conn.blocked[0]["event"] == event
    assert not (tmp_path / "outside.txt").exists()


def test_writes_inside_workdir_allowed(tmp_path):
    p = write(tmp_path, """
        def schema():
            return {}
        def sync(config, state):
            with open("cache.json", "w") as f:
                f.write("{}")
            return {"ok": True}
            yield
    """)
    assert run_sync(SandboxConnector(p, port=1)) == ([], {"ok": True})


def test_timeout(tmp_path):
    p = write(tmp_path, """
        import time
        def schema():
            return {}
        def sync(config, state):
            time.sleep(30)
            yield "r", {}
    """)
    with pytest.raises(SandboxError, match="timed out"):
        run_sync(SandboxConnector(p, port=1, timeout=1.5))


def test_import_time_code_is_guarded(tmp_path):
    p = write(tmp_path, "import os\nos.system('echo hi')\ndef schema():\n    return {}\n")
    with pytest.raises(SandboxError, match="blocked"):
        SandboxConnector(p, port=1).schema()
