"""Run connector code in a subprocess with a timeout and a guard (see _sandbox_runner.py).

`SandboxConnector` has the same `schema()` / `sync(config, state)` interface as a loaded
connector module, so the harness can use either.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Iterator
from urllib.parse import urlsplit

RUNNER = Path(__file__).with_name("_sandbox_runner.py")


class SandboxError(RuntimeError):
    pass


class SandboxConnector:
    def __init__(self, path: str | Path, port: int, timeout: float = 120.0):
        self.path = Path(path).resolve()
        self.port = port
        self.timeout = timeout
        self.blocked: list[dict[str, Any]] = []

    @classmethod
    def for_url(cls, path: str | Path, base_url: str, timeout: float = 120.0) -> "SandboxConnector":
        return cls(path, urlsplit(base_url).port or 80, timeout)

    def _run(self, mode: str, payload: dict[str, Any]) -> Iterator[dict[str, Any]]:
        env = {
            "SYSTEMROOT": os.environ.get("SYSTEMROOT", ""),
            "PATH": "",
            "PYTHONIOENCODING": "utf-8",
            "NO_PROXY": "*",  # keep urllib from reading system proxy settings
        }
        with tempfile.TemporaryDirectory(prefix="cf-sandbox-") as work:
            proc = subprocess.Popen(
                [sys.executable, "-I", "-B", str(RUNNER), str(self.path), str(self.port), mode],
                cwd=work,
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
            )
            lines: queue.Queue[str | None] = queue.Queue()

            def pump():
                for line in proc.stdout:
                    lines.put(line)
                lines.put(None)

            threading.Thread(target=pump, daemon=True).start()
            err_tail: list[str] = []
            threading.Thread(target=lambda: err_tail.extend(proc.stderr.read().splitlines()[-5:]), daemon=True).start()
            proc.stdin.write(json.dumps(payload) + "\n")
            proc.stdin.close()
            deadline = time.monotonic() + self.timeout
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise SandboxError(f"timed out after {self.timeout:g}s")
                    try:
                        line = lines.get(timeout=remaining)
                    except queue.Empty:
                        continue
                    if line is None:
                        proc.wait(timeout=10)
                        if proc.returncode not in (0, 1):
                            raise SandboxError(f"runner exited with {proc.returncode}: {' | '.join(err_tail)}")
                        return
                    msg = json.loads(line)
                    if msg.get("type") == "blocked":
                        self.blocked.append(msg)
                    yield msg
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()

    def schema(self) -> Any:
        for msg in self._run("schema", {}):
            if msg["type"] == "schema":
                return msg["schema"]
            if msg["type"] == "error":
                raise SandboxError(msg["error"])
        raise SandboxError("connector returned no schema")

    def sync(self, config: dict, state: Any):
        for msg in self._run("sync", {"config": config, "state": state}):
            if msg["type"] == "record":
                yield msg["resource"], msg["record"]
            elif msg["type"] == "state":
                return msg["state"]
            elif msg["type"] == "error":
                raise SandboxError(msg["error"])
        raise SandboxError("connector ended without returning a state")
