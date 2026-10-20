import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from connector_forge.llm import FakeLLM, OllamaClient, extract_code


def test_extract_code():
    text = "Here:\n```python\ndef schema():\n    return {}\n```\nand\n```\nx = 1\n```"
    assert extract_code(text) == "def schema():\n    return {}\n"
    assert extract_code("def schema(): ...\ndef sync(c, s): ...") is not None
    assert extract_code("no code here") is None
    assert extract_code("```\nPROBE /x\n```") is None


def test_fake_llm():
    llm = FakeLLM(["a", "b"])
    assert llm.chat([{"role": "user", "content": "hi"}]) == "a"
    assert llm.chat([]) == "b" and llm.usage.calls == 2
    with pytest.raises(RuntimeError):
        llm.chat([])


def test_ollama_client_against_fake_server():
    seen = {}

    class H(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            seen.update(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            body = json.dumps({"message": {"content": "ok"}, "prompt_eval_count": 12, "eval_count": 3}).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, args=(0.05,), daemon=True).start()
    try:
        c = OllamaClient(host=f"http://127.0.0.1:{srv.server_address[1]}", seed=7)
        assert c.chat([{"role": "user", "content": "hi"}]) == "ok"
    finally:
        srv.shutdown()
        srv.server_close()
    assert seen["model"] == "qwen2.5-coder:3b" and seen["options"]["seed"] == 7 and seen["stream"] is False
    assert (c.usage.prompt_tokens, c.usage.output_tokens, c.usage.calls) == (12, 3, 1)
