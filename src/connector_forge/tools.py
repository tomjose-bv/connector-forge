"""Agent tools for one scenario run, behind a guard.

Tools: read_docs, probe_api, write_connector, run_tests, submit. The guard allows only GET
requests to the mock API (by path; the host is fixed), enforces per-tool call limits and logs
every call. Tool results are short strings, sized for a small local model's context.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from connector_forge.docs import render
from connector_forge.scenario import Scenario

DEFAULT_LIMITS = {"read_docs": 5, "probe_api": 20, "write_connector": 10, "run_tests": 6, "submit": 1}
MAX_BODY = 1500

TOOL_SPECS = [
    {"name": "read_docs", "description": "Return the API documentation (Markdown).", "args": {}},
    {
        "name": "probe_api",
        "description": "GET a path on the API, e.g. /items?offset=0. Auth is added for you. Returns status, "
        "pagination headers and the start of the JSON body.",
        "args": {"path": "string", "params": "object (optional query parameters)"},
    },
    {
        "name": "write_connector",
        "description": "Save the full Python source of the connector (replaces the previous version).",
        "args": {"code": "string"},
    },
    {
        "name": "run_tests",
        "description": "Run the saved connector against the API (full sync, then an incremental sync) and report "
        "accuracy and errors.",
        "args": {},
    },
    {"name": "submit", "description": "Finish. The last saved connector is final.", "args": {}},
]


@dataclass
class ToolCall:
    tool: str
    args: dict[str, Any]
    ok: bool
    blocked: bool
    seconds: float
    result: str


@dataclass
class ToolBox:
    scenario: Scenario
    run_dir: Path
    limits: dict[str, int] = field(default_factory=lambda: dict(DEFAULT_LIMITS))
    allow_probe: bool = True
    log: list[ToolCall] = field(default_factory=list)
    submitted: bool = False
    versions: int = 0
    last_report: Any = None
    _api: Any = None
    _token: str | None = None

    def __post_init__(self):
        self.run_dir = Path(self.run_dir)
        self.run_dir.mkdir(parents=True, exist_ok=True)

    # lifecycle: the probe API is separate from the one run_tests starts
    def __enter__(self) -> "ToolBox":
        if self.allow_probe:
            from connector_forge.mock_api import MockAPI

            self._api = MockAPI(self.scenario).start()
        return self

    def __exit__(self, *exc) -> None:
        if self._api:
            self._api.stop()
            self._api = None

    @property
    def connector_path(self) -> Path:
        return self.run_dir / "connector.py"

    @property
    def blocked(self) -> int:
        return sum(c.blocked for c in self.log)

    def count(self, tool: str) -> int:
        return sum(1 for c in self.log if c.tool == tool and not c.blocked)

    # dispatch
    def call(self, tool: str, args: dict[str, Any] | None = None) -> str:
        args = dict(args or {})
        started = time.monotonic()
        handler = getattr(self, f"_tool_{tool}", None)
        blocked, ok = False, False
        if handler is None or (tool == "probe_api" and not self.allow_probe):
            blocked, result = True, f"error: unknown or disabled tool {tool!r}"
        elif self.submitted:
            blocked, result = True, "error: already submitted"
        elif self.count(tool) >= self.limits.get(tool, 0):
            blocked, result = True, f"error: call limit for {tool} reached ({self.limits.get(tool, 0)})"
        else:
            try:
                result, ok = handler(**args), True
            except GuardError as e:
                blocked, result = True, f"error: blocked: {e}"
            except TypeError as e:
                result = f"error: bad arguments: {e}"
        self.log.append(ToolCall(tool, _short_args(args), ok, blocked, round(time.monotonic() - started, 3), result[:300]))
        return result

    # tools
    def _tool_read_docs(self) -> str:
        return render(self.scenario)

    def _auth_headers(self) -> dict[str, str]:
        a = self.scenario.auth
        if a.type == "api_key":
            return {a.header: a.secret}
        if a.type == "bearer":
            return {"Authorization": f"Bearer {a.secret}"}
        if a.type == "oauth_client_credentials":
            if self._token is None:
                form = urlencode({"grant_type": "client_credentials", "client_id": a.client_id, "client_secret": a.secret})
                req = urllib.request.Request(f"{self._api.url}/oauth/token", data=form.encode(), method="POST")
                with urllib.request.urlopen(req, timeout=10) as r:
                    self._token = json.loads(r.read())["access_token"]
            return {"Authorization": f"Bearer {self._token}"}
        return {}

    def _tool_probe_api(self, path: str, params: dict[str, Any] | None = None) -> str:
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//") or "://" in path:
            raise GuardError("path must be a path on the API, like /items")
        if params:
            path += ("&" if "?" in path else "?") + urlencode(params)
        req = urllib.request.Request(self._api.url + path, headers=self._auth_headers())
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                status, headers, body = r.status, r.headers, r.read().decode()
        except urllib.error.HTTPError as e:
            status, headers, body = e.code, e.headers, e.read().decode()
        keep = {k: headers[k] for k in ("Link", "Retry-After") if headers.get(k)}
        if "Link" in keep:
            keep["Link"] = keep["Link"].replace(self._api.url, "<base_url>")
        body = _shorten_records(body)
        if len(body) > MAX_BODY:
            body = body[:MAX_BODY] + f"... [{len(body) - MAX_BODY} more characters]"
        return f"status: {status}\nheaders: {json.dumps(keep)}\nbody: {body}"

    def _tool_write_connector(self, code: str) -> str:
        if not isinstance(code, str) or not code.strip():
            return "error: empty code"
        self.versions += 1
        (self.run_dir / f"connector_v{self.versions}.py").write_text(code, encoding="utf-8")
        self.connector_path.write_text(code, encoding="utf-8")
        try:
            compile(code, "connector.py", "exec")
        except SyntaxError as e:
            return f"saved version {self.versions}, but it has a syntax error: line {e.lineno}: {e.msg}"
        missing = [f for f in ("def schema", "def sync") if f not in code]
        if missing:
            return f"saved version {self.versions}, but it is missing: {', '.join(missing)}"
        return f"saved version {self.versions}"

    def _tool_run_tests(self) -> str:
        from connector_forge.harness import evaluate

        if not self.connector_path.exists():
            return "error: no connector saved yet; call write_connector first"
        r = evaluate(self.scenario, self.connector_path, sandbox=True, timeout=60)
        self.last_report = r
        return summarize(r)

    def _tool_submit(self) -> str:
        self.submitted = True
        return "submitted"


class GuardError(Exception):
    pass


def summarize(r) -> str:
    lines = [
        f"full sync accuracy: {r.full_sync_accuracy:.2f}",
        f"incremental accuracy: {r.incremental_accuracy:.2f}",
        f"schema accuracy: {r.schema_accuracy:.2f}",
        f"missed updates: {r.missed_updates}, missed deletes: {r.missed_deletes}, refetched: {r.refetched}",
        f"rate limited (429): {r.rate_limited}, Retry-After violations: {r.rate_violations}",
    ]
    if r.blocked:
        lines.append(f"sandbox blocked calls: {r.blocked}")
    for phase, per in (r.details or {}).items():
        for res, d in per.items():
            if d["matched"] != d["expected"] or d["extra"]:
                lines.append(
                    f"{phase} sync, {res}: expected {d['expected']} rows, matched {d['matched']}, "
                    f"missing {d['missing']}, wrong {d['mismatched']}, unexpected {d['extra']}"
                )
                if d.get("example"):
                    lines.append(f"  example wrong row: {d['example'][:300]}")
    lines += [f"error: {e[:300]}" for e in r.errors[:3]]
    perfect = (
        not r.errors and r.full_sync_accuracy == 1 and r.incremental_accuracy == 1 and r.schema_accuracy == 1
        and r.rate_violations == 0 and r.refetched == 0
    )
    lines.append("ALL CHECKS PASSED" if perfect else "SOME CHECKS FAILED")
    return "\n".join(lines)


def _shorten_records(body: str, keep: int = 2) -> str:
    """Keep the first records of a page and every other key (pagination fields matter most)."""
    try:
        data = json.loads(body)
    except ValueError:
        return body
    if isinstance(data, list) and len(data) > keep:
        return json.dumps(data[:keep] + [f"... {len(data) - keep} more records (page had {len(data)})"])
    if isinstance(data, dict) and isinstance(data.get("data"), list) and len(data["data"]) > keep:
        n = len(data["data"])
        data["data"] = data["data"][:keep] + [f"... {n - keep} more records (page had {n})"]
        return json.dumps(data)
    return body


def _short_args(args: dict[str, Any]) -> dict[str, Any]:
    return {k: (v[:80] + "..." if isinstance(v, str) and len(v) > 80 else v) for k, v in args.items()}
