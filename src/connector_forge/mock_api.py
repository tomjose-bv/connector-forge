"""Mock HTTP API that serves a scenario's synthetic dataset (standard library only)."""

from __future__ import annotations

import base64
import json
import secrets
import threading
import time
from collections import deque
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit

from connector_forge.data import Dataset, apply_changes, apply_drift, generate
from connector_forge.scenario import Resource, Scenario

PHASES = ("initial", "changed", "drifted")


@dataclass
class LogEntry:
    t: float
    method: str
    path: str
    status: int


class MockAPI:
    """Serve a scenario on 127.0.0.1. Use as a context manager; `.url` is the base URL."""

    def __init__(self, scenario: Scenario):
        self.scenario = scenario
        initial = generate(scenario)
        changed = apply_changes(scenario, initial)
        self.datasets: dict[str, Dataset] = {
            "initial": initial,
            "changed": changed,
            "drifted": apply_drift(scenario, changed),
        }
        self.phase = "initial"
        self.log: list[LogEntry] = []
        self.rate_violations = 0  # requests sent before a Retry-After had elapsed
        self._lock = threading.Lock()
        self._window: deque[float] = deque()
        self._blocked_until = 0.0
        self._tokens: set[str] = set()
        self._server: ThreadingHTTPServer | None = None

    # lifecycle
    def start(self) -> "MockAPI":
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):  # noqa: N802
                api._handle(self, "GET")

            def do_POST(self):  # noqa: N802
                api._handle(self, "POST")

            def log_message(self, *args):
                pass

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=self._server.serve_forever, args=(0.05,), daemon=True).start()
        return self

    def stop(self) -> None:
        if self._server:
            self._server.shutdown()
            self._server.server_close()
            self._server = None

    def __enter__(self) -> "MockAPI":
        return self.start()

    def __exit__(self, *exc) -> None:
        self.stop()

    @property
    def url(self) -> str:
        assert self._server, "server not started"
        host, port = self._server.server_address[:2]
        return f"http://{host}:{port}"

    def set_phase(self, phase: str) -> None:
        if phase not in PHASES:
            raise ValueError(f"phase must be one of {PHASES}")
        self.phase = phase

    @property
    def dataset(self) -> Dataset:
        return self.datasets[self.phase]

    # request handling
    def _handle(self, h: BaseHTTPRequestHandler, method: str) -> None:
        parts = urlsplit(h.path)
        query = {k: v[-1] for k, v in parse_qs(parts.query).items()}
        try:
            status, body, headers = self._route(h, method, parts.path, query)
        except Exception as e:  # pragma: no cover - defensive
            status, body, headers = 500, {"error": str(e)}, {}
        with self._lock:
            self.log.append(LogEntry(time.monotonic(), method, h.path, status))
        payload = json.dumps(body).encode()
        h.send_response(status)
        h.send_header("Content-Type", "application/json")
        h.send_header("Content-Length", str(len(payload)))
        for k, v in headers.items():
            h.send_header(k, v)
        h.end_headers()
        h.wfile.write(payload)

    def _rate_limited(self) -> int | None:
        rl = self.scenario.rate_limit
        if rl is None:
            return None
        now = time.monotonic()
        with self._lock:
            if now < self._blocked_until:
                self.rate_violations += 1
                return rl.retry_after
            while self._window and now - self._window[0] >= rl.per_seconds:
                self._window.popleft()
            if len(self._window) >= rl.requests:
                self._blocked_until = now + rl.retry_after
                return rl.retry_after
            self._window.append(now)
        return None

    def _authorized(self, h: BaseHTTPRequestHandler) -> bool:
        auth = self.scenario.auth
        if auth.type == "none":
            return True
        if auth.type == "api_key":
            return h.headers.get(auth.header) == auth.secret
        value = h.headers.get("Authorization", "")
        if not value.startswith("Bearer "):
            return False
        token = value[len("Bearer "):]
        if auth.type == "bearer":
            return token == auth.secret
        with self._lock:
            return token in self._tokens

    def _token(self, h: BaseHTTPRequestHandler) -> tuple[int, Any, dict]:
        auth = self.scenario.auth
        if auth.type != "oauth_client_credentials":
            return 404, {"error": "not found"}, {}
        length = int(h.headers.get("Content-Length") or 0)
        form = {k: v[-1] for k, v in parse_qs(h.rfile.read(length).decode()).items()}
        if (
            form.get("grant_type") != "client_credentials"
            or form.get("client_id") != auth.client_id
            or form.get("client_secret") != auth.secret
        ):
            return 401, {"error": "invalid_client"}, {}
        token = secrets.token_hex(16)
        with self._lock:
            self._tokens.add(token)
        return 200, {"access_token": token, "token_type": "bearer", "expires_in": 3600}, {}

    def _route(self, h, method, path, query) -> tuple[int, Any, dict]:
        retry = self._rate_limited()
        if retry is not None:
            return 429, {"error": "rate limit exceeded"}, {"Retry-After": str(retry)}
        if method == "POST" and path == "/oauth/token":
            return self._token(h)
        res = next((r for r in self.scenario.resources if r.path == path), None)
        if res is None or method != "GET":
            return 404, {"error": "not found"}, {}
        if not self._authorized(h):
            return 401, {"error": "unauthorized"}, {}
        try:
            return self._list(res, path, query)
        except ValueError as e:
            return 400, {"error": str(e)}, {}

    def _records(self, res: Resource, query: dict[str, str]) -> list[dict[str, Any]]:
        recs = list(self.dataset[res.name].values())
        if res.incremental:
            since = query.get("updated_since")
            if since:
                recs = [r for r in recs if r["updated_at"] > since]
            recs.sort(key=lambda r: (r["updated_at"], str(r[res.primary_key])))
        else:
            recs.sort(key=lambda r: str(r[res.primary_key]))
        return recs

    def _list(self, res: Resource, path: str, query: dict[str, str]) -> tuple[int, Any, dict]:
        recs = self._records(res, query)
        size = self.scenario.pagination.page_size
        kind = self.scenario.pagination.type
        if kind == "offset":
            offset = int(query.get("offset", 0))
            limit = min(int(query.get("limit", size)), size)
            if offset < 0 or limit < 1:
                raise ValueError("offset must be >= 0 and limit >= 1")
            return 200, {"data": recs[offset: offset + limit], "total": len(recs)}, {}
        if kind == "cursor":
            cursor = query.get("cursor")
            start = int(base64.urlsafe_b64decode(cursor.encode()).decode()) if cursor else 0
            end = start + size
            nxt = base64.urlsafe_b64encode(str(end).encode()).decode() if end < len(recs) else None
            return 200, {"data": recs[start:end], "next_cursor": nxt}, {}
        page = int(query.get("page", 1))
        if page < 1:
            raise ValueError("page must be >= 1")
        chunk = recs[(page - 1) * size: page * size]
        if kind == "page":
            pages = max(1, -(-len(recs) // size))
            return 200, {"data": chunk, "page": page, "total_pages": pages}, {}
        # link: body is a bare list, next page in the Link header
        headers = {}
        if page * size < len(recs):
            q = {k: v for k, v in query.items() if k != "page"} | {"page": page + 1}
            headers["Link"] = f'<{self.url}{path}?{urlencode(q)}>; rel="next"'
        return 200, chunk, headers
